// ==========================================================================
// Candy Dash — Offline Payment Queue
// Queues payments in localStorage when offline, syncs when back online.
// ==========================================================================

(() => {
  "use strict";

  const QUEUE_KEY = "paymentQueue";
  let _syncing = false;

  function showToast(message, category) {
    document.dispatchEvent(new CustomEvent("show-toast", {
      detail: { message, category },
    }));
  }

  function csrfToken() {
    return window.CandyDash && window.CandyDash.csrfToken
      ? window.CandyDash.csrfToken()
      : "";
  }

  /**
   * Add a payment to the offline queue.
   */
  function addToQueue(customerId, amount, notes) {
    const queue = getQueue();
    const entry = {
      customerId: String(customerId),
      amount: parseFloat(amount),
      notes: notes || "",
      timestamp: new Date().toISOString(),
      receiptRef: "OFL-" + Date.now() + "-" + Math.random().toString(36).slice(2, 7).toUpperCase(),
    };
    queue.push(entry);
    saveQueue(queue);
    updateBadge();

    showToast("Payment queued offline (Ref: " + entry.receiptRef + ")", "warning");
    return entry;
  }

  /**
   * Get all queued payments.
   */
  function getQueue() {
    try {
      const raw = localStorage.getItem(QUEUE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (_) {
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
   */
  function getQueueCount() {
    return getQueue().length;
  }

  /**
   * Sync queued payments to the server.
   * POSTs to /api/sync. On success clears queue; on failure keeps it.
   */
  function syncPayments() {
    const queue = getQueue();
    if (queue.length === 0 || _syncing) return Promise.resolve();

    _syncing = true;
    return fetch("/api/sync", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify({ payments: queue }),
    })
      .then((resp) => {
        if (!resp.ok) throw new Error("Sync failed: " + resp.status);
        return resp.json();
      })
      .then((data) => {
        const count = queue.length;
        clearQueue();
        showToast(
          count + " offline payment" + (count !== 1 ? "s" : "") + " synced successfully.",
          "success"
        );
        return data;
      })
      .catch((err) => {
        console.error("[OfflineQueue] Sync error:", err);
        showToast("Failed to sync offline payments. Will retry when connected.", "error");
      })
      .finally(() => { _syncing = false; });
  }

  // ── Internal helpers ──────────────────────────────────────────────────

  function saveQueue(queue) {
    try {
      localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    } catch (e) {
      console.error("[OfflineQueue] Could not save to localStorage:", e);
    }
  }

  function updateBadge() {
    const count = getQueueCount();
    document.querySelectorAll("[data-offline-badge]").forEach((badge) => {
      if (count > 0) {
        badge.textContent = count;
        badge.classList.remove("hidden");
      } else {
        badge.textContent = "";
        badge.classList.add("hidden");
      }
    });
  }

  // ── Event Listeners ───────────────────────────────────────────────────

  window.addEventListener("online", () => {
    if (getQueueCount() > 0) syncPayments();
  });

  // On load: update badge and sync if online
  const onReady = () => {
    updateBadge();
    if (navigator.onLine && getQueueCount() > 0) syncPayments();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onReady);
  } else {
    onReady();
  }

  // Expose public API
  window.OfflineQueue = {
    addToQueue,
    getQueue,
    clearQueue,
    syncPayments,
    getQueueCount,
  };
})();
