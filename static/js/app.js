// static/js/app.js
// Candy Flask – Shared frontend utilities & behaviors
// Vanilla JS + Tailwind – no build step yet

document.addEventListener("DOMContentLoaded", () => {
  console.log("Candy Flask frontend loaded");

  // ── State ────────────────────────────────────────────────────────────────
  const appState = {
    selectedDate: null,
  };

  window.setSelectedDate = (dateStr) => {
    appState.selectedDate = dateStr;
  };

  // ── Utilities ────────────────────────────────────────────────────────────
  function formatCurrency(cents) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(cents / 100);
  }

  function escapeHTML(str = "") {
    return str.replace(/[&<>"']/g, (m) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[m]));
  }

  function debounce(fn, delay = 250) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), delay);
    };
  }

  function openModal(modalEl) {
    modalEl?.classList.remove("hidden");
  }

  function closeModal(modalEl) {
    modalEl?.classList.add("hidden");
  }

  // ── Modal Helpers ────────────────────────────────────────────────────────
  function setupModal(modalId, closeSelector = ".close-modal, [data-close]") {
    const modal = document.getElementById(modalId);
    if (!modal) return null;

    const closeBtn = modal.querySelector(closeSelector);
    if (closeBtn) {
      closeBtn.addEventListener("click", () => closeModal(modal));
    }

    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal(modal);
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.classList.contains("hidden")) {
        closeModal(modal);
      }
    });

    return modal;
  }

  // ── Area Optimizer Modal ─────────────────────────────────────────────────
  const areaModal = setupModal("area-optimizer-modal", ".close-area-modal, button[data-close]");

  window.openAreaOptimizer = async () => {
    if (!areaModal) {
      console.warn("Area optimizer modal not found");
      return;
    }

    openModal(areaModal);

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
              ${customers.map(c => `
                <div class="bg-gray-800 rounded-xl p-5 border border-gray-700 hover:border-blue-500 transition">
                  <div class="font-medium text-lg mb-2">${escapeHTML(c.name)}</div>
                  <div class="text-sm text-gray-400 mb-3">${escapeHTML(c.address || "No address")}</div>
                  <div class="flex flex-wrap gap-2 mb-4">
                    ${c.balance_cents > 0 ? `<span class="text-xs bg-red-500/30 text-red-400 px-2.5 py-1 rounded-full">Owes ${formatCurrency(c.balance_cents)}</span>` : ""}
                    ${c.days_since > 14 ? `<span class="text-xs bg-amber-500/30 text-amber-400 px-2.5 py-1 rounded-full">${c.days_since}+ days</span>` : ""}
                  </div>
                  <button onclick="quickAddFromArea(${c.id})" class="w-full bg-green-600 hover:bg-green-700 text-white py-2.5 rounded-lg font-medium transition">
                    + Add to ${appState.selectedDate ? "selected day" : "Today"}
                  </button>
                </div>
              `).join("")}
            </div>
          </div>`;
      });

      container.innerHTML = html;
    } catch (err) {
      console.error(err);
      container.innerHTML = `<div class="text-center py-12 text-red-400">Failed to load customers by area.</div>`;
    }
  };

  // ── Quick Add from Area ──────────────────────────────────────────────────
  window.quickAddFromArea = (customerId) => {
    const modal = document.getElementById("quickAddModal");
    if (!modal) {
      console.warn("Quick add modal not found");
      return;
    }

    openModal(modal);

    const form = modal.querySelector("form");
    if (!form) return;

    const customerSelect = form.querySelector('select[name="customer_id"]');
    if (customerSelect) customerSelect.value = customerId;

    const dateInput = form.querySelector('input[name="date"]');
    if (dateInput) {
      dateInput.value = appState.selectedDate || new Date().toISOString().split("T")[0];
    }

    const notes = form.querySelector('textarea[name="notes"]');
    if (notes) notes.value = "Added from Area Optimizer";
  };

  // ── Route Complete Confirmation ──────────────────────────────────────────
  document.querySelectorAll(".route-complete-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      if (!confirm("Mark this stop as completed?")) {
        e.preventDefault();
      }
    });
  });
