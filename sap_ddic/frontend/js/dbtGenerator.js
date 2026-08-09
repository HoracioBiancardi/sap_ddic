/**
 * "Gerador SQL" tab: turns the already-fetched table contract into a
 * staging SQL model (+ dbt sources.yml, when enabled), via
 * GET /api/table/{name}/dbt.
 *
 * The load type and schema inputs are pre-filled from the first,
 * override-free call (which applies the same FULL/INCREMENTAL heuristic as
 * the sibling datasphere_generator_dbt project); the user can then edit them
 * and click "Gerar SQL" again to regenerate with overrides. The watermark
 * input is informational only — it documents which SAP field to use for the
 * table's bronze ingestion config, but never changes the generated SQL/YML,
 * which always relies on the bronze layer's own dt_ingestao/hash_pk columns.
 *
 * Whether to include the dbt scaffolding (sources.yml + macros) or emit
 * plain ad-hoc SQL is a fixed, persisted preference set in Configurações
 * ("Gerar com dbt"), not a per-generation toggle — see initConfigPage in
 * app.js, which writes it to localStorage under "dbt_enabled".
 */

import { getDbtArtifacts } from "./api.js";

const loadTypeSelect = document.getElementById("dbt-load-type");
const watermarkInput = document.getElementById("dbt-watermark");
const schemaInput = document.getElementById("dbt-schema");
const warningsBox = document.getElementById("dbt-warnings");
const loadingCard = document.getElementById("dbt-loading");
const outputBox = document.getElementById("dbt-output");
const ymlArtifact = document.getElementById("dbt-yml-artifact");
const ymlCode = document.getElementById("dbt-yml-code");
const sqlCode = document.getElementById("dbt-sql-code");
const sqlArtifactTitle = document.getElementById("dbt-sql-artifact-title");

let lastArtifacts = null;

function showMessage(text, isError) {
  warningsBox.textContent = text;
  warningsBox.classList.remove("hidden");
  warningsBox.classList.toggle("dbt-warnings--error", isError);
}

function clearMessage() {
  warningsBox.classList.add("hidden");
  warningsBox.classList.remove("dbt-warnings--error");
}

function renderArtifacts(artifacts, isPlainSql) {
  lastArtifacts = artifacts;
  loadTypeSelect.value = artifacts.load_type;
  watermarkInput.value = artifacts.watermark_column || "";
  schemaInput.value = artifacts.dbt_schema;

  if (artifacts.warnings.length > 0) {
    showMessage(artifacts.warnings.join(" "), false);
  } else {
    clearMessage();
  }

  ymlArtifact.classList.toggle("hidden", isPlainSql);
  outputBox.classList.toggle("dbt-output--sql-only", isPlainSql);
  sqlArtifactTitle.textContent = isPlainSql ? "consulta.sql" : "stg_<tabela>.sql";

  ymlCode.textContent = artifacts.yml;
  Prism.highlightElement(ymlCode);
  sqlCode.textContent = artifacts.sql;
  Prism.highlightElement(sqlCode);

  outputBox.classList.remove("hidden");
}

async function generate(tableName, { useCurrentInputs } = {}) {
  loadingCard.classList.remove("hidden");
  outputBox.classList.add("hidden");
  clearMessage();

  const plainSql = localStorage.getItem("dbt_enabled") === "false";

  try {
    const defaultSchema = localStorage.getItem("dbt_schema") || "dataspherev2";
    const defaultDatabase = localStorage.getItem("dbt_database") || "BRONZE";
    const useMacros = localStorage.getItem("dbt_use_macros") !== "false";

    const overrides = {
      loadType: useCurrentInputs ? loadTypeSelect.value : null,
      watermarkColumn: useCurrentInputs ? watermarkInput.value.trim() : null,
      schema: useCurrentInputs ? schemaInput.value.trim() : defaultSchema,
      database: defaultDatabase,
      useMacros: useMacros,
      sqlTemplate: localStorage.getItem("temp_staging_sql") || null,
      ymlTemplate: localStorage.getItem("temp_staging_yml") || null,
      plainSql: plainSql,
      useBusinessAlias: localStorage.getItem("use_business_alias") === "true",
    };
    const artifacts = await getDbtArtifacts(tableName, overrides);
    renderArtifacts(artifacts, plainSql);
  } catch (error) {
    showMessage(error.message || "Erro ao gerar os artefatos SQL.", true);
  } finally {
    loadingCard.classList.add("hidden");
  }
}

async function copyToClipboard(buttonId, text) {
  const button = document.getElementById(buttonId);
  await navigator.clipboard.writeText(text);
  const original = button.textContent;
  button.textContent = "Copiado!";
  setTimeout(() => {
    button.textContent = original;
  }, 1500);
}

function downloadFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Wires up the "Gerar dbt" button and the copy/download buttons for both
 * artifacts. Call once at startup.
 * @param {() => string} getTableName - Returns the currently selected table's name.
 */
export function initDbtGenerator(getTableName) {
  document.getElementById("btn-generate-dbt").addEventListener("click", () => {
    generate(getTableName(), { useCurrentInputs: true });
  });

  document
    .getElementById("btn-copy-yml")
    .addEventListener("click", () => copyToClipboard("btn-copy-yml", lastArtifacts?.yml || ""));
  document
    .getElementById("btn-copy-sql")
    .addEventListener("click", () => copyToClipboard("btn-copy-sql", lastArtifacts?.sql || ""));

  document.getElementById("btn-download-yml").addEventListener("click", () => {
    downloadFile(`stg_${getTableName().toLowerCase()}.yml`, lastArtifacts?.yml || "", "text/yaml");
  });
  document.getElementById("btn-download-sql").addEventListener("click", () => {
    downloadFile(`stg_${getTableName().toLowerCase()}.sql`, lastArtifacts?.sql || "", "text/plain");
  });
}

/**
 * Triggers the first, auto-suggested dbt generation for a freshly selected
 * table. Called lazily, the first time the tab becomes active for that table.
 * @param {string} tableName - Technical table name.
 */
export function generateInitialDbtArtifacts(tableName) {
  return generate(tableName, { useCurrentInputs: false });
}

/**
 * Clears the tab's output; called whenever a new table is selected so stale
 * artifacts from the previous table never linger in a hidden tab.
 */
export function resetDbtGenerator() {
  lastArtifacts = null;
  outputBox.classList.add("hidden");
  clearMessage();
}
