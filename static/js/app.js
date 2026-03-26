/* ============================================
   Candy Route Planner - Client-Side JavaScript
   ============================================ */

(function () {
  "use strict";

  /* ------------------------------------------
     Toast Notification System
     ------------------------------------------ */
  const Toast = {
    container: null,

    init() {
      this.container = document.getElementById("toast-container");
      if (!this.container) {
        this.container = document.createElement("div");
        this.container.id = "toast-container";
        this.container.className = "toast-container";
        this.container.setAttribute("aria-live", "polite");
        this.container.setAttribute("aria-atomic", "true");
        document.body.appendChild(this.container);
      }
    },

    /**
     * Show a toast notification.
     * @param {string} message - Text to display.
     * @param {string} [type='info'] - success | error | warning | info
     * @param {number} [duration=3000] - Auto-dismiss in ms. 0 = manual.
     */
    show(message, type = "info", duration = 3000) {
      if (!this.container) this.init();

      const icons = {
        success: "\u2713",
        error: "\u2717",
        warning: "\u26A0",
        info: "\u2139",
      };

      const el = document.createElement("div");
      el.className = `toast toast-${type}`;
      el.setAttribute("role", "alert");
      el.innerHTML = `<span aria-hidden="true">${icons[type] || icons.info}</span><span>${escapeHtml(message)}</span>`;

      this.container.appendChild(el);

      if (duration > 0) {
        setTimeout(() => this.dismiss(el), duration);
      }

      return el;
    },

    dismiss(el) {
      if (!el || !el.parentNode) return;
      el.classList.add("toast-dismiss");
      el.addEventListener("animationend", () => el.remove(), { once: true });
    },
  };

  /* ------------------------------------------
     HTMX Event Hooks
     ------------------------------------------ */
  function initHtmxHooks() {
    const overlay = document.getElementById("loading-overlay");

    document.body.addEventListener("htmx:beforeRequest", function () {
      if (overlay) overlay.classList.add("active");
    });

    document.body.addEventListener("htmx:afterRequest", function () {
      if (overlay) overlay.classList.remove("active");
    });

    document.body.addEventListener("htmx:responseError", function (evt) {
      if (overlay) overlay.classList.remove("active");
      const status = evt.detail.xhr ? evt.detail.xhr.status : 0;
      let msg = "Something went wrong. Please try again.";
      if (status === 0) {
        msg = "Network error. You may be offline.";
      } else if (status === 403) {
        msg = "You do not have permission for that action.";
      } else if (status === 404) {
        msg = "The requested resource was not found.";
      } else if (status >= 500) {
        msg = "Server error. Please try again later.";
      }
      Toast.show(msg, "error", 5000);
    });

    // Handle flash messages sent via HX-Trigger header
    document.body.addEventListener("showToast", function (evt) {
      const detail = evt.detail || {};
      Toast.show(
        detail.message || "Done",
        detail.type || "info",
        detail.duration || 3000
      );
    });
  }

  /* ------------------------------------------
     Payment Modal Helpers
     ------------------------------------------ */
  function openPaymentModal(customerId, customerName, currentBalance) {
    const modal = document.getElementById("payment-modal");
    if (!modal) return;

    const nameEl = modal.querySelector("[data-customer-name]");
    const balanceEl = modal.querySelector("[data-current-balance]");
    const idInput = modal.querySelector("[name='customer_id']");
    const amountInput = modal.querySelector("[name='amount']");

    if (nameEl) nameEl.textContent = customerName;
    if (balanceEl)
      balanceEl.textContent = formatCurrency(parseFloat(currentBalance) || 0);
    if (idInput) idInput.value = customerId;
    if (amountInput) {
      amountInput.value = "";
      amountInput.focus();
    }

    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }

  function closePaymentModal() {
    const modal = document.getElementById("payment-modal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }

  /* ------------------------------------------
     Confirm Dialogs for Dangerous Actions
     ------------------------------------------ */
  function initConfirmDialogs() {
    document.body.addEventListener("click", function (evt) {
      const btn = evt.target.closest("[data-confirm]");
      if (!btn) return;

      const message =
        btn.getAttribute("data-confirm") ||
        "Are you sure? This action cannot be undone.";
      if (!confirm(message)) {
        evt.preventDefault();
        evt.stopPropagation();
      }
    });
  }

  /* ------------------------------------------
     Currency Input Formatting
     ------------------------------------------ */
  function initCurrencyInputs() {
    document.body.addEventListener("input", function (evt) {
      const el = evt.target;
      if (!el.matches("[data-currency]")) return;

      // Allow digits, one decimal point, and up to 2 decimal places
      let val = el.value.replace(/[^0-9.]/g, "");
      const parts = val.split(".");
      if (parts.length > 2) {
        val = parts[0] + "." + parts.slice(1).join("");
      }
      if (parts[1] && parts[1].length > 2) {
        val = parts[0] + "." + parts[1].slice(0, 2);
      }
      el.value = val;
    });
  }

  /* ------------------------------------------
     Click-to-Call on Mobile
     ------------------------------------------ */
  function initClickToCall() {
    document.body.addEventListener("click", function (evt) {
      const link = evt.target.closest("[data-phone]");
      if (!link) return;

      const phone = link.getAttribute("data-phone").replace(/\s+/g, "");
      if (phone && "ontouchstart" in window) {
        window.location.href = "tel:" + phone;
      }
    });
  }

  /* ------------------------------------------
     Keyboard Shortcuts
     ------------------------------------------ */
  function initKeyboardShortcuts() {
    document.addEventListener("keydown", function (evt) {
      if (evt.key === "Escape") {
        // Close any visible modal
        const modals = document.querySelectorAll(
          '.modal:not(.hidden), [role="dialog"]:not(.hidden)'
        );
        modals.forEach(function (modal) {
          modal.classList.add("hidden");
          modal.setAttribute("aria-hidden", "true");
        });
      }
    });
  }

  /* ------------------------------------------
     Utilities
     ------------------------------------------ */
  function escapeHtml(str) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function formatCurrency(amount) {
    return "R " + parseFloat(amount).toFixed(2);
  }

  /* ------------------------------------------
     Active Nav Link Highlighting
     ------------------------------------------ */
  function highlightActiveNav() {
    const path = window.location.pathname;
    document.querySelectorAll(".nav-link").forEach(function (link) {
      const href = link.getAttribute("href");
      if (!href) return;
      if (path === href || (href !== "/" && path.startsWith(href))) {
        link.classList.add("active");
      } else {
        link.classList.remove("active");
      }
    });
  }

  /* ------------------------------------------
     Offline Banner
     ------------------------------------------ */
  function initOfflineBanner() {
    const banner = document.getElementById("offline-banner");
    if (!banner) return;

    function update() {
      if (navigator.onLine) {
        banner.classList.remove("visible");
      } else {
        banner.classList.add("visible");
      }
    }

    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    update();
  }

  /* ------------------------------------------
     Initialize Everything
     ------------------------------------------ */
  document.addEventListener("DOMContentLoaded", function () {
    Toast.init();
    initHtmxHooks();
    initConfirmDialogs();
    initCurrencyInputs();
    initClickToCall();
    initKeyboardShortcuts();
    highlightActiveNav();
    initOfflineBanner();
  });

  // Expose public API
  window.CandyApp = {
    toast: Toast,
    openPaymentModal: openPaymentModal,
    closePaymentModal: closePaymentModal,
    formatCurrency: formatCurrency,
  };
})();
