// static/js/app.js
// Candy Flask – Frontend Behavior
// Minimal, no frameworks, only what's needed

document.addEventListener("DOMContentLoaded", () => {
  console.log("Candy Flask frontend loaded");

  // Format currency helper (for future use)
  function formatCurrency(amount) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  }

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

  // Edit modal
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
        document.getElementById("editNotes").value = button.dataset.notes || ""; // pre-fill existing notes from DB
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

  // Route complete confirmation (optional, non-breaking)
  document.querySelectorAll(".route-complete-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      if (!confirm("Mark this stop as completed?")) {
        event.preventDefault();
      }
    });
  });
});
