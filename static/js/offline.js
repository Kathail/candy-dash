/* ============================================
   Candy Route Planner - Offline Payment Queue
   ============================================ */

(function () {
  "use strict";

  var QUEUE_KEY = "paymentQueue";

  /**
   * Add a payment to the offline queue.
   * @param {string|number} customerId
   * @param {number} amount
   * @param {string} [notes='']
   * @returns {object} The queued payment entry.
   */
  function addToQueue(customerId, amount, notes) {
    var queue = getQueue();
    var entry = {
      customerId: String(customerId),
      amount: parseFloat(amount),
      notes: notes || "",
      timestamp: new Date().toISOString(),
      receiptRef: "OFL-" + Date.now() + "-" + Math.random().toString(36).slice(2, 7).toUpperCase(),
    };
    queue.push(entry);
    saveQueue(queue);
    updateBadge();

    if (window.CandyApp && window.CandyApp.toast) {
      window.CandyApp.toast.show(
        "Payment queued offline (Ref: " + entry.receiptRef + ")",
        "warning",
        4000
      );
    }

    return entry;
  }

  /**
   * Get all queued payments.
   * @returns {Array}
   */
  function getQueue() {
    try {
      var raw = localStorage.getItem(QUEUE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  /**
   * Clear the entire queue.
   */
  function clearQueue() {
    localStorage.removeItem(QUEUE_KEY);
    updateBadge();
  }

  /**
   * Return number of items in the queue.
   * @returns {number}
   */
  function getQueueCount() {
    return getQueue().length;
  }

  /**
   * Sync queued payments to the server.
   * POSTs to /api/sync. On success clears queue; on failure keeps it.
   * @returns {Promise}
   */
  function syncPayments() {
    var queue = getQueue();
    if (queue.length === 0) return Promise.resolve();

    return fetch("/api/sync", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify({ payments: queue }),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("Sync failed: " + resp.status);
        return resp.json();
      })
      .then(function (data) {
        clearQueue();
        if (window.CandyApp && window.CandyApp.toast) {
          var count = queue.length;
          window.CandyApp.toast.show(
            count + " offline payment" + (count !== 1 ? "s" : "") + " synced successfully.",
            "success",
            4000
          );
        }
        return data;
      })
      .catch(function (err) {
        console.error("[OfflineQueue] Sync error:", err);
        if (window.CandyApp && window.CandyApp.toast) {
          window.CandyApp.toast.show(
            "Failed to sync offline payments. Will retry when connected.",
            "error",
            5000
          );
        }
      });
  }

  /* ------------------------------------------
     Internal helpers
     ------------------------------------------ */
  function saveQueue(queue) {
    try {
      localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    } catch (e) {
      console.error("[OfflineQueue] Could not save to localStorage:", e);
    }
  }

  function updateBadge() {
    var count = getQueueCount();
    var badges = document.querySelectorAll("[data-offline-badge]");
    badges.forEach(function (badge) {
      if (count > 0) {
        badge.textContent = count;
        badge.classList.remove("hidden");
      } else {
        badge.textContent = "";
        badge.classList.add("hidden");
      }
    });
  }

  /* ------------------------------------------
     Event Listeners
     ------------------------------------------ */
  window.addEventListener("online", function () {
    if (getQueueCount() > 0) {
      syncPayments();
    }
  });

  // On load: if online and queue has items, sync immediately
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      updateBadge();
      if (navigator.onLine && getQueueCount() > 0) {
        syncPayments();
      }
    });
  } else {
    updateBadge();
    if (navigator.onLine && getQueueCount() > 0) {
      syncPayments();
    }
  }

  // Expose public API
  window.OfflineQueue = {
    addToQueue: addToQueue,
    getQueue: getQueue,
    clearQueue: clearQueue,
    syncPayments: syncPayments,
    getQueueCount: getQueueCount,
  };
})();
