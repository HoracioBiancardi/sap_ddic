/**
 * Thin fetch wrappers around the backend API.
 *
 * Both endpoints are same-origin (the FastAPI app serves this frontend
 * itself), so no CORS handling is needed here.
 */

/**
 * Searches for tables matching a term.
 * @param {string} term - Raw search text typed by the user.
 * @returns {Promise<Array<{table_name: string, description: string}>>}
 */
export async function searchTables(term) {
  const response = await fetch(`/api/search?q=${encodeURIComponent(term)}`);
  if (!response.ok) {
    throw new Error(`Search failed (${response.status})`);
  }
  return response.json();
}

/**
 * Fetches the full metadata contract for a table.
 * @param {string} tableName - Technical table name.
 * @returns {Promise<object>} The SAPTableMetadata contract.
 */
export async function getTable(tableName) {
  const response = await fetch(`/api/table/${encodeURIComponent(tableName)}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

/**
 * Generates the dbt staging SQL model and sources YAML for a table.
 * @param {string} tableName - Technical table name.
 * @param {{loadType?: string, watermarkColumn?: string, schema?: string}} [overrides] -
 *   Optional overrides for the auto-suggested load type, watermark column
 *   (informational only) and sources.yml schema.
 * @returns {Promise<object>} The DbtArtifacts payload (sql, yml, load_type,
 *   watermark_column, warnings, source_name, database, dbt_schema).
 */
export async function getDbtArtifacts(tableName, overrides = {}) {
  const payload = {
    load_type: overrides.loadType || null,
    watermark_column: overrides.watermarkColumn || null,
    dbt_schema: overrides.schema || null,
    database: overrides.database || null,
    source_name: overrides.sourceName || null,
    use_macros: overrides.useMacros !== undefined ? overrides.useMacros : true,
    sql_template: overrides.sqlTemplate || null,
    yml_template: overrides.ymlTemplate || null
  };

  const response = await fetch(`/api/table/${encodeURIComponent(tableName)}/dbt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

/**
 * Generates a fact/dimension dbt mart model from an arbitrary graph of
 * table "boxes" and their join wiring — the visual builder's "Gerar" action.
 * @param {object} payload - Shaped like the backend's MartGenerateRequest:
 *   `{ tables: [{node_id, table_name}], root_node, joins: [{left_node,
 *   right_node, fields: [{left_field, right_field}], left_filter?,
 *   right_filter?, auto_detected}], mart_type?, source_name?, database?,
 *   dbt_schema? }`.
 * @returns {Promise<object>} The MartArtifacts payload (sql, yml,
 *   documentation, mart_type, model_name, base_table, joined_tables,
 *   warnings, source_name, database, dbt_schema).
 */
export async function generateMart(payload) {
  const response = await fetch("/api/mart/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
    throw new Error(message || `Request failed (${response.status})`);
  }
  return response.json();
}
