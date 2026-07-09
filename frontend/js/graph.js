/**
 * Lineage graph rendering via vis-network.
 *
 * The searched table is the emphasized node (accent color); parent and text
 * tables are context (neutral gray) — this is an "emphasis" composition, not
 * a categorical one, since there is exactly one entity the reader must find
 * first. Edges point FROM parent tables INTO the central table, and from the
 * central table INTO its text table, matching the relationship's real direction.
 *
 * A table like MARA can have 60+ check-table relationships. Each is ranked
 * Alta/Média/Baixa (see backend.heuristics.TableClassifier.
 * classify_relationship_importance): Alta is real business-entity data,
 * Média is a substantial Configuration-class lookup, Baixa is a small/tiny
 * one. By default only Alta+Média are shown; the caller can pass
 * `showAll: true` to reveal the Baixa tier too.
 */

let network = null;

// Two-digit hex alpha appended to a `#rrggbb` category color, used to tint a
// node's fill without a separate color-mix() computation per node.
function withAlpha(hexColor, alphaHex) {
  return `${hexColor}${alphaHex}`;
}

function importanceStyle(importance, { highAccent, mediumAccent, neutral, textPrimary }) {
  if (importance === "Alta") {
    return {
      border: highAccent,
      background: withAlpha(highAccent, "26"),
      fontColor: textPrimary,
      fontSize: 14,
      borderWidth: 2,
      dashes: false,
    };
  }
  if (importance === "Média") {
    return {
      border: mediumAccent,
      background: withAlpha(mediumAccent, "1f"),
      fontColor: textPrimary,
      fontSize: 13,
      borderWidth: 2,
      dashes: false,
    };
  }
  return {
    border: neutral,
    background: withAlpha(neutral, "14"),
    fontColor: neutral,
    fontSize: 12,
    borderWidth: 1,
    dashes: [3, 3],
  };
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Renders (or re-renders) the lineage graph for a table contract.
 * @param {object} contract - The SAPTableMetadata contract.
 * @param {{showAll?: boolean, onNodeClick?: (tableName: string) => void}} [options] -
 *   Pass `showAll: true` to include Baixa-importance parent tables (defaults
 *   to only Alta+Média), and `onNodeClick` to make related-table nodes
 *   navigable (called with the clicked table's name; not fired for the
 *   central/current table).
 */
export function renderLineageGraph(contract, options = {}) {
  const showAll = options.showAll ?? false;
  const onNodeClick = options.onNodeClick;
  const container = document.getElementById("canvas-linhagem");

  const accent = cssVar("--accent");
  const highAccent = cssVar("--cat-violet");
  const mediumAccent = cssVar("--cat-aqua");
  const neutral = cssVar("--text-muted");
  const textPrimary = cssVar("--text-primary");
  const surface = cssVar("--surface-2");
  const bgSolid = cssVar("--bg-solid") || "#040f06";

  const nodes = [
    {
      id: contract.table_name,
      label: contract.table_name,
      title: `${contract.table_name} — tabela atual`,
      color: { background: accent, border: accent, highlight: { background: accent, border: textPrimary } },
      font: { color: bgSolid, size: 16, bold: { color: bgSolid } },
      shape: "box",
      borderWidth: 2,
      shapeProperties: { borderRadius: 2 },
      margin: 12,
    },
  ];
  const edges = [];

  if (contract.associated_text_table) {
    nodes.push({
      id: contract.associated_text_table,
      label: contract.associated_text_table,
      title: `${contract.associated_text_table} — tabela de texto · clique para abrir`,
      color: {
        background: withAlpha(textAccent, "1f"),
        border: textAccent,
        highlight: { background: withAlpha(textAccent, "33"), border: textAccent },
      },
      font: { color: textPrimary, size: 13 },
      shape: "box",
      borderWidth: 2,
      shapeProperties: { borderRadius: 2 },
      margin: 10,
    });
    edges.push({
      from: contract.table_name,
      to: contract.associated_text_table,
      arrows: "to",
      color: { color: textAccent, highlight: textAccent },
      label: "texto",
      width: 1.5,
    });
  }

  const parents = showAll
    ? contract.parent_tables
    : contract.parent_tables.filter((p) => p.importance !== "Baixa");

  parents.forEach((parent) => {
    const style = importanceStyle(parent.importance, { highAccent, mediumAccent, neutral, textPrimary });
    if (!nodes.some((n) => n.id === parent.parent_table_name)) {
      const fkPairs = parent.foreign_key_fields
        .map((fk) => `${fk.child_field} → ${fk.parent_field}`)
        .join(", ");
      nodes.push({
        id: parent.parent_table_name,
        label: parent.parent_table_name,
        title: `${parent.parent_table_name} — ${parent.relationship_type} (importância ${parent.importance})\n${fkPairs}\nClique para abrir`,
        color: {
          background: style.background,
          border: style.border,
          highlight: { background: withAlpha(style.border, "40"), border: style.border },
        },
        font: { color: style.fontColor, size: style.fontSize },
        shape: "box",
        borderWidth: style.borderWidth,
        shapeProperties: { borderDashes: style.dashes, borderRadius: 2 },
        margin: 10,
      });
    }
    edges.push({
      from: parent.parent_table_name,
      to: contract.table_name,
      arrows: "to",
      color: { color: withAlpha(style.border, "99"), highlight: style.border },
      label: parent.relationship_type,
      width: style.borderWidth,
    });
  });

  if (network) {
    network.destroy();
  }

  network = new vis.Network(
    container,
    { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) },
    {
      layout: { hierarchical: false },
      physics: { stabilization: true, barnesHut: { gravitationalConstant: -5500, springLength: 160 } },
      edges: {
        font: { size: 11, color: neutral, strokeWidth: 4, strokeColor: surface, align: "middle" },
        smooth: { type: "continuous", roundness: 0.4 },
        selectionWidth: 1.5,
      },
      nodes: { font: { size: 14, face: "ui-monospace, monospace" }, shadow: { enabled: true, size: 8, x: 0, y: 2, color: "rgba(0,0,0,0.35)" } },
      interaction: { hover: true },
    }
  );

  network.on("click", (params) => {
    if (params.nodes.length === 0) return;
    const nodeId = params.nodes[0];
    if (nodeId === contract.table_name) return;
    onNodeClick?.(nodeId);
  });

  network.on("hoverNode", (params) => {
    container.style.cursor = params.node === contract.table_name ? "default" : "pointer";
  });

  network.on("blurNode", () => {
    container.style.cursor = "default";
  });
}
