// static/js/app.js
// Candy Dash – Shared frontend utilities
// Used with HTMX + Alpine.js

document.addEventListener("DOMContentLoaded", () => {
  console.log("Candy Dash frontend loaded");

  // ── State ────────────────────────────────────────────────────────────────
  const appState = {
    selectedDate: null,
  };

  window.setSelectedDate = (dateStr) => {
    appState.selectedDate = dateStr;
  };

  // ── Utilities ────────────────────────────────────────────────────────────
  window.formatCurrency = (cents) => {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(cents / 100);
  };

  window.escapeHTML = (str = "") => {
    return str.replace(
      /[&<>"']/g,
      (m) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[m],
    );
  };

  // ── Area Optimizer Modal ─────────────────────────────────────────────────
  window.openAreaOptimizer = async () => {
    const areaModal = document.getElementById("area-optimizer-modal");
    if (!areaModal) {
      console.warn("Area optimizer modal not found");
      return;
    }

    areaModal.showModal(); // Assuming <dialog> or Alpine handles open

    const container = areaModal.querySelector(".flex-1, .overflow-y-auto");
    if (!container) return;

    container.innerHTML = `
      <div class="text-center py-12 text-gray-500">
        <svg class="animate-spin h-8 w-8 mx-auto mb-4 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        Loading areas…
      </div>`;

    try {
      const res = await fetch("/calendar/customers_by_area");
      if (!res.ok) throw new Error("Failed to load");

      const groups = await res.json();

      if (!Object.keys(groups).length) {
        container.innerHTML = `<div class="text-center py-12 text-gray-500">No priority customers found.</div>`;
        return;
      }

      let html = "";
      Object.entries(groups).forEach(([area, customers]) => {
        html += `
          <div class="mb-8">
            <div class="flex items-center justify-between mb-4">
              <h4 class="text-xl font-semibold">${escapeHTML(area)} <span class="ml-2 text-sm text-gray-500">(${customers.length})</span></h4>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              ${customers
                .map(
                  (c) => `
                <div class="bg-gray-800 rounded-xl p-5 border border-gray-700 hover:border-blue-500 transition">
                  <div class="font-medium text-lg mb-2">${escapeHTML(c.name)}</div>
                  <div class="text-sm text-gray-400 mb-3">${escapeHTML(c.address || "No address")}</div>
                  <div class="flex flex-wrap gap-2 mb-4">
                    ${c.balance_cents > 0 ? `<span class="text-xs bg-red-500/30 text-red-400 px-2.5 py-1 rounded-full">Owes ${formatCurrency(c.balance_cents)}</span>` : ""}
                    ${c.days_since > 14 ? `<span class="text-xs bg-amber-500/30 text-amber-400 px-2.5 py-1 rounded-full">${c.days_since}+ days</span>` : ""}
                  </div>
                  <button hx-post="/quick_add_from_area" hx-vals='{"customer_id": ${c.id}}' hx-swap="none" class="w-full bg-green-600 hover:bg-green-700 text-white py-2.5 rounded-lg font-medium transition">
                    + Add to ${appState.selectedDate ? "selected day" : "Today"}
                  </button>
                </div>
              `,
                )
                .join("")}
            </div>
          </div>`;
      });

      container.innerHTML = html;
    } catch (err) {
      console.error(err);
      container.innerHTML = `<div class="text-center py-12 text-red-400">Failed to load customers by area.</div>`;
    }
  };

  // ── Route Complete Confirmation ──────────────────────────────────────────
  htmx.on("htmx:beforeRequest", (e) => {
    if (e.detail.elt.classList.contains("route-complete-btn")) {
      if (!confirm("Mark this stop as completed?")) {
        e.preventDefault();
      }
    }
  });
});
