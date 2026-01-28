// static/js/app.js
// Candy Flask – Frontend Behavior
// Minimal, no frameworks, only what's needed

document.addEventListener("DOMContentLoaded", () => {
  console.log("Candy Flask frontend loaded");

  // Format currency helper
  function formatCurrency(amount) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount / 100); // assuming cents → dollars
  }

  // Global reference to selected date from calendar (used in quick add)
  let selectedDate = null; // will be set by calendar when day is clicked

  // Export selectedDate setter so calendar.js can update it
  window.setSelectedDate = (dateStr) => {
    selectedDate = dateStr;
  };

  // Customers page search
  const customerTable = document.getElementById("customerTable");
  const searchInput = document.getElementById("searchInput");
  if (customerTable && searchInput) {
    searchInput.addEventListener("input", () => {
      const filter = searchInput.value.toLowerCase().trim();
      const rows = customerTable.tBodies[0].rows;
      Array.from(rows).forEach((row) => {
        const cells = row.cells;
        const searchableText = [
          cells[0]?.textContent || "", // name
          cells[1]?.textContent || "", // phone
          cells[2]?.textContent || "", // address
          cells[3]?.textContent || "", // notes
        ]
          .join(" ")
          .toLowerCase();
        row.style.display = searchableText.includes(filter) ? "" : "none";
      });
    });
  }

  // Edit modal (customers page)
  const editModal = document.getElementById("editModal");
  const closeModalBtn = document.querySelector(".close-modal");
  const editButtons = document.querySelectorAll(".edit-button");
  if (editModal && closeModalBtn && editButtons.length > 0) {
    editButtons.forEach((button) => {
      button.addEventListener("click", () => {
        document.getElementById("editId").value = button.dataset.id;
        document.getElementById("editName").value = button.dataset.name;
        document.getElementById("editPhone").value = button.dataset.phone || "";
        document.getElementById("editAddress").value =
          button.dataset.address || "";
        document.getElementById("editNotes").value = button.dataset.notes || "";
        document.getElementById("editBalance").value =
          button.dataset.balance || "0.00";
        editModal.style.display = "block";
      });
    });
    closeModalBtn.addEventListener("click", () => {
      editModal.style.display = "none";
    });
    window.addEventListener("click", (event) => {
      if (event.target === editModal) {
        editModal.style.display = "none";
      }
    });
  }

  // Route complete confirmation
  document.querySelectorAll(".route-complete-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      if (!confirm("Mark this stop as completed?")) {
        event.preventDefault();
      }
    });
  });

  // ────────────────────────────────────────────────────────────────
  // Area Optimizer (Quick Add by Area)
  // ────────────────────────────────────────────────────────────────

  const areaModal = document.getElementById("area-optimizer-modal");
  const areaModalCloseBtn = areaModal?.querySelector(
    ".close-area-modal, button[onclick*='hidden']",
  );

  window.openAreaOptimizer = async () => {
    if (!areaModal) {
      console.warn("Area optimizer modal not found in DOM");
      return;
    }

    areaModal.classList.remove("hidden");

    const contentContainer = areaModal.querySelector(
      ".flex-1, .overflow-y-auto",
    );
    if (!contentContainer) return;

    // Show loading state
    contentContainer.innerHTML = `
      <div class="text-center py-12 text-gray-500">
        <svg class="animate-spin h-8 w-8 mx-auto mb-4 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        Loading areas...
      </div>
    `;

    try {
      const response = await fetch("/calendar/customers_by_area");
      if (!response.ok) throw new Error("Failed to load customers by area");

      const groups = await response.json();

      if (Object.keys(groups).length === 0) {
        contentContainer.innerHTML = `
          <div class="text-center py-12 text-gray-500">
            No priority customers found in any area right now.
          </div>
        `;
        return;
      }

      let html = "";
      Object.entries(groups).forEach(([area, customers]) => {
        html += `
          <div class="mb-8">
            <div class="flex items-center justify-between mb-4">
              <h4 class="text-xl font-semibold text-white">
                ${area}
                <span class="ml-2 text-sm text-gray-500">(${customers.length})</span>
              </h4>
              <!-- Optional: Add All button – needs backend support -->
              <!-- <button class="text-sm bg-purple-600 hover:bg-purple-700 px-4 py-1 rounded">Add All</button> -->
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              ${customers
                .map(
                  (customer) => `
                <div class="bg-gray-800 rounded-xl p-5 hover:bg-gray-750 transition border border-gray-700">
                  <div class="font-medium text-lg mb-2">${customer.name}</div>
                  <div class="text-sm text-gray-400 mb-3">${customer.address}</div>
                  <div class="flex flex-wrap gap-2 mb-4">
                    ${
                      customer.balance_cents > 0
                        ? `
                      <span class="text-xs bg-red-500/30 text-red-400 px-2.5 py-1 rounded-full">
                        Owes ${formatCurrency(customer.balance_cents)}
                      </span>
                    `
                        : ""
                    }
                    ${
                      customer.days_since && customer.days_since > 14
                        ? `
                      <span class="text-xs bg-amber-500/30 text-amber-400 px-2.5 py-1 rounded-full">
                        ${customer.days_since}+ days
                      </span>
                    `
                        : ""
                    }
                  </div>
                  <button
                    onclick="quickAddFromArea(${customer.id})"
                    class="w-full bg-green-600 hover:bg-green-700 text-white py-2.5 rounded-lg font-medium transition">
                    + Add to ${selectedDate ? "selected day" : "Today"}
                  </button>
                </div>
              `,
                )
                .join("")}
            </div>
          </div>
        `;
      });

      contentContainer.innerHTML = html;
    } catch (err) {
      console.error("Error loading areas:", err);
      contentContainer.innerHTML = `
        <div class="text-center py-12 text-red-400">
          Failed to load customers by area.<br>
          Please try again later.
        </div>
      `;
    }
  };

  // Quick add function – fills the existing Quick Add modal
  window.quickAddFromArea = (customerId) => {
    const quickAddModal = document.getElementById("quickAddModal");
    if (!quickAddModal) {
      alert("Quick add modal not found");
      return;
    }

    const form = quickAddModal.querySelector("form");
    if (!form) return;

    // Set customer
    const select = form.querySelector('select[name="customer_id"]');
    if (select) select.value = customerId;

    // Set date (selected from calendar or today)
    const dateInput = form.querySelector('input[name="date"]');
    if (dateInput) {
      dateInput.value = selectedDate || new Date().toISOString().split("T")[0];
    }

    // Optional: pre-fill notes
    const notesTextarea = form.querySelector('textarea[name="notes"]');
    if (notesTextarea) notesTextarea.value = "Added from Area Optimizer";

    // Open the modal
    quickAddModal.classList.remove("hidden");
  };

  // Close area modal (if you have a dedicated close button)
  if (areaModalCloseBtn) {
    areaModalCloseBtn.addEventListener("click", () => {
      areaModal.classList.add("hidden");
    });
  }

  // Close on outside click
  if (areaModal) {
    areaModal.addEventListener("click", (e) => {
      if (e.target === areaModal) {
        areaModal.classList.add("hidden");
      }
    });
  }
});
