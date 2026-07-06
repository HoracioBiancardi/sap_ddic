/**
 * Application entrypoint: wires search, three-screen navigation (landing ->
 * summary -> details), dictionary table, lineage graph and JSON viewer
 * together.
 *
 * Search is deliberately explicit (Enter / "Buscar" button), not
 * live-as-you-type: this environment's HANA Cloud connection has a ~2-5s
 * round-trip floor regardless of query complexity (measured — even a
 * trivial `SELECT 1` takes over a second), so a live-typing autocomplete
 * would just fire a slow request per keystroke pause and feel perpetually
 * behind. One intentional search per explicit action reads as "the app is
 * working" instead of "the app is stuck".
 */

import { getTable, searchTables } from "./api.js";
import { initExportButtons } from "./exports.js";
import { renderLineageGraph } from "./graph.js";
import { initJsonToolbar, renderJson } from "./jsonViewer.js";
import { renderColumnsTable, renderEnumModal, renderSummary } from "./render.js";
import { state } from "./state.js";
import { initTabs } from "./tabs.js";
import {
  clearSearchError,
  hideSearchLoading,
  hideSummaryLoading,
  showDetails,
  showLanding,
  showSearchError,
  showSearchLoading,
  showSummary,
  showSummaryLoading,
} from "./views.js";

const searchInput = document.getElementById("search-input");
const btnSearch = document.getElementById("btn-search");
const searchResultsList = document.getElementById("autocomplete-list");
const searchResultsLoading = document.getElementById("search-results-loading");
const btnNewSearch = document.getElementById("btn-new-search");
const btnViewDetails = document.getElementById("btn-view-details");
const btnBackToSummary = document.getElementById("btn-back-to-summary");
const chkShowAllLineage = document.getElementById("chk-show-all-lineage");
const lineageToggleLabel = document.getElementById("lineage-toggle-label");

let lineageRendered = false;

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
  searchResultsLoading.classList.remove("hidden");
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
    searchResultsLoading.classList.add("hidden");
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
  searchInput.value = tableName;
  selectTable(tableName);
}

async function selectTable(tableName) {
  lineageRendered = false;
  clearSearchError();
  renderSearchResults([]);
  showSearchLoading();
  try {
    const contract = await getTable(tableName);
    state.currentTable = tableName;
    state.contract = contract;

    hideSearchLoading();
    showSummary();
    hideSummaryLoading();
    renderSummary(contract);

    document.getElementById("details-table-name").textContent = contract.table_name;
    renderColumnsTable(
      contract,
      (column) => renderEnumModal(column),
      (checkTableName) => goToTable(checkTableName)
    );
    renderJson(contract);
    updateLineageToggleLabel(contract);

    const activeTab = document.querySelector(".tab-button.active")?.dataset.tab;
    if (activeTab === "linhagem") {
      renderLineageGraph(contract, { showAll: chkShowAllLineage.checked, onNodeClick: goToTable });
      lineageRendered = true;
    }
  } catch (error) {
    hideSearchLoading();
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
  if (!event.target.closest(".search-card")) {
    searchResultsList.classList.add("hidden");
  }
});

btnNewSearch.addEventListener("click", () => {
  searchInput.value = "";
  clearSearchError();
  renderSearchResults([]);
  showLanding();
  searchInput.focus();
});

btnViewDetails.addEventListener("click", () => {
  showDetails();
});

btnBackToSummary.addEventListener("click", () => {
  showSummary();
});

initTabs((tabName) => {
  if (tabName === "linhagem" && !lineageRendered && state.contract) {
    renderLineageGraph(state.contract, { showAll: chkShowAllLineage.checked, onNodeClick: goToTable });
    lineageRendered = true;
  }
});

chkShowAllLineage.addEventListener("change", () => {
  if (state.contract) {
    renderLineageGraph(state.contract, { showAll: chkShowAllLineage.checked, onNodeClick: goToTable });
  }
});

initJsonToolbar(() => state.contract);
initExportButtons(() => state.contract);

showLanding();
searchInput.focus();
