/**
 * Three-screen navigation: landing (search) -> summary (one consolidated
 * card) -> details (field dictionary / lineage / JSON tabs).
 *
 * The search box only lives on the landing view. Going "back" always steps
 * one screen at a time (details -> summary -> landing), never skips ahead.
 */

const landingView = document.getElementById("landing-view");
const summaryView = document.getElementById("summary-view");
const detailsView = document.getElementById("details-view");

const searchError = document.getElementById("search-error");
const searchLoading = document.getElementById("search-loading");
const summaryLoading = document.getElementById("summary-loading");
const summaryCard = document.getElementById("summary-card");

/**
 * Switches to the landing (search-only) view.
 */
export function showLanding() {
  landingView.classList.remove("hidden");
  summaryView.classList.add("hidden");
  detailsView.classList.add("hidden");
  hideSearchLoading();
}

/**
 * Switches to the summary view (single consolidated card).
 */
export function showSummary() {
  summaryView.classList.remove("hidden");
  landingView.classList.add("hidden");
  detailsView.classList.add("hidden");
}

/**
 * Switches to the details view (field dictionary / lineage / JSON tabs).
 */
export function showDetails() {
  detailsView.classList.remove("hidden");
  summaryView.classList.add("hidden");
  landingView.classList.add("hidden");
}

/**
 * Shows a loading spinner below the landing search card while a table is
 * being fetched, before the view switches to the summary screen.
 */
export function showSearchLoading() {
  searchLoading.classList.remove("hidden");
}

/**
 * Hides the landing search-loading spinner.
 */
export function hideSearchLoading() {
  searchLoading.classList.add("hidden");
}

/**
 * Shows a loading spinner in place of the summary card.
 */
export function showSummaryLoading() {
  summaryLoading.classList.remove("hidden");
  summaryCard.classList.add("hidden");
}

/**
 * Hides the summary-view loading spinner, revealing the summary card.
 */
export function hideSummaryLoading() {
  summaryLoading.classList.add("hidden");
  summaryCard.classList.remove("hidden");
}

/**
 * Shows an inline error message next to the search input.
 * @param {string} message - Text to display.
 */
export function showSearchError(message) {
  searchError.textContent = message;
  searchError.classList.remove("hidden");
}

/**
 * Hides the inline search error message, if shown.
 */
export function clearSearchError() {
  searchError.classList.add("hidden");
}
