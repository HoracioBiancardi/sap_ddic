/**
 * Application entrypoint: wires the persistent app shell (sidebar nav +
 * topbar search + swappable content view) together — search, the field
 * dictionary table, the lineage graph, the JSON viewer and the dbt
 * generator all live as views inside one shell, switched by icon nav
 * instead of by navigating through a sequence of full-page screens.
 *
 * Search is deliberately explicit (Enter / "Buscar" button), not
 * live-as-you-type: this environment's HANA Cloud connection has a ~2-5s
 * round-trip floor regardless of query complexity (measured — even a
 * trivial `SELECT 1` takes over a second), so a live-typing autocomplete
 * would just fire a slow request per keystroke pause and feel perpetually
 * behind. One intentional search per explicit action reads as "the app is
 * working" instead of "the app is stuck".
 *
 * Selecting a table never forces a screen jump: if the user is already
 * inside a table-scoped view (Dicionário, Linhagem, ...), picking a new
 * table re-renders that same view for the new table instead of resetting
 * to the summary. Only the very first table of a session (coming from the
 * home/search view) defaults to "Resumo".
 */

import { getTable, searchTables } from "./api.js";
import { generateInitialDbtArtifacts, initDbtGenerator, resetDbtGenerator } from "./dbtGenerator.js";
import { initExportButtons } from "./exports.js";
import { renderLineageGraph } from "./graph.js";
import { initJsonToolbar, renderJson } from "./jsonViewer.js";
import { initMartGenerator } from "./martGenerator.js";
import { renderColumnsTable, renderEnumModal, renderSummary } from "./render.js";
import { state } from "./state.js";
import {
  clearSearchError,
  getActiveView,
  hideSearchLoading,
  hideTableFetchLoading,
  initBackButton,
  initNav,
  resetToHome,
  setBackAvailable,
  setTopbarTable,
  showSearchError,
  showSearchLoading,
  showTableFetchLoading,
  showView,
} from "./views.js";

const searchInput = document.getElementById("search-input");
const btnSearch = document.getElementById("btn-search");
const searchResultsList = document.getElementById("autocomplete-list");
const chkShowAllLineage = document.getElementById("chk-show-all-lineage");
const lineageToggleLabel = document.getElementById("lineage-toggle-label");
const navHomeItem = document.querySelector('.nav-item[data-view="home"]');

let lineageRendered = false;
let dbtRendered = false;

// Stack of table names visited before drilling into a related table (via a
// lineage node or a dictionary 🔗 check-table tag), so the "← Voltar" button
// can step back one table at a time. A fresh search (picking a result from
// the search box) starts a new browsing session and clears it.
let tableHistory = [];

function renderSearchResults(results) {
  if (results.length === 0) {
    searchResultsList.classList.add("hidden");
    searchResultsList.innerHTML = "";
    return;
  }

  searchResultsList.innerHTML = results
    .map(
      (row) => `
        <li class="autocomplete-item" data-table-name="${row.table_name}">
          <span class="table-name">${row.table_name}</span>
          <span class="table-desc">${row.description}</span>
        </li>`
    )
    .join("");
  searchResultsList.classList.remove("hidden");

  searchResultsList.querySelectorAll(".autocomplete-item").forEach((item) => {
    item.addEventListener("click", () => {
      searchInput.value = item.dataset.tableName;
      searchResultsList.classList.add("hidden");
      tableHistory = [];
      setBackAvailable(false);
      selectTable(item.dataset.tableName);
    });
  });
}

async function performSearch() {
  const term = searchInput.value.trim();
  if (!term) {
    return;
  }

  clearSearchError();
  renderSearchResults([]);
  showSearchLoading();
  btnSearch.disabled = true;

  try {
    const results = await searchTables(term);
    renderSearchResults(results);
    if (results.length === 0) {
      showSearchError("Nenhuma tabela encontrada para esse termo.");
    }
  } catch (error) {
    showSearchError(error.message || "Erro ao buscar tabelas.");
  } finally {
    hideSearchLoading();
    btnSearch.disabled = false;
  }
}

function updateLineageToggleLabel(contract) {
  const total = contract.parent_tables.length;
  const hidden = contract.parent_tables.filter((p) => p.importance === "Baixa").length;
  chkShowAllLineage.checked = false;
  lineageToggleLabel.textContent =
    hidden > 0 ? `Mostrar todas as tabelas (${hidden} ocultas de ${total})` : `Mostrar todas as tabelas (${total})`;
}

function goToTable(tableName) {
  if (state.currentTable) {
    tableHistory.push(state.currentTable);
    setBackAvailable(true);
  }
  searchInput.value = tableName;
  selectTable(tableName);
}

function goBackTable() {
  const previousTable = tableHistory.pop();
  if (!previousTable) return;
  setBackAvailable(tableHistory.length > 0);
  searchInput.value = previousTable;
  selectTable(previousTable);
}

async function selectTable(tableName) {
  lineageRendered = false;
  dbtRendered = false;
  resetDbtGenerator();
  clearSearchError();
  renderSearchResults([]);
  showTableFetchLoading();
  try {
    const contract = await getTable(tableName);
    state.currentTable = tableName;
    state.contract = contract;

    hideTableFetchLoading();
    setTopbarTable(contract.table_name, contract.business_description);

    renderSummary(contract);
    renderColumnsTable(
      contract,
      (column) => renderEnumModal(column),
      (checkTableName) => goToTable(checkTableName)
    );
    renderJson(contract);
    updateLineageToggleLabel(contract);

    const targetView = getActiveView() === "home" ? "resumo" : getActiveView();
    showView(targetView);

    if (targetView === "linhagem") {
      renderLineageGraph(contract, { showAll: chkShowAllLineage.checked, onNodeClick: goToTable });
      lineageRendered = true;
    } else if (targetView === "dbt") {
      generateInitialDbtArtifacts(contract.table_name);
      dbtRendered = true;
    }
  } catch (error) {
    hideTableFetchLoading();
    showSearchError(error.message || "Erro ao buscar a tabela.");
  }
}

btnSearch.addEventListener("click", performSearch);

searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    performSearch();
  }
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".topbar-search")) {
    searchResultsList.classList.add("hidden");
  }
});

navHomeItem.addEventListener("click", () => {
  tableHistory = [];
  searchInput.value = "";
  clearSearchError();
  renderSearchResults([]);
  resetToHome();
  searchInput.focus();
});

initBackButton(goBackTable);

initNav((viewName) => {
  if (viewName === "linhagem" && !lineageRendered && state.contract) {
    renderLineageGraph(state.contract, { showAll: chkShowAllLineage.checked, onNodeClick: goToTable });
    lineageRendered = true;
  }
  if (viewName === "dbt" && !dbtRendered && state.contract) {
    generateInitialDbtArtifacts(state.contract.table_name);
    dbtRendered = true;
  }
});

chkShowAllLineage.addEventListener("change", () => {
  if (state.contract) {
    renderLineageGraph(state.contract, { showAll: chkShowAllLineage.checked, onNodeClick: goToTable });
  }
});

initJsonToolbar(() => state.contract);
initExportButtons(() => state.contract);
initDbtGenerator(() => state.currentTable);
initMartGenerator();

searchInput.focus();
