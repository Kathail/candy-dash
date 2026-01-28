// static/js/app.js
// Candy Dash – Shared frontend utilities (HTMX + Alpine)
// Single source of truth for shared UI behavior

(() => {
  "use strict";

  // ---------------------------------------------------------------------------
  // Namespace
  // ---------------------------------------------------------------------------
  const CandyDash = (window.CandyDash = window.CandyDash || {});

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------
  function escapeHTML(input = "") {
    return String(input).replace(/[&<>"']/g, (m) => {
      return (
        {
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        }[m] || m
      );
    });
  }

  function formatCurrency(cents) {
    const n = Number(cents);
    const safe = Number.isFinite(n) ? n : 0;
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
    }).format(safe / 100);
  }

  CandyDash.escapeHTML = escapeHTML;
  CandyDash.formatCurrency = formatCurrency;

  // ---------------------------------------------------------------------------
  // HTMX global confirmation handling
  // ---------------------------------------------------------------------------
  function installHTMXConfirm() {
    if (!window.htmx) return;

    htmx.on("htmx:beforeRequest", (e) => {
      const el = e.detail?.elt;
      if (!el) return;

      const msg = el.getAttribute?.("data-confirm");
      if (msg && !window.confirm(msg)) {
        e.preventDefault();
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Alpine shared components
  // ---------------------------------------------------------------------------
  document.addEventListener("alpine:init", () => {
    Alpine.data("customerTable", ({ mode }) => ({
      // ---------------------------------------------------------------------
      // Exposed state
      // ---------------------------------------------------------------------
      mode, // 'customers' | 'balances'

      rows: Array.isArray(window.CUSTOMERS) ? window.CUSTOMERS : [],

      searchTerm: "",
      sortKey: mode === "balances" ? "balance" : "name",
      sortDir: mode === "balances" ? "desc" : "asc",

      // ---------------------------------------------------------------------
      // Actions
      // ---------------------------------------------------------------------
      sortBy(key) {
        if (this.sortKey === key) {
          this.sortDir = this.sortDir === "asc" ? "desc" : "asc";
        } else {
          this.sortKey = key;
          this.sortDir = "asc";
        }
      },

      sortIndicator(key) {
        if (this.sortKey !== key) return "";
        return this.sortDir === "asc" ? "▲" : "▼";
      },

      // ---------------------------------------------------------------------
      // Computed
      // ---------------------------------------------------------------------
      get filteredRows() {
        const t = this.searchTerm.toLowerCase();

        let rows = !t
          ? this.rows
          : this.rows.filter((c) =>
              [c.name, c.phone, c.email, c.address, c.notes]
                .filter(Boolean)
                .some((v) => v.toLowerCase().includes(t)),
            );

        if (this.mode === "balances") {
          rows = rows.filter((c) => Number(c.balance) > 0);
        }

        return [...rows].sort((a, b) => {
          let A = a[this.sortKey] ?? "";
          let B = b[this.sortKey] ?? "";

          if (typeof A === "string") A = A.toLowerCase();
          if (typeof B === "string") B = B.toLowerCase();

          if (A < B) return this.sortDir === "asc" ? -1 : 1;
          if (A > B) return this.sortDir === "asc" ? 1 : -1;
          return 0;
        });
      },

      // ---------------------------------------------------------------------
      // Helpers
      // ---------------------------------------------------------------------
      balanceClass(balance) {
        const n = Number(balance);
        if (!Number.isFinite(n) || n <= 0) return "text-gray-400";
        if (n < 20) return "text-yellow-300";
        if (n < 100) return "text-orange-400";
        return "theme-text-danger";
      },
    }));
  });

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  function boot() {
    installHTMXConfirm();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
