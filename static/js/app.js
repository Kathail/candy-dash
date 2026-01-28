// static/js/app.js
// Candy Dash – Shared frontend utilities (HTMX + Alpine-friendly)
//
// Goals of this refactor:
// - Keep app.js “thin”: shared helpers + global HTMX hooks.
// - Avoid owning business state (no appState).
// - Keep backwards compatibility for legacy calls (openAreaOptimizer / setSelectedDate),
//   but make them optional + safer.

(() => {
  "use strict";

  // ---------------------------------------------------------------------------
  // Namespace
  // ---------------------------------------------------------------------------
  const CandyDash = (window.CandyDash = window.CandyDash || {});

  // ---------------------------------------------------------------------------
  // Tiny DOM helpers
  // ---------------------------------------------------------------------------
  const qs = (sel, root = document) => root.querySelector(sel);
  const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ---------------------------------------------------------------------------
  // Shared utilities
  // ---------------------------------------------------------------------------
  function formatCurrency(cents) {
    const n = Number(cents);
    const safe = Number.isFinite(n) ? n : 0;
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(safe / 100);
  }

  function escapeHTML(input = "") {
    // Ensure string, handle null/undefined
    const str = String(input ?? "");
    return str.replace(/[&<>"']/g, (m) => {
      switch (m) {
        case "&":
          return "&amp;";
        case "<":
          return "&lt;";
        case ">":
          return "&gt;";
        case '"':
          return "&quot;";
        case "'":
          return "&#39;";
        default:
          return m;
      }
    });
  }

  // Expose helpers (backwards compatible)
  window.formatCurrency = formatCurrency;
  window.escapeHTML = escapeHTML;
  CandyDash.formatCurrency = formatCurrency;
  CandyDash.escapeHTML = escapeHTML;

  // ---------------------------------------------------------------------------
  // HTMX integration helpers
  // ---------------------------------------------------------------------------
  function htmxProcess(el) {
    if (!el) return;
    if (window.htmx && typeof window.htmx.process === "function") {
      window.htmx.process(el);
    }
  }

  function htmxAjax(method, url, { values, target, swap } = {}) {
    if (!window.htmx || typeof window.htmx.ajax !== "function") return;
    window.htmx.ajax(method, url, {
      values,
      target,
      swap,
    });
  }

  CandyDash.htmxProcess = htmxProcess;
  CandyDash.htmxAjax = htmxAjax;

  // ---------------------------------------------------------------------------
  // Global confirmation behavior
  // - Supports:
  //   1) .route-complete-btn (legacy)
  //   2) Any element with data-confirm="Message..."
  // ---------------------------------------------------------------------------
  function installGlobalConfirmations() {
    if (!window.htmx || typeof window.htmx.on !== "function") return;

    window.htmx.on("htmx:beforeRequest", (e) => {
      const elt = e.detail?.elt;
      if (!elt) return;

      // Generic: data-confirm
      const msg = elt.getAttribute?.("data-confirm");
      if (msg) {
        if (!window.confirm(msg)) e.preventDefault();
        return;
      }

      // Legacy: route complete button
      if (elt.classList?.contains("route-complete-btn")) {
        if (!window.confirm("Mark this stop as completed?")) e.preventDefault();
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Legacy: Selected date (deprecated)
  // - Old code used window.setSelectedDate() and appState.selectedDate.
  // - We keep a tiny store for backwards compatibility, but DO NOT rely on it.
  //   Prefer passing selectedDate explicitly to functions.
  // ---------------------------------------------------------------------------
  const legacyStore = {
    selectedDate: null,
  };

  window.setSelectedDate = (dateStr) => {
    // Deprecated: keep only for old templates
    legacyStore.selectedDate = dateStr ? String(dateStr) : null;
  };

  CandyDash.getSelectedDate = () => legacyStore.selectedDate;

  // ---------------------------------------------------------------------------
  // Legacy: Area Optimizer modal (kept for compatibility)
  //
  // Recommended future direction:
  // - Move this UI into the calendar template as an Alpine component.
  // - Let Alpine render the groups, and use htmx.ajax for actions.
  //
  // For now:
  // - Still fetches /calendar/customers_by_area by default
  // - Renders cards
  // - Calls htmx.process(container) so hx-* in injected HTML works reliably
  // - Does NOT rely on global appState; uses selectedDate passed in or legacyStore
  // ---------------------------------------------------------------------------
  async function openAreaOptimizer(options = {}) {
    const {
      modalId = "area-optimizer-modal",
      endpoint = "/calendar/customers_by_area",
      selectedDate = legacyStore.selectedDate,
    } = options;

    const modal = document.getElementById(modalId);
    if (!modal) {
      console.warn(`Area optimizer modal not found (#${modalId})`);
      return;
    }

    // Support <dialog> modal OR a normal container (Alpine x-show etc.)
    if (typeof modal.showModal === "function") {
      modal.showModal();
    } else {
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
    }

    const container =
      qs(".flex-1", modal) ||
      qs(".overflow-y-auto", modal) ||
      qs("[data-area-optimizer-body]", modal) ||
      modal;

    if (!container) return;

    container.innerHTML = `
      <div class="text-center py-12 text-gray-500">
        <svg class="animate-spin h-8 w-8 mx-auto mb-4 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        Loading areas…
      </div>
    `;

    try {
      const res = await fetch(endpoint, {
        headers: { Accept: "application/json" },
      });
      if (!res.ok) throw new Error(`Failed to load (${res.status})`);

      const groups = await res.json();
      const entries = Object.entries(groups || {});

      if (!entries.length) {
        container.innerHTML = `<div class="text-center py-12 text-gray-500">No priority customers found.</div>`;
        return;
      }

      const addLabel = selectedDate ? "selected day" : "Today";

      let html = "";
      for (const [area, customers] of entries) {
        const list = Array.isArray(customers) ? customers : [];
        html += `
          <div class="mb-8">
            <div class="flex items-center justify-between mb-4">
              <h4 class="text-xl font-semibold">
                ${escapeHTML(area)}
                <span class="ml-2 text-sm text-gray-500">(${list.length})</span>
              </h4>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              ${list
                .map((c) => {
                  const name = escapeHTML(c?.name || "Unnamed");
                  const address = escapeHTML(c?.address || "No address");
                  const id = Number(c?.id);

                  const tags = [
                    c?.balance_cents > 0
                      ? `<span class="text-xs bg-red-500/30 text-red-400 px-2.5 py-1 rounded-full">Owes ${formatCurrency(
                          c.balance_cents,
                        )}</span>`
                      : "",
                    c?.days_since > 14
                      ? `<span class="text-xs bg-amber-500/30 text-amber-400 px-2.5 py-1 rounded-full">${escapeHTML(
                          c.days_since,
                        )}+ days</span>`
                      : "",
                  ]
                    .filter(Boolean)
                    .join("");

                  // Keep hx-post for compatibility with your backend endpoint.
                  // If you later want to pass selectedDate, change hx-vals accordingly and update backend.
                  return `
                    <div class="bg-gray-800 rounded-xl p-5 border border-gray-700 hover:border-blue-500 transition">
                      <div class="font-medium text-lg mb-2">${name}</div>
                      <div class="text-sm text-gray-400 mb-3">${address}</div>
                      <div class="flex flex-wrap gap-2 mb-4">${tags || ""}</div>

                      <button
                        hx-post="/quick_add_from_area"
                        hx-vals='{"customer_id": ${Number.isFinite(id) ? id : -1}}'
                        hx-swap="none"
                        class="w-full bg-green-600 hover:bg-green-700 text-white py-2.5 rounded-lg font-medium transition"
                      >
                        + Add to ${addLabel}
                      </button>
                    </div>
                  `;
                })
                .join("")}
            </div>
          </div>
        `;
      }

      container.innerHTML = html;

      // Critical: make sure HTMX sees any hx-* we injected
      htmxProcess(container);
    } catch (err) {
      console.error(err);
      container.innerHTML = `<div class="text-center py-12 text-red-400">Failed to load customers by area.</div>`;
    }
  }

  window.openAreaOptimizer = openAreaOptimizer;
  CandyDash.openAreaOptimizer = openAreaOptimizer;

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  function boot() {
    installGlobalConfirmations();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
