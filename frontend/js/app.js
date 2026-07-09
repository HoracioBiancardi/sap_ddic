/**
 * Application entrypoint: wires the persistent app shell (sidebar nav +
 * topbar search + swappable content view) together.
 */

import { getTable, searchTables } from "./api.js";
import { generateInitialDbtArtifacts, initDbtGenerator, resetDbtGenerator } from "./dbtGenerator.js";
import { initExportButtons } from "./exports.js";
import { renderLineageGraph } from "./graph.js";
import { initJsonToolbar, renderJson } from "./jsonViewer.js";
import { initMartGenerator } from "./martGenerator.js";
import { renderColumnsTable, renderEnumModal, renderSummary, renderRelations } from "./render.js";
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
let tableHistory = [];

// Default templates
const DEFAULT_STAGING_SQL = `{{
    config(
        tags=["{source_name}", "silver"],
        alias="{table_name}",
        materialized="{materialized}",{config_extra}
    )
}}
{incremental_header}
SELECT
{columns}
FROM {source_relation}{incremental_footer}
`;

const DEFAULT_STAGING_YML = `sources:
  - name: {source_name}
    database: {database}
    schema: {schema}
    tables:
      - name: {table_name}
        description: "{description}"
        config:
          materialized: {materialized}
          {config_extra}
        columns:
{columns}
`;

const DEFAULT_MART_SQL = `{{
    config(
        tags=['{source_name}', 'gold'],
        alias='{model_name}',
        materialized='table',
    )
}}

SELECT
{columns}
FROM {source_relation}
{joins}
`;

const DEFAULT_MART_YML = `version: 2

models:
  - name: {model_name}
    description: "{description}"
    columns:
{columns}
`;

const DEFAULT_MACROS_CODE = `-- macros/sap_ddic_macros.sql

{% macro nullif_empty(field) %}
    NULLIF(TRIM({{ field }}), '')
{% endmacro %}

{% macro to_date(field) %}
    TRY_CAST(NULLIF(TRIM({{ field }}), '') AS DATE)
{% endmacro %}

{% macro to_decimal_nullif(field) %}
    TRY_CAST(NULLIF(TRIM({{ field }}), '') AS DECIMAL)
{% endmacro %}

{% macro to_integer_nullif(field) %}
    TRY_CAST(NULLIF(TRIM({{ field }}), '') AS INTEGER)
{% endmacro %}

{% macro to_timestamp(field) %}
    TRY_CAST(NULLIF(TRIM({{ field }}), '') AS TIMESTAMP)
{% endmacro %}
`;

function initConfigPage() {
  const dbInput = document.getElementById("config-dbt-database");
  const schemaInput = document.getElementById("config-dbt-schema");
  const useMacrosCheck = document.getElementById("config-dbt-use-macros");

  const themeSelect = document.getElementById("config-ui-theme");
  const scanlinesCheck = document.getElementById("config-ui-scanlines");
  const flickerCheck = document.getElementById("config-ui-flicker");

  const tempStagingSql = document.getElementById("temp-staging-sql");
  const tempStagingYml = document.getElementById("temp-staging-yml");
  const tempMartSql = document.getElementById("temp-mart-sql");
  const tempMartYml = document.getElementById("temp-mart-yml");

  const referenceCode = document.getElementById("macros-reference-code");
  if (referenceCode) {
    referenceCode.textContent = DEFAULT_MACROS_CODE;
    Prism.highlightElement(referenceCode);
  }

  // Load values from localStorage
  dbInput.value = localStorage.getItem("dbt_database") || "BRONZE";
  schemaInput.value = localStorage.getItem("dbt_schema") || "dataspherev2";
  useMacrosCheck.checked = localStorage.getItem("dbt_use_macros") !== "false";

  themeSelect.value = localStorage.getItem("ui_theme") || "green";
  scanlinesCheck.checked = localStorage.getItem("ui_scanlines") !== "false";
  flickerCheck.checked = localStorage.getItem("ui_flicker") !== "false";

  // Apply UI settings immediately
  applyUiSettings();

  // Load templates
  tempStagingSql.value = localStorage.getItem("temp_staging_sql") || DEFAULT_STAGING_SQL;
  tempStagingYml.value = localStorage.getItem("temp_staging_yml") || DEFAULT_STAGING_YML;
  tempMartSql.value = localStorage.getItem("temp_mart_sql") || DEFAULT_MART_SQL;
  tempMartYml.value = localStorage.getItem("temp_mart_yml") || DEFAULT_MART_YML;

  // Save config
  document.getElementById("btn-save-config").addEventListener("click", () => {
    localStorage.setItem("dbt_database", dbInput.value.trim());
    localStorage.setItem("dbt_schema", schemaInput.value.trim());
    localStorage.setItem("dbt_use_macros", useMacrosCheck.checked);
    localStorage.setItem("ui_theme", themeSelect.value);
    localStorage.setItem("ui_scanlines", scanlinesCheck.checked);
    localStorage.setItem("ui_flicker", flickerCheck.checked);

    localStorage.setItem("temp_staging_sql", tempStagingSql.value);
    localStorage.setItem("temp_staging_yml", tempStagingYml.value);
    localStorage.setItem("temp_mart_sql", tempMartSql.value);
    localStorage.setItem("temp_mart_yml", tempMartYml.value);

    applyUiSettings();

    const status = document.getElementById("config-save-status");
    status.classList.remove("hidden");
    setTimeout(() => {
      status.classList.add("hidden");
    }, 2000);
  });

  // Reset templates
  document.getElementById("btn-reset-templates").addEventListener("click", () => {
    tempStagingSql.value = DEFAULT_STAGING_SQL;
    tempStagingYml.value = DEFAULT_STAGING_YML;
    tempMartSql.value = DEFAULT_MART_SQL;
    tempMartYml.value = DEFAULT_MART_YML;
  });
}

function applyUiSettings() {
  const theme = localStorage.getItem("ui_theme") || "green";
  const scanlines = localStorage.getItem("ui_scanlines") !== "false";
  const flicker = localStorage.getItem("ui_flicker") !== "false";

  document.body.className = `theme-${theme}`;
  document.body.classList.toggle("crt-enabled", scanlines);
  document.body.classList.toggle("flicker-enabled", flicker);
}

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
    renderRelations(contract, (checkTableName) => goToTable(checkTableName));
    renderJson(contract);
    updateLineageToggleLabel(contract);

    const targetView = getActiveView() === "home" ? "dicionario" : getActiveView();
    showView(targetView);

    // Render lineage graph if container is expanded
    const canvasContainer = document.getElementById("canvas-linhagem-container");
    if (canvasContainer && !canvasContainer.classList.contains("hidden")) {
      renderLineageGraph(contract, { showAll: chkShowAllLineage.checked, onNodeClick: goToTable });
      lineageRendered = true;
    }

    if (targetView === "dbt") {
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
  if (viewName === "dbt" && !dbtRendered && state.contract) {
    generateInitialDbtArtifacts(state.contract.table_name);
    dbtRendered = true;
  }
});

// Graph radar collapsible trigger
const btnToggleGraph = document.getElementById("btn-toggle-graph");
const canvasContainer = document.getElementById("canvas-linhagem-container");
if (btnToggleGraph && canvasContainer) {
  btnToggleGraph.addEventListener("click", () => {
    const isHidden = canvasContainer.classList.contains("hidden");
    canvasContainer.classList.toggle("hidden");
    btnToggleGraph.textContent = isHidden ? "[ OCULTAR GRAFO RADAR (LINHAGEM) ]" : "[ MOSTRAR GRAFO RADAR (LINHAGEM) ]";
    if (isHidden && !lineageRendered && state.contract) {
      renderLineageGraph(state.contract, { showAll: chkShowAllLineage.checked, onNodeClick: goToTable });
      lineageRendered = true;
    }
  });
}

chkShowAllLineage.addEventListener("change", () => {
  if (state.contract && lineageRendered) {
    renderLineageGraph(state.contract, { showAll: chkShowAllLineage.checked, onNodeClick: goToTable });
  }
});

// JSON modal trigger
const btnViewJsonModal = document.getElementById("btn-view-json-modal");
const jsonModal = document.getElementById("json-modal");
if (btnViewJsonModal && jsonModal) {
  btnViewJsonModal.addEventListener("click", () => {
    jsonModal.showModal();
  });
}

// Keyboard shortcuts (hotkeys 1 to 5)
document.addEventListener("keydown", (event) => {
  if (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA") {
    return;
  }
  const viewMap = {
    "1": "home",
    "2": "dicionario",
    "3": "dbt",
    "4": "mart",
    "5": "config"
  };
  if (viewMap[event.key]) {
    showView(viewMap[event.key]);
  }
});

initJsonToolbar(() => state.contract);
initExportButtons(() => state.contract);
initDbtGenerator(() => state.currentTable);
initMartGenerator();
initConfigPage();

searchInput.focus();
