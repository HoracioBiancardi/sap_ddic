/** Lightweight toast notification, ported from the app_template design system. */

const toastEl = document.getElementById("toast");
let hideTimer = null;

/**
 * Shows a transient notification in the bottom-right corner.
 * @param {string} message - Text to display.
 * @param {"success"|"error"|"info"|"warn"} [type] - Visual variant.
 * @param {number} [duration] - Milliseconds before it fades out.
 */
export function toast(message, type = "info", duration = 3000) {
  if (!toastEl) return;
  clearTimeout(hideTimer);
  toastEl.textContent = message;
  toastEl.className = `toast ${type} visible`;
  hideTimer = setTimeout(() => {
    toastEl.classList.remove("visible");
  }, duration);
}
