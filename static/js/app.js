// static/js/app.js
// Candy Dash – Shared frontend utilities (HTMX + Alpine)

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
      // state
      searchTerm: "",
      sortKey: mode === "balances" ? "balance" : "name",
      sortDir: mode === "balances" ? "desc" : "asc",

      // actions
      sortBy(key) {
        if (this.sortKey === key) {
          this.sortDir = this.sortDir === "asc" ? "desc" : "asc";
        } else {
          this.sortKey = key;
          this.sortDir = "asc";
        }
      },

      // computed
      get filteredRows() {
        const t = this.searchTerm.toLowerCase();

        let rows = !t
          ? customers
          : customers.filter((c) =>
              [c.name, c.phone, c.email, c.address, c.notes]
                .filter(Boolean)
                .some((v) => v.toLowerCase().includes(t)),
            );

        if (mode === "balances") {
          rows = rows.filter((c) => c.balance > 0);
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

      // helpers
      balanceClass(balance) {
        if (balance <= 0) return "text-gray-400";
        if (balance < 20) return "text-yellow-300";
        if (balance < 100) return "text-orange-400";
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
