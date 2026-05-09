# Backup & Restore — Design

**Date:** 2026-05-09
**Status:** Approved, pending implementation plan
**Owner:** kathail

## Problem

Candy Dash is a live production app. The current `/admin/backups` page exports per-table CSVs, which are useful for spreadsheet inspection but cannot rebuild the database — CSVs lose schema, foreign keys, ID continuity, and money/date precision. There is no automated cadence; backups only happen if a human remembers to click. If Railway is lost or corrupted, recovery from CSVs would be a multi-day reconstruction project.

## Goals

1. **Restorable backup** — a single file that, given the matching schema, deterministically rebuilds the entire database.
2. **In-app restore** — admin can upload a backup file and restore from it without shell access.
3. **Daily automation** — a backup is produced and emailed every day with no human action.
4. **CLI parity** — every web action also has a CLI equivalent for emergency recovery.

## Non-goals

- Selective / per-table restore.
- Schema migration as part of restore (restore assumes target DB is at the matching alembic head).
- Background-job restore (kept synchronous so admin sees errors immediately).
- Cloud-storage destinations (email-only for v1).
- File uploads / blob storage backup (the app stores no user-uploaded files).

## Architecture

**New files:**
- `app/backup.py` — pure logic.
  - `make_backup() -> bytes` builds and returns a zip.
  - `restore_backup(zip_bytes) -> RestoreResult` validates and restores in one transaction.
  - `email_backup(zip_bytes) -> None` sends via `app.mail.send_email`.
- `app/cli.py` — already exists with `flask mail send-test`. Add a `backup` Click group:
  - `flask backup now [--no-email] [--out PATH]`
  - `flask backup restore PATH [--confirm RESTORE]`
- `app/mail.py` — already exists. Reused as-is.

**Modified files:**
- `app/routes/admin.py` — add three routes:
  - `GET  /admin/backups/full-archive` — download zip
  - `POST /admin/backups/email-now` — trigger immediate email send
  - `POST /admin/backups/restore` — accept upload + confirmation, run restore
- `templates/admin/backups.html` — add a top "Restorable Backup" section with the three controls. Existing CSV section stays untouched below it.
- `app/__init__.py` — already registers CLI. No further changes.

**No new dependencies beyond what is already added** (`resend`, `python-dotenv`).

**Storage:** auto-snapshots written to `instance/backups/pre-restore-<timestamp>.zip`. Retention: keep last 3, delete older.

## Backup file format

Zip named `candy_dash_backup_<YYYY-MM-DD>_<HHMMSS>.zip`.

**Contents:**

```
manifest.json
tables/
  users.json
  customers.json
  invoices.json
  ...
  alembic_version.json
```

**`manifest.json`:**
```json
{
  "format_version": 1,
  "app": "candy_dash",
  "created_at": "2026-05-09T03:00:00Z",
  "alembic_version": "c3d4e5f6a7b8",
  "tables": [
    {"name": "users", "rows": 4},
    {"name": "customers", "rows": 137}
  ]
}
```

**`tables/<table>.json`:** JSON array of row dicts. One file per SQLAlchemy model in `db.metadata.sorted_tables` order (FK-aware).

**Type encoding:**
| SQLAlchemy type | JSON encoding |
|---|---|
| `Integer`, `Boolean`, `String`, `Text` | native JSON |
| `Numeric` / `Decimal` | quoted string preserving precision: `"12.50"` |
| `DateTime` | ISO 8601 with `Z` suffix |
| `Date` | `"YYYY-MM-DD"` |
| `LargeBinary` | base64 string with `__b64__` wrapper (none currently) |
| `None` | `null` |

The `alembic_version` table is included like any other table so the schema marker round-trips through restore.

## Restore flow

**Web trigger:** `POST /admin/backups/restore` with file upload + typed `RESTORE` confirmation. Gated by `@admin_required` (owner + admin). Demo users blocked by existing middleware.

**CLI trigger:** `flask backup restore PATH --confirm RESTORE`. Same code path.

**Pre-flight validation** (no DB writes yet):
1. Zip opens cleanly. Contains `manifest.json`.
2. `format_version == 1`.
3. `manifest.alembic_version == current alembic head`. **Hard refuse** on mismatch — restoring data into the wrong schema corrupts silently.
4. Every table named in manifest exists in current models. Tables in current models but absent from manifest → log warning, leave empty.
5. Zip-slip protection: every entry must be `manifest.json` or `tables/<simple-name>.json` with no path separators.

**Auto-snapshot:** Before any DELETE, run `make_backup()` and write to `instance/backups/pre-restore-<timestamp>.zip`. Trim to last 3. **If snapshot creation fails, abort the restore.**

**Restore transaction:**
1. `BEGIN`.
2. For each table in **reverse** sorted order: `DELETE FROM <table>`.
3. For each table in forward sorted order: bulk-insert via `db.session.execute(insert(model.__table__), rows)`.
4. **Postgres only:** for each table with a serial/identity PK, `SELECT setval(pg_get_serial_sequence(table, pk), GREATEST(MAX(pk), 1))`. SQLite handles autoincrement via `sqlite_sequence` (updated explicitly to `MAX(pk)`).
5. `COMMIT`. Any exception → rollback, surface message, DB unchanged.

**Post-restore:**
- Rotate `app.secret_key` for the current process to invalidate session cookies. (Documented caveat: in multi-worker prod, redeploy after restore for a clean cut.)
- Flash: `Restored N tables, M total rows. Snapshot saved at <path>.`

## Email content & automation

**Both manual "Email now" and the daily cron use the same `email_backup()` function.**

- **Subject:** `[Candy Dash] Backup 2026-05-09 — 137 customers, 412 payments`
- **Body:** plain text + HTML, identical content. Includes timestamp, alembic version, per-table row counts, restore instructions.
- **Attachment:** the zip.
- **From:** `RESEND_FROM` env (`onboarding@resend.dev` initially; switch to verified domain later).
- **To:** `BACKUP_EMAIL_TO` env. Comma-separated list supported.

**Resend size limits:** 40 MB attachment, 50 MB total. Current data well under. If a future backup exceeds 35 MB, log warning and skip the email send; the local zip still succeeds. Cloud-storage fallback deferred to v2.

## Cron on Railway

Setup steps (executed when implementation is ready, not before):

1. Add a new service to the existing project: cron type, command `flask backup now`.
2. Reference the same env vars as the web service: `DATABASE_URL`, `RESEND_API_KEY`, `RESEND_FROM`, `BACKUP_EMAIL_TO`, `SECRET_KEY`.
3. Schedule: `0 7 * * *` UTC (3 AM Eastern during DST). User to choose final time.
4. Verify first run lands an email; from then on it runs unattended.

CLI exit code is non-zero on any failure so Railway marks the run failed and surfaces it in the dashboard.

## Error handling

| Scenario | Behavior |
|---|---|
| SMTP/Resend send fails (CLI) | Log error, exit non-zero. Cron service marks failure. |
| SMTP/Resend send fails (admin button) | Flash error with exception detail. Backup zip still available for download. |
| Zip upload missing manifest.json | Refuse, flash "Not a valid backup file." |
| `format_version` unknown | Refuse, flash "Backup format vN; this version supports v1." |
| `alembic_version` mismatch | Refuse, flash "Backup is from schema X; current schema is Y. Apply matching migrations first." |
| Restore raises mid-transaction | Rollback, flash full error, DB unchanged. |
| Pre-restore snapshot fails | Abort restore. |
| Demo user attempts restore | Blocked by existing middleware. |
| Backup file > 35 MB on cron run | Log warning, skip email, local zip still produced. |

## Testing

**Unit tests** (`tests/test_backup.py` — create `tests/` dir if absent):
- `make_backup()` returns valid zip with manifest + per-table JSON files.
- Manifest table list matches `db.metadata.sorted_tables` exactly.
- Decimal `12.50` round-trips as `"12.50"` (not `12.5`).
- Datetime round-trips identical within 1µs.
- `restore_backup(make_backup())` is a no-op (row counts and content identical pre/post).
- Restore with mismatched `alembic_version` raises and DB is untouched.
- Restore with corrupt zip raises and DB is untouched.
- Restore with unknown extra table in manifest raises.

**Integration test (manual, local SQLite):**
1. Fresh DB. Login as admin, add 3 customers, 2 payments, 1 route stop.
2. Download full backup → save zip.
3. Add 2 more customers.
4. Restore from backup → upload zip → type RESTORE → submit.
5. Verify extra customers gone, originals remain, counts match.
6. Verify `instance/backups/pre-restore-*.zip` exists.
7. Create another customer, verify no PK collision.
8. Verify logged out (re-login).
9. `flask backup now --no-email --out /tmp/test.zip` → identical zip (modulo timestamp).
10. `flask backup restore /tmp/test.zip --confirm RESTORE` → CLI path works.
11. `flask backup now` → email arrives at `kyle.cahill@pm.me` with attachment.

**Out of automated test scope:**
- Postgres sequence reset (smoke-test on first prod backup).
- Concurrent writes during restore (admin-triggered, seconds-long, accepted).
- Email deliverability beyond "Resend accepted it" (already proven end-to-end).

## Acceptance criteria

- Local round-trip works (backup + restore returns DB to identical state).
- Manual download from `/admin/backups` produces a valid zip.
- Manual upload + restore from `/admin/backups` succeeds with typed-RESTORE confirmation.
- `flask backup now` produces and emails a zip; exit code reflects success/failure.
- `flask backup restore <file>` works from shell.
- Auto-snapshot before restore is created; retention keeps last 3.
- Schema-mismatch refusal verified.
- All existing CSV download routes still work, untouched.
