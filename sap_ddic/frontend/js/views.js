/**
 * App-shell navigation: a persistent sidebar + topbar frame around a single
 * content area whose section ("view") is swapped by icon nav, not by
 * navigating through a sequence of full-page screens. This replaces the
 * previous landing -> summary -> details screen chain and the separate
 * in-page tab bar with one model: every icon is always clickable, even
 * before any table has ever been loaded — a table-scoped view just renders
 * whatever it last had (its own empty state if nothing was ever loaded, or
 * the last-loaded table's data otherwise), so switching views never throws
 * away context.
 */

const navItems = Array.from(document.querySelectorAll(".nav-item"));
const views = Array.from(document.querySelectorAll(".view"));

const topbarTableInfo = document.getElementById("topbar-table-info");
const topbarTableName = document.getElementById("topbar-table-name");
const topbarTableDescription = document.getElementById("topbar-table-description");
const btnBackTable = document.getElementById("btn-back-table");

const searchError = document.getElementById("search-error");
const searchResultsLoading = document.getElementById("search-results-loading");
const tableFetchLoading = document.getElementById("table-fetch-loading");
const tableCountStat = document.getElementById("table-count-stat");
const searchResultsCount = document.getElementById("search-results-count");

// The search widget lives inside the home hero (between the subtitle and the
// feature cards) while on the home view, and moves into the topbar for every
// table-scoped view, so a new table can always be searched without leaving
// the current view. Reparenting (not duplicating) keeps one input/one set of
// listeners as the single source of truth.
const searchWidget = document.getElementById("search-widget");
const homeSearchSlot = document.getElementById("home-search-slot");
const topbarSearchSlot = document.getElementById("topbar-search-slot");

let activeView = "home";

function positionSearchWidget(viewName) {
  const target = viewName === "home" ? homeSearchSlot : topbarSearchSlot;
  if (searchWidget.parentElement !== target) {
    target.appendChild(searchWidget);
  }
}

function setActiveView(viewName) {
  activeView = viewName;
  navItems.forEach((item) => item.classList.toggle("active", item.dataset.view === viewName));
  views.forEach((view) => view.classList.toggle("hidden", view.id !== `view-${viewName}`));
  positionSearchWidget(viewName);
}

/**
 * Switches the content area to the given view name (home/resumo/dicionario/
 * linhagem/json/dbt/mart).
 * @param {string} viewName
 */
export function showView(viewName) {
  setActiveView(viewName);
}

/**
 * Returns the name of the currently visible view.
 */
export function getActiveView() {
  return activeView;
}

/**
 * Wires up sidebar icon clicks. `onNavigate` fires with the view name every
 * time the user switches views (used to lazily render the lineage graph /
 * dbt output the first time their view becomes visible).
 * @param {(viewName: string) => void} onNavigate
 */
export function initNav(onNavigate) {
  navItems.forEach((item) => {
    item.addEventListener("click", () => {
      setActiveView(item.dataset.view);
      onNavigate?.(item.dataset.view);
    });
  });
}

/**
 * Switches to the home view for a fresh search, clearing the drill-down
 * "← Voltar" trail. Deliberately leaves the topbar's current-table
 * breadcrumb and every other view's already-rendered data alone — going
 * home to search something else doesn't throw away what you were just
 * looking at, so the other icons keep showing your last table until (and
 * unless) you actually load a new one.
 */
export function resetToHome() {
  setBackAvailable(false);
  setActiveView("home");
}

/**
 * Updates the topbar's "current table" breadcrumb (name + description).
 * @param {string} tableName
 * @param {string} description
 */
export function setTopbarTable(tableName, description) {
  topbarTableName.textContent = tableName;
  topbarTableDescription.textContent = description;
  topbarTableInfo.classList.remove("hidden");
}

/**
 * Wires the topbar "← Voltar" button, shown whenever the user has drilled
 * into a related table (via a lineage node or a dictionary 🔗 check-table
 * tag) so they can step back to the table they came from.
 * @param {() => void} onBack
 */
export function initBackButton(onBack) {
  btnBackTable.addEventListener("click", onBack);
}

/**
 * Shows or hides the topbar "← Voltar" button.
 * @param {boolean} available
 */
export function setBackAvailable(available) {
  btnBackTable.classList.toggle("hidden", !available);
}

/**
 * Shows the inline "Carregando tabela..." indicator next to the topbar search.
 */
export function showTableFetchLoading() {
  tableFetchLoading.classList.remove("hidden");
}

/**
 * Hides the inline table-fetch loading indicator.
 */
export function hideTableFetchLoading() {
  tableFetchLoading.classList.add("hidden");
}

/**
 * Shows the "Buscando tabelas..." indicator under the topbar search input.
 */
export function showSearchLoading() {
  searchResultsLoading.classList.remove("hidden");
}

/**
 * Hides the topbar name-search loading indicator.
 */
export function hideSearchLoading() {
  searchResultsLoading.classList.add("hidden");
}

/**
 * Shows an inline error message next to the topbar search input.
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

/**
 * Shows the total-tables figure under the hero subtitle.
 * @param {number} total - Total number of tables in the DDIC schema.
 */
export function showTableCount(total) {
  tableCountStat.textContent = `${total} TABELAS DISPONÍVEIS NO DICIONÁRIO DDIC`;
  tableCountStat.classList.remove("hidden");
}

/**
 * Shows the "N resultado(s)" line above the search results list.
 * @param {number} count - Number of results currently rendered.
 */
export function showSearchResultsCount(count) {
  searchResultsCount.textContent = `${count} resultado${count === 1 ? "" : "s"}`;
  searchResultsCount.classList.remove("hidden");
}

/**
 * Hides the search results count line.
 */
export function hideSearchResultsCount() {
  searchResultsCount.classList.add("hidden");
}
