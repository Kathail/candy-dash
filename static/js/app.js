// ==========================================================================
// Candy Dash — App JS
// Alpine components, HTMX config, and global utilities.
// ==========================================================================

(() => {
  "use strict";

  // ── Helpers ───────────────────────────────────────────────────────────

  function csrfToken() {
    const el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute("content") : "";
  }

  // Expose CSRF helper for offline.js
  window.CandyDash = { csrfToken };

  // ── Alpine components ─────────────────────────────────────────────────
  document.addEventListener("alpine:init", () => {

    // Global search (used in header + mobile bar)
    Alpine.data("globalSearch", () => ({
      query: "",
      results: [],
      open: false,
      loading: false,
      _controller: null,

      async search() {
        if (this.query.length < 1) {
          this.results = [];
          this.open = false;
          return;
        }

        // Abort any in-flight request
        if (this._controller) this._controller.abort();
        this._controller = new AbortController();

        this.loading = true;
        try {
          const res = await fetch(
            "/api/customers/search?q=" + encodeURIComponent(this.query),
            { signal: this._controller.signal }
          );
          if (!res.ok) { this.results = []; this.loading = false; return; }
          this.results = await res.json();
          this.open = true;
        } catch (e) {
          if (e.name !== "AbortError") this.results = [];
        }
        this.loading = false;
      },
    }));

    // Toast manager
    Alpine.data("toastManager", () => {
      return {
        toasts: [],
        nextId: 0,

        init() {
          // Read flash messages injected by Jinja (consume once)
          const el = document.getElementById("flash-messages");
          if (el) {
            try {
              const msgs = JSON.parse(el.textContent);
              for (const [cat, msg] of msgs) {
                this.add(msg, cat);
              }
            } catch (_) { /* ignore parse errors */ }
            el.remove();
          }
          // Listen for dynamic toasts (single global listener via window flag)
          if (!window.__toastBound) {
            window.__toastBound = true;
            document.addEventListener("show-toast", (e) => {
              this.add(e.detail.message, e.detail.category || "info");
            });
          }
        },

        add(msg, cat) {
          // Deduplicate: skip if same message already showing
          if (this.toasts.some((t) => t.msg === msg && t.show)) return;
          const id = this.nextId++;
          this.toasts.push({ id, msg, cat, show: true });
          setTimeout(() => this.dismiss(id), 5000);
        },

        dismiss(id) {
          const t = this.toasts.find((t) => t.id === id);
          if (t) t.show = false;
          setTimeout(() => {
            this.toasts = this.toasts.filter((t) => t.id !== id);
          }, 300);
        },
      };
    });

    // Payment modal
    Alpine.data("paymentModal", () => ({
      isOpen: false,
      selectedCustomer: null,
      customerQuery: "",
      custResults: [],
      custDropdown: false,
      amountSold: "",
      amountPaid: "",
      notes: "",
      submitting: false,
      _controller: null,

      get newBalance() {
        const bal = Number(this.selectedCustomer?.balance || 0);
        const sold = Number(this.amountSold) || 0;
        const paid = Number(this.amountPaid) || 0;
        return bal + sold - paid;
      },

      openModal(detail) {
        this.isOpen = true;
        if (detail && detail.customerId && detail.customerName) {
          this.selectedCustomer = { id: detail.customerId, name: detail.customerName, balance: detail.customerBalance || 0 };
          this.customerQuery = detail.customerName;
        }
      },

      close() {
        this.isOpen = false;
        this.selectedCustomer = null;
        this.customerQuery = "";
        this.custResults = [];
        this.amountSold = "";
        this.amountPaid = "";
        this.notes = "";
      },

      async searchCustomers() {
        if (this.customerQuery.length < 1) {
          this.custResults = [];
          this.custDropdown = false;
          return;
        }

        if (this._controller) this._controller.abort();
        this._controller = new AbortController();

        try {
          const res = await fetch(
            "/api/customers/search?q=" + encodeURIComponent(this.customerQuery),
            { signal: this._controller.signal }
          );
          if (!res.ok) { this.custResults = []; return; }
          this.custResults = await res.json();
          this.custDropdown = true;
        } catch (e) {
          if (e.name !== "AbortError") this.custResults = [];
        }
      },

      selectCustomer(c) {
        this.selectedCustomer = c;
        this.customerQuery = c.name;
        this.custDropdown = false;
      },

      async submit() {
        if (!this.selectedCustomer || (!this.amountSold && !this.amountPaid)) return;
        this.submitting = true;
        try {
          const res = await fetch("/customers/" + this.selectedCustomer.id + "/payment", {
            method: "POST",
            headers: {
              "Content-Type": "application/x-www-form-urlencoded",
              "X-CSRFToken": csrfToken(),
              "X-Requested-With": "fetch",
            },
            body: new URLSearchParams({
              amount_sold: this.amountSold || "0",
              amount_paid: this.amountPaid || "0",
              notes: this.notes,
            }),
          });
          if (!res.ok) {
            let msg = "Failed to record transaction.";
            try { const d = await res.json(); msg = d.error || msg; } catch (_) {}
            document.dispatchEvent(new CustomEvent("show-toast", { detail: { message: msg, category: "error" } }));
            this.submitting = false;
            return;
          }
          const data = await res.json();
          if (data.ok) {
            document.dispatchEvent(new CustomEvent("show-toast", {
              detail: { message: "Transaction recorded. Invoice #" + data.receipt_number, category: "success" },
            }));
            this.close();
            window.location.reload();
          } else {
            document.dispatchEvent(new CustomEvent("show-toast", {
              detail: { message: data.error || "Failed to record transaction.", category: "error" },
            }));
          }
        } catch (_) {
          document.dispatchEvent(new CustomEvent("show-toast", {
            detail: { message: "Network error. Please try again.", category: "error" },
          }));
        }
        this.submitting = false;
      },
    }));
  });

  // ── HTMX config ───────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {

    // CSRF header on every HTMX request
    document.body.addEventListener("htmx:configRequest", (e) => {
      e.detail.headers["X-CSRFToken"] = csrfToken();
    });

    // Error handling for HTMX swaps
    document.body.addEventListener("htmx:beforeSwap", (e) => {
      if (e.detail.xhr.status === 422 || e.detail.xhr.status === 400) {
        e.detail.shouldSwap = true;
        e.detail.isError = false;
      } else if (e.detail.xhr.status >= 500) {
        document.dispatchEvent(new CustomEvent("show-toast", {
          detail: { message: "A server error occurred. Please try again.", category: "error" },
        }));
        e.detail.shouldSwap = false;
      }
    });

    // Confirm dialogs for [data-confirm] elements
    document.body.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-confirm]");
      if (!btn) return;
      if (!confirm(btn.getAttribute("data-confirm") || "Are you sure?")) {
        e.preventDefault();
        e.stopPropagation();
      }
    });

    // Keyboard shortcuts
    document.addEventListener("keydown", (e) => {
      // Ignore when typing in inputs
      const tag = (e.target.tagName || "").toLowerCase();
      const isInput = tag === "input" || tag === "textarea" || tag === "select" || e.target.isContentEditable;

      // Escape always works (closes modals)
      if (e.key === "Escape") {
        document.querySelectorAll('.modal:not(.hidden), [role="dialog"]:not(.hidden)').forEach((m) => {
          m.classList.add("hidden");
        });
        return;
      }

      if (isInput) return;

      // "/" focuses global search
      if (e.key === "/") {
        e.preventDefault();
        const searchEl = document.querySelector("#desktop-search input[type=search], #mobile-search input[type=search]");
        if (searchEl) searchEl.focus();
      }

      // "?" shows keyboard shortcuts overlay
      if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        document.dispatchEvent(new CustomEvent("open-shortcuts"));
      }
    });

    // Offline banner
    const banner = document.getElementById("offline-banner");
    if (banner) {
      const updateBanner = () => banner.classList.toggle("visible", !navigator.onLine);
      window.addEventListener("online", updateBanner);
      window.addEventListener("offline", updateBanner);
      updateBanner();
    }

    // Service worker (served from root for full-app scope)
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js")
        .then((reg) => console.log("SW registered:", reg.scope))
        .catch((err) => console.warn("SW failed:", err));
    }
  });

})();
