// static/js/app.js
(() => {
  "use strict";

  // -----------------------------
  // Global namespace
  // -----------------------------
  window.CandyDash = window.CandyDash || {};

  // -----------------------------
  // Alpine components
  // -----------------------------
  document.addEventListener("alpine:init", () => {
    Alpine.data("customerTable", () => ({
      // injected
      mode: "customers",
      rows: [],

      // ui state
      searchTerm: "",
      sortKey: "name",
      sortDir: "asc",

      // lifecycle
      init() {
        this.rows = Array.isArray(window.CUSTOMERS) ? window.CUSTOMERS : [];

        if (this.mode === "balances") {
          this.sortKey = "balance";
          this.sortDir = "desc";
        }
      },

      // actions
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

      // computed
      get filteredRows() {
        const t = this.searchTerm.toLowerCase();

        let rows = !t
          ? this.rows
          : this.rows.filter((c) =>
              [c.name, c.phone, c.email, c.address]
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

      // helpers
      balanceClass(balance) {
        const n = Number(balance);
        if (!n || n <= 0) return "text-gray-400";
        if (n < 20) return "text-yellow-300";
        if (n < 100) return "text-orange-400";
        return "theme-text-danger";
      },
    }));
  });
})();
