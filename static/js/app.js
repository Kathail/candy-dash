// ==========================================================================
// Candy Dash — App JS
// All Alpine components, HTMX config, and global utilities.
// ==========================================================================

(() => {
  "use strict";

  // ── Global namespace ──────────────────────────────────────────────────
  window.CandyDash = window.CandyDash || {};

  // ── Helpers ───────────────────────────────────────────────────────────
  function escapeHtml(str) {
    var d = document.createElement("div");
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
  }

  function csrfToken() {
    var el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute("content") : "";
  }

  CandyDash.formatCurrency = function (amount) {
    return "$" + parseFloat(amount || 0).toFixed(2);
  };

  // ── Alpine components ─────────────────────────────────────────────────
  document.addEventListener("alpine:init", function () {

    // Global search (used in header + mobile bar)
    Alpine.data("globalSearch", function () {
      return {
        query: "",
        results: [],
        open: false,
        loading: false,
        async search() {
          if (this.query.length < 1) { this.results = []; this.open = false; return; }
          this.loading = true;
          try {
            var res = await fetch("/api/customers/search?q=" + encodeURIComponent(this.query));
            this.results = await res.json();
            this.open = true;
          } catch (e) { this.results = []; }
          this.loading = false;
        }
      };
    });

    // Toast manager
    Alpine.data("toastManager", function () {
      return {
        toasts: [],
        nextId: 0,
        init() {
          // Read flash messages injected by Jinja
          var el = document.getElementById("flash-messages");
          if (el) {
            try {
              var msgs = JSON.parse(el.textContent);
              for (var i = 0; i < msgs.length; i++) {
                this.add(msgs[i][1], msgs[i][0]);
              }
            } catch (e) { /* ignore parse errors */ }
          }
          // Listen for dynamic toasts
          document.addEventListener("show-toast", function (e) {
            this.add(e.detail.message, e.detail.category || "info");
          }.bind(this));
        },
        add(msg, cat) {
          var id = this.nextId++;
          this.toasts.push({ id: id, msg: msg, cat: cat, show: true });
          setTimeout(function () { this.dismiss(id); }.bind(this), 5000);
        },
        dismiss(id) {
          var t = this.toasts.find(function (t) { return t.id === id; });
          if (t) t.show = false;
          setTimeout(function () {
            this.toasts = this.toasts.filter(function (t) { return t.id !== id; });
          }.bind(this), 300);
        }
      };
    });

    // Payment modal
    Alpine.data("paymentModal", function () {
      return {
        isOpen: false,
        selectedCustomer: null,
        customerQuery: "",
        custResults: [],
        custDropdown: false,
        amount: "",
        notes: "",
        submitting: false,

        openModal(detail) {
          this.isOpen = true;
          if (detail && detail.customerId && detail.customerName) {
            this.selectedCustomer = { id: detail.customerId, name: detail.customerName };
            this.customerQuery = detail.customerName;
          }
        },
        close() {
          this.isOpen = false;
          this.selectedCustomer = null;
          this.customerQuery = "";
          this.custResults = [];
          this.amount = "";
          this.notes = "";
        },
        async searchCustomers() {
          if (this.customerQuery.length < 1) { this.custResults = []; this.custDropdown = false; return; }
          try {
            var res = await fetch("/api/customers/search?q=" + encodeURIComponent(this.customerQuery));
            this.custResults = await res.json();
            this.custDropdown = true;
          } catch (e) { this.custResults = []; }
        },
        selectCustomer(c) {
          this.selectedCustomer = c;
          this.customerQuery = c.name;
          this.custDropdown = false;
        },
        async submit() {
          if (!this.selectedCustomer || !this.amount) return;
          this.submitting = true;
          try {
            var res = await fetch("/customers/" + this.selectedCustomer.id + "/payment", {
              method: "POST",
              headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken() },
              body: new URLSearchParams({ amount: this.amount, notes: this.notes })
            });
            if (res.ok) {
              document.dispatchEvent(new CustomEvent("show-toast", {
                detail: { message: "Payment recorded successfully.", category: "success" }
              }));
              this.close();
              if (typeof htmx !== "undefined") htmx.trigger(document.body, "paymentRecorded");
            } else {
              document.dispatchEvent(new CustomEvent("show-toast", {
                detail: { message: "Failed to record payment.", category: "error" }
              }));
            }
          } catch (e) {
            document.dispatchEvent(new CustomEvent("show-toast", {
              detail: { message: "Network error. Please try again.", category: "error" }
            }));
          }
          this.submitting = false;
        }
      };
    });

    // Customer table (reusable for customers + balances pages)
    Alpine.data("customerTable", function () {
      return {
        mode: "customers",
        rows: [],
        searchTerm: "",
        sortKey: "name",
        sortDir: "asc",

        init() {
          this.rows = Array.isArray(window.CUSTOMERS) ? window.CUSTOMERS : [];
          if (this.mode === "balances") {
            this.sortKey = "balance";
            this.sortDir = "desc";
          }
        },

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
          return this.sortDir === "asc" ? "\u25B2" : "\u25BC";
        },

        get filteredRows() {
          var t = this.searchTerm.toLowerCase();
          var rows = !t ? this.rows : this.rows.filter(function (c) {
            return [c.name, c.phone, c.email, c.address].filter(Boolean).some(function (v) {
              return v.toLowerCase().includes(t);
            });
          });
          if (this.mode === "balances") {
            rows = rows.filter(function (c) { return Number(c.balance) > 0; });
          }
          var sk = this.sortKey;
          var sd = this.sortDir;
          return rows.slice().sort(function (a, b) {
            var A = a[sk] != null ? a[sk] : "";
            var B = b[sk] != null ? b[sk] : "";
            if (typeof A === "string") A = A.toLowerCase();
            if (typeof B === "string") B = B.toLowerCase();
            if (A < B) return sd === "asc" ? -1 : 1;
            if (A > B) return sd === "asc" ? 1 : -1;
            return 0;
          });
        },

        balanceClass(balance) {
          var n = Number(balance);
          if (!n || n <= 0) return "text-faint";
          if (n < 20) return "text-warn";
          if (n < 100) return "text-orange-400";
          return "theme-text-danger";
        }
      };
    });
  });

  // ── HTMX config ───────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", function () {

    // CSRF header on every HTMX request
    document.body.addEventListener("htmx:configRequest", function (e) {
      e.detail.headers["X-CSRFToken"] = csrfToken();
    });

    // Error handling for HTMX swaps
    document.body.addEventListener("htmx:beforeSwap", function (e) {
      if (e.detail.xhr.status === 422 || e.detail.xhr.status === 400) {
        e.detail.shouldSwap = true;
        e.detail.isError = false;
      } else if (e.detail.xhr.status >= 500) {
        document.dispatchEvent(new CustomEvent("show-toast", {
          detail: { message: "A server error occurred. Please try again.", category: "error" }
        }));
        e.detail.shouldSwap = false;
      }
    });

    // Confirm dialogs for [data-confirm] elements
    document.body.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-confirm]");
      if (!btn) return;
      if (!confirm(btn.getAttribute("data-confirm") || "Are you sure?")) {
        e.preventDefault();
        e.stopPropagation();
      }
    });

    // Escape key closes modals
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        document.querySelectorAll('.modal:not(.hidden), [role="dialog"]:not(.hidden)').forEach(function (m) {
          m.classList.add("hidden");
        });
      }
    });

    // Offline banner
    var banner = document.getElementById("offline-banner");
    if (banner) {
      function updateBanner() {
        banner.classList.toggle("visible", !navigator.onLine);
      }
      window.addEventListener("online", updateBanner);
      window.addEventListener("offline", updateBanner);
      updateBanner();
    }

    // Service worker
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/static/sw.js")
        .then(function (reg) { console.log("SW registered:", reg.scope); })
        .catch(function (err) { console.warn("SW failed:", err); });
    }
  });

})();
