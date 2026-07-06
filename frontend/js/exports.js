/**
 * Scoped JSON exports: technical fact sheet, join/lineage keys, and fields
 * only — narrower alternatives to the full contract download for whoever
 * just needs one slice (e.g. feeding field names into a script, or the
 * join keys into a data pipeline).
 */

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
 * Builds the table's technical attributes as a standalone JSON object.
 * @param {object} contract - The SAPTableMetadata contract.
 * @returns {object} Technical fact sheet.
 */
function buildTechnicalPayload(contract) {
  return {
    table_name: contract.table_name,
    technical_class: contract.technical_class,
    table_type: contract.table_type,
    hierarchy_type: contract.hierarchy_type,
    associated_text_table: contract.associated_text_table,
    technical_stats: contract.technical_stats,
  };
}

/**
 * Builds the join/lineage keys as a standalone JSON array: one entry per
 * child/parent field pair, flattened out of parent_tables.
 * @param {object} contract - The SAPTableMetadata contract.
 * @returns {object} Lineage payload.
 */
function buildLineagePayload(contract) {
  const joins = contract.parent_tables.flatMap((parent) =>
    parent.foreign_key_fields.map((fk) => ({
      child_table: contract.table_name,
      child_field: fk.child_field,
      parent_table: parent.parent_table_name,
      parent_field: fk.parent_field,
      relationship_type: parent.relationship_type,
    }))
  );
  return { table_name: contract.table_name, associated_text_table: contract.associated_text_table, joins };
}

/**
 * Builds the fields list as a standalone JSON object, matching the
 * Dicionário tab.
 * @param {object} contract - The SAPTableMetadata contract.
 * @returns {object} Fields payload.
 */
function buildFieldsPayload(contract) {
  return { table_name: contract.table_name, columns: contract.columns };
}

/**
 * Builds the primary key fields as a standalone JSON object, in key order.
 * @param {object} contract - The SAPTableMetadata contract.
 * @returns {object} Primary key payload.
 */
function buildPrimaryKeysPayload(contract) {
  const primaryKeys = contract.columns
    .filter((c) => c.is_primary_key)
    .map((c) => ({
      column_name: c.column_name,
      data_type: c.data_type,
      length: c.length,
      decimals: c.decimals,
      domain_name: c.domain_name,
    }));
  return { table_name: contract.table_name, primary_keys: primaryKeys };
}

/**
 * Wires up the scoped export buttons (técnico / linhagem / campos / PKs).
 * @param {() => object} getContract - Returns the currently displayed contract.
 */
export function initExportButtons(getContract) {
  const bindings = [
    ["btn-export-technical", buildTechnicalPayload, "tecnico"],
    ["btn-export-lineage", buildLineagePayload, "linhagem"],
    ["btn-export-fields", buildFieldsPayload, "campos"],
    ["btn-export-pks", buildPrimaryKeysPayload, "pks"],
  ];

  for (const [buttonId, build, suffix] of bindings) {
    document.getElementById(buttonId).addEventListener("click", () => {
      const contract = getContract();
      const json = JSON.stringify(build(contract), null, 2);
      downloadFile(`sap_schema_${contract.table_name}_${suffix}.json`, json, "application/json");
    });
  }
}
