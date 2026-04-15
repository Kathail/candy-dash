# Candy Dash — Claude Code Guide

## What This Is
Route planning and customer management system for Northern Sweet Supply, a candy distribution business. Flask + PostgreSQL, deployed on Railway, used daily by delivery drivers on mobile and office staff on desktop.

**This app is live in production. Never push without asking.**

## Tech Stack
- **Backend**: Flask 3.x, SQLAlchemy 2.x, Flask-Login, Flask-WTF (CSRF), Flask-Limiter, Flask-Migrate (Alembic)
- **Database**: PostgreSQL (Railway production), SQLite (local dev)
- **Frontend**: Tailwind CSS 4.x, Alpine.js, HTMX, Chart.js — all vendored in `static/vendor/`
- **PDF**: ReportLab for receipt/invoice/PO generation
- **Deploy**: Gunicorn on Railway, Nixpacks start command runs `flask db upgrade` then gunicorn. `build.sh` only installs pip dependencies.

## Project Structure
```
app/
  __init__.py          # App factory, extensions, security headers, readonly guard
  models.py            # 12 SQLAlchemy models (Customer, Payment, Invoice, RouteStop, etc.)
  helpers.py           # Decorators, PDF generation, receipt numbers, template filters
  init_db.py           # Auto-migration, seed data
  routes/              # 16 blueprints (customers.py is largest at ~1100 lines)
templates/             # Jinja2 templates (base.html, partials/, auth/, reports/, etc.)
static/css/app.css     # Theme variables, custom utilities (bg-panel, theme-input, etc.)
migrations/versions/   # 3 Alembic migrations
```

## Key Patterns

### Financial Operations
- All balance mutations use `with_for_update()` row locking on Customer
- Payment recording is atomic: sale + payment + FIFO invoice marking in one transaction
- FIFO invoice marking stores `paid_by_payment_id` FK on Invoice for precise reversal
- Payment deletion restores `previous_balance` directly (not arithmetic reconstruction)
- Receipt numbers: `INV-YYYYMMDD-XXXX` with UUID fallback for collisions
- After `db.session.flush()`, always assert `payment.id is not None` before using it for FIFO FK tracking
- **Sales vs Collections**: `Payment.amount_sold` = goods delivered (sales). `Payment.amount` = money received (collections). Any metric labeled "sales", "revenue", or "Total Sales" must use `amount_sold` (or `Invoice.amount`). Only bookkeeper/collections views should use `Payment.amount`. Never sum the two together.

### PDF Generation
- User data in ReportLab `Paragraph()` must be XML-escaped (`xml.sax.saxutils.escape`) — `&` in customer names crashes PDFs
- `pdf_table_response` auto-switches to landscape for 7+ columns with proportional widths
- Invoice PDFs use `invoice.amount` as total (not sum of line items), handle void status separately
- PO PDFs find separator rows dynamically (not hardcoded offsets), sanitize filenames with `re.sub`

### Exports (CSV/Excel/PDF)
- Money values: always format with 2 decimals (`f"{val:.2f}"`), never `str(decimal)` which drops trailing zeros
- Dates: use readable format (`format_date` or `strftime`), never raw `.isoformat()` with timezone offsets
- Excel: `xlsx_response` converts numeric strings to actual numbers so formulas/sorting work

### Authorization
- Roles: owner, admin, bookkeeper, demo
- `@admin_required` = owner + admin
- `@staff_required` = blocks demo users only
- Demo users: POST/PUT/DELETE blocked via `before_request` middleware, exports blocked
- Purchases: add/edit require `@staff_required`, delete requires `@admin_required`

### Frontend
- Dark theme with CSS custom properties (`--bg-app`, `--bg-panel`, `--text-muted`, etc.)
- Inputs should always use `theme-input` class (defined in app.css). Never hardcode `bg-gray-700 border-gray-600` — use theme classes (`bg-panel`, `border-app`, `text-muted`).
- Currency inputs must have `inputmode="decimal"`, phone inputs must have `inputmode="tel"`
- HTMX for partial updates; `HX-Request` header skips nav badge queries
- All destructive actions need `confirm()` dialogs
- Payment submit buttons must disable on click to prevent double-submission (HTMX: `hx-disabled-elt`, forms: Alpine `@submit="submitting = true"` + `:disabled="submitting"`)

### Database
- Composite indexes on hot query paths (invoices date, payments date, route_stops)
- `Invoice.status`: unpaid / paid / void — void invoices excluded from all reports
- Aging buckets use oldest unpaid invoice date, not last payment date

## Running Locally
```bash
FLASK_ENV=development FLASK_DEBUG=1 flask run --port 5000
```
Database auto-creates on first request via `init_db.py`. Default admin: `admin` / password from `ADMIN_PASSWORD` env var or auto-generated (check logs).

### Alembic Migrations
Local SQLite may be ahead of Alembic's version tracking because `init_db.py` auto-creates columns via `db.create_all()`. If `flask db upgrade` fails with "duplicate column", stamp to the last known version first:
```bash
flask db stamp b2c3d4e5f6a7   # or whatever the last applied revision is
flask db upgrade
```
Production (Railway PostgreSQL) tracks Alembic properly — Nixpacks start command runs `flask db upgrade` before gunicorn on every deploy. If a migration file is missing but its version is stamped in the DB, the app will fail to start.

### Smoke Test
After changes, verify all pages return 200:
```bash
# Login, then curl all major endpoints
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/health
```

## Before Pushing
1. Run the app locally, verify no import errors
2. Test the page you changed in browser — **especially templates** (Jinja2 syntax errors only surface at render time)
3. If you added/removed a migration file, verify the Alembic version chain is intact
4. Ask the user before pushing — the app is live
