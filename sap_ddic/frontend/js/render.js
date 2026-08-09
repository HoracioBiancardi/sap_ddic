/**
 * DOM rendering for the dashboard cards, the field dictionary table and the
 * fixed-value enum modal.
 *
 * Colors are assigned per fixed enum value (never re-cycled per result set),
 * matching the categorical palette's "identity, not rank" rule.
 */

const TABLE_TYPE_ACCENT = {
  "Master Data": "var(--cat-blue)",
  Transactional: "var(--cat-aqua)",
  Configuration: "var(--cat-yellow)",
  Unknown: "var(--text-muted)",
};

const HIERARCHY_TYPE_ACCENT = {
  "Header / Cabeçalho": "var(--cat-violet)",
  "Item / Filha": "var(--cat-orange)",
  "Standalone / Mestre": "var(--cat-aqua)",
};

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Verified empirically against the live DDIC replica: BSEG/EKPO/VBAP (item/
// line-level transactional tables) are all APPL1, not APPL2 — APPL2 is
// configuration/customizing (e.g. the /ASU/* add-on's own Customizing
// tables), not "movement data" as an earlier version of this label assumed.
const DATA_CLASS_LABELS = {
  APPL0: "Dados mestres",
  APPL1: "Transacional",
  APPL2: "Configuração / Customização",
};

// DD09L.TABKAT: SAP's own 0-9 ordinal "expected volume" category, assigned
// by the developer at table creation. Qualitative band plus the concrete
// row-count ceiling per category, per the sibling datasphere-generator-dbt
// project's documented thresholds (sap_generator/ddic_extractor/extractor.py).
const SIZE_CATEGORY_LABELS = {
  0: "Mínima",
  1: "Pequena",
  2: "Pequena",
  3: "Média",
  4: "Média",
  5: "Grande",
  6: "Grande",
  7: "Muito grande",
  8: "Muito grande",
  9: "Muito grande",
};

const SIZE_CATEGORY_RANGES = {
  0: "até 10 mil registros",
  1: "até 40 mil registros",
  2: "até 160 mil registros",
  3: "até 650 mil registros",
  4: "até 2,5 milhões de registros",
  5: "até 10 milhões de registros",
  6: "até 40 milhões de registros",
  7: "até 160 milhões de registros",
  8: "até 650 milhões de registros",
  9: "mais de 650 milhões de registros",
};

function describeDataClass(rawValue) {
  return DATA_CLASS_LABELS[rawValue] || rawValue || "Não classificado";
}

function describeSizeCategory(rawValue) {
  const category = Number(rawValue);
  const label = SIZE_CATEGORY_LABELS[category];
  const range = SIZE_CATEGORY_RANGES[category];
  if (label && range) return `${label} (${range})`;
  return range || `Categoria ${rawValue}`;
}

/**
 * Renders the single consolidated summary card (title + all fact items).
 * @param {object} contract - The SAPTableMetadata contract.
 */
export function renderSummary(contract) {
  document.getElementById("page-table-name").textContent = contract.table_name;
  document.getElementById("page-table-description").textContent = contract.business_description;

  const facts = document.getElementById("summary-facts");

  const stats = contract.technical_stats;
  const loadTypeLabel = stats.supports_incremental_load ? "Incremental" : "Full";
  const creationFields = stats.creation_date_candidate_fields || [];
  // A "last changed" field (AEDAT, LAEDA...) is frequently zero-filled
  // ("00000000") on old or never-updated records, which makes it useless
  // as the cutoff for the very first extraction even though it's fine for
  // delta runs afterward — so when a creation-date field is also available,
  // surface both: one watermark for the initial full load, another to
  // switch to for every incremental run after that.
  const loadTypeHint = stats.supports_incremental_load
    ? creationFields.length > 0
      ? `Full inicial via ${creationFields.join(", ")} · depois trocar para ${stats.incremental_candidate_fields.join(
          ", "
        )} (pode estar zerado em registros antigos)`
      : `via ${stats.incremental_candidate_fields.join(", ")}`
    : "nenhum campo de data de alteração reconhecido";

  const items = [
    {
      label: "Tipo de tabela",
      value: contract.table_type,
      accent: TABLE_TYPE_ACCENT[contract.table_type],
    },
    {
      label: "Hierarquia",
      value: contract.hierarchy_type,
      accent: HIERARCHY_TYPE_ACCENT[contract.hierarchy_type],
    },
    {
      label: "Classe técnica",
      value: contract.technical_class,
      accent: "var(--cat-green)",
    },
    {
      label: "Tamanho do registro",
      value: `${formatBytes(stats.record_length_bytes)} · ${stats.field_count} campos`,
      accent: "var(--cat-blue)",
    },
    {
      label: "Categoria de volume",
      value: describeSizeCategory(stats.size_category),
      hint: describeDataClass(stats.data_class),
      accent: "var(--cat-violet)",
    },
    {
      label: "Carga sugerida",
      value: loadTypeLabel,
      hint: loadTypeHint,
      accent: stats.supports_incremental_load ? "var(--cat-aqua)" : "var(--cat-orange)",
    },
  ];

  facts.innerHTML = items
    .map(
      (item) => `
        <div class="fact-item">
          <span class="fact-dot" style="--accent: ${item.accent}"></span>
          <div>
            <p class="fact-label">${escapeHtml(item.label)}</p>
            <p class="fact-value">${escapeHtml(item.value)}</p>
            ${item.hint ? `<p class="fact-hint">${escapeHtml(item.hint)}</p>` : ""}
          </div>
        </div>`
    )
    .join("");
}

/**
 * Renders the field dictionary table body for a table contract.
 * @param {object} contract - The SAPTableMetadata contract.
 * @param {(column: object) => void} onShowEnum - Called when a fixed-values
 *   button is clicked, with the corresponding column object.
 * @param {(tableName: string) => void} onNavigateToTable - Called with the
 *   check table's name when its 🔗 tag is clicked, to drill into it as a
 *   fresh search.
 * @param {string} [filterText] - Free-text filter matched against field name,
 *   business description and domain name (case-insensitive, substring match).
 */
export function renderColumnsTable(contract, onShowEnum, onNavigateToTable, filterText = "") {
  const tbody = document.getElementById("columns-table-body");

  // A field's valid values can come from two different places, and a field
  // list row alone doesn't say which: a domain with fixed values (DD07T —
  // already surfaced via the "Ver valores" button) or a foreign key to a
  // check table (DD08L/DD05S, e.g. MTART -> T134), which otherwise only
  // shows up on the Linhagem tab with no per-field cross-reference. Build
  // that cross-reference here so every field's source table is visible
  // right where the field is listed.
  const checkTableByField = {};
  contract.parent_tables.forEach((parent) => {
    parent.foreign_key_fields.forEach((fk) => {
      checkTableByField[fk.child_field] = parent.parent_table_name;
    });
  });

  const normalizedFilter = filterText.trim().toLowerCase();
  const visibleColumns = normalizedFilter
    ? contract.columns.filter((column) =>
        [column.column_name, column.business_description, column.domain_name]
          .join(" ")
          .toLowerCase()
          .includes(normalizedFilter)
      )
    : contract.columns;

  if (visibleColumns.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="filter-empty-row">Nenhum campo encontrado para "${escapeHtml(
      filterText.trim()
    )}".</td></tr>`;
    return;
  }

  tbody.innerHTML = visibleColumns
    .map((column) => {
      // contract.columns is the source of truth for indices (the enum click
      // handler below looks the column back up in it), so resolve the index
      // there rather than from visibleColumns, which may be a filtered subset.
      const index = contract.columns.indexOf(column);
      const keyBadge = column.is_primary_key ? '<span class="key-badge">PK</span>' : "";
      const enumButton = column.has_fixed_values
        ? `<button class="enum-button" data-column-index="${index}">Ver valores</button>`
        : "";
      const checkTable = checkTableByField[column.column_name];
      const checkTableTag = checkTable
        ? `<button class="ref-table-tag" data-check-table="${escapeHtml(checkTable)}" title="Ver a tabela ${escapeHtml(
            checkTable
          )}">🔗 ${escapeHtml(checkTable)}</button>`
        : "";
      return `
        <tr>
          <td>${escapeHtml(column.column_name)} ${keyBadge}</td>
          <td>${column.is_primary_key ? "Sim" : "Não"}</td>
          <td>${escapeHtml(column.data_type)}(${column.length}${
        column.decimals ? `,${column.decimals}` : ""
      })</td>
          <td class="description-cell">${escapeHtml(column.business_description)}${enumButton}</td>
          <td>${escapeHtml(column.domain_name || "-")}${checkTableTag}</td>
        </tr>`;
    })
    .join("");

  tbody.querySelectorAll(".enum-button").forEach((button) => {
    button.addEventListener("click", () => {
      const column = contract.columns[Number(button.dataset.columnIndex)];
      onShowEnum(column);
    });
  });

  tbody.querySelectorAll(".ref-table-tag").forEach((tag) => {
    tag.addEventListener("click", () => onNavigateToTable(tag.dataset.checkTable));
  });
}

/**
 * Populates and opens the fixed-values enum modal for a column.
 * @param {object} column - A column object with has_fixed_values/fixed_values_map.
 */
export function renderEnumModal(column) {
  const dialog = document.getElementById("enum-modal");
  document.getElementById("enum-modal-title").textContent =
    `Campo ${column.column_name} — Domínio ${column.domain_name || "(sem domínio)"}`;
  document.getElementById("enum-modal-source").textContent =
    `Fonte: tabela DD07T do SAP (textos de valores fixos do domínio ${column.domain_name || ""})`;

  const body = document.getElementById("enum-modal-body");
  const entries = Object.entries(column.fixed_values_map);
  body.innerHTML = entries
    .map(
      ([value, text]) =>
        `<dt>${escapeHtml(value === "" ? "(vazio)" : value)}</dt><dd>${escapeHtml(text)}</dd>`
    )
    .join("");

  dialog.showModal();
}

/**
 * Renders the textual listing of related tables.
 * @param {object} contract - The SAPTableMetadata contract.
 * @param {(tableName: string) => void} onNavigateToTable - Called when a table link is clicked.
 */
export function renderRelations(contract, onNavigateToTable) {
  const textTableVal = document.getElementById("text-table-info");
  const checkTablesList = document.getElementById("check-tables-list");

  // Render Associated Text Table
  if (contract.associated_text_table) {
    textTableVal.innerHTML = `<button class="ref-table-tag" data-check-table="${escapeHtml(
      contract.associated_text_table
    )}" title="Ver a tabela ${escapeHtml(contract.associated_text_table)}">🔗 ${escapeHtml(
      contract.associated_text_table
    )}</button> (tabela de textos que contém as descrições traduzidas dos códigos)`;
  } else {
    textTableVal.innerHTML = `<span class="relation-value-none">Nenhuma tabela de textos associada encontrada</span>`;
  }

  // Render Check Tables (Parent Tables)
  if (contract.parent_tables && contract.parent_tables.length > 0) {
    checkTablesList.innerHTML = contract.parent_tables
      .map((parent) => {
        const fkPairs = parent.foreign_key_fields
          .map((fk) => `${fk.child_field} ➔ ${fk.parent_field}`)
          .join(", ");
        const importanceClass = `legend-dot--${parent.importance.toLowerCase()}`;
        return `
          <div class="check-table-item" style="margin-bottom: 0.45rem;">
            <button class="ref-table-tag" data-check-table="${escapeHtml(
              parent.parent_table_name
            )}">🔗 ${escapeHtml(parent.parent_table_name)}</button>
            <span class="check-table-info" style="font-size: 0.78rem; color: var(--text-secondary);">
              (${parent.relationship_type} · <span class="legend-dot ${importanceClass}"></span> ${parent.importance})
              <span class="check-table-keys" style="color: var(--text-muted);">[${fkPairs}]</span>
            </span>
          </div>`;
      })
      .join("");
  } else {
    checkTablesList.innerHTML = `<span class="relation-value-none">Nenhuma tabela de verificação encontrada</span>`;
  }

  // Wire navigation clicks
  const allTags = [
    ...textTableVal.querySelectorAll(".ref-table-tag"),
    ...checkTablesList.querySelectorAll(".ref-table-tag")
  ];
  allTags.forEach((tag) => {
    tag.addEventListener("click", () => onNavigateToTable(tag.dataset.checkTable));
  });
}

