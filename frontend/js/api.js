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
