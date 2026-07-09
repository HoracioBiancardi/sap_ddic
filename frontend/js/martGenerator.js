/**
 * "Fato/Dimensão" view: a visual canvas where tables are boxes and joins are
 * lines between them — not a checklist tied to one base table's own
 * declared parents. Real DD08L foreign keys are detected and wired
 * automatically when possible; relationships DDIC doesn't model as a formal
 * FK (SAP document-flow chains through VBFA, or VGBEL/VGPOS "reference
 * document" fields on LIPS/VBRP) are wired by hand via a small modal.
 *
 * The same underlying SAP table can appear as two independent boxes with
 * two independent roles (e.g. KNA1 once as "sold-to", once as "payer") —
 * each box has its own `node_id` (defaults to the table name, suffixed on
 * collision) which is what identifies it on the canvas and becomes its SQL
 * alias, kept distinct from its `table_name` (see backend/mart_generator.py
 * for why).
 *
 * Generation only fires on an explicit "Gerar Fato/Dimensão" click — never
 * automatically — since building the graph may need a fresh contract fetch
 * per newly added table.
 */

import { generateMart, getTable, searchTables } from "./api.js";

const addInput = document.getElementById("mart-add-input");
const addAutocomplete = document.getElementById("mart-add-autocomplete");
const btnAdd = document.getElementById("btn-mart-add");
const canvasContainer = document.getElementById("canvas-mart");
const martTypeSelect = document.getElementById("mart-type");
const schemaInput = document.getElementById("mart-schema");
const warningsBox = document.getElementById("mart-warnings");
const loadingCard = document.getElementById("mart-loading");
const outputBox = document.getElementById("mart-output");
const ymlCode = document.getElementById("mart-yml-code");
const sqlCode = document.getElementById("mart-sql-code");
const docOutputBox = document.getElementById("mart-doc-output");
const docCode = document.getElementById("mart-doc-code");
const mermaidContainer = document.getElementById("mart-mermaid");

const joinModal = document.getElementById("mart-join-modal");
const joinModalTitle = document.getElementById("mart-join-modal-title");
const joinCandidatesBox = document.getElementById("mart-join-candidates");
const joinCandidatesList = document.getElementById("mart-join-candidates-list");
const joinFieldsContainer = document.getElementById("mart-join-fields");
const btnAddPair = document.getElementById("btn-mart-join-add-pair");
const joinFiltersContainer = document.getElementById("mart-join-filters");
const btnJoinRemove = document.getElementById("btn-mart-join-remove");
const btnJoinCancel = document.getElementById("btn-mart-join-cancel");
const btnJoinSave = document.getElementById("btn-mart-join-save");

// canvasNodes: Map<nodeId, {nodeId, tableName, contract}>
let canvasNodes = new Map();
// canvasJoins: {leftNode, rightNode, fields: [{left_field,right_field}], leftFilter, rightFilter, autoDetected}[]
let canvasJoins = [];
let rootNodeId = null;

let network = null;
let nodesDataSet = null;
let edgesDataSet = null;
let pendingSourceNodeId = null;

let modalLeftNodeId = null;
let modalRightNodeId = null;
let editingJoinIndex = null;
let modalCandidateSelected = false;

let lastArtifacts = null;
let mermaidRenderSeq = 0;
let mermaidReady = false;

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showMessage(text, isError) {
  warningsBox.textContent = text;
  warningsBox.classList.remove("hidden");
  warningsBox.classList.toggle("dbt-warnings--error", isError);
}

function clearMessage() {
  warningsBox.classList.add("hidden");
  warningsBox.classList.remove("dbt-warnings--error");
}

/**
 * Splits a ParentTable's flat foreign_key_fields list back into its
 * independent composite-key groups — mirrors backend.mart_generator's
 * _split_fk_groups exactly (see there for why: a table with *multiple
 * independent* FKs to the same checktable, e.g. MARA's five
 * self-referencing generic-material fields, gets all of their pairs
 * flattened into one list by the DDIC extraction; ANDing them all together
 * would be wrong).
 */
function splitFkGroups(fields) {
  if (!fields || fields.length === 0) return [];
  const anchor = fields[0].parent_field;
  const groups = [];
  fields.forEach((fk) => {
    if (fk.parent_field === anchor) {
      groups.push([fk]);
    } else {
      groups[groups.length - 1].push(fk);
    }
  });
  return groups;
}

/**
 * Finds every real DD08L FK relationship between two table contracts,
 * checked in both directions, expressed as `{fields: [{left_field,
 * right_field}]}` where `left_field` belongs to `leftContract` and
 * `right_field` to `rightContract`.
 */
function findCandidateGroups(leftContract, rightContract) {
  const candidates = [];
  (leftContract.parent_tables || []).forEach((parent) => {
    if (parent.parent_table_name === rightContract.table_name) {
      splitFkGroups(parent.foreign_key_fields).forEach((group) => {
        candidates.push({ fields: group.map((fk) => ({ left_field: fk.child_field, right_field: fk.parent_field })) });
      });
    }
  });
  (rightContract.parent_tables || []).forEach((parent) => {
    if (parent.parent_table_name === leftContract.table_name) {
      splitFkGroups(parent.foreign_key_fields).forEach((group) => {
        candidates.push({ fields: group.map((fk) => ({ left_field: fk.parent_field, right_field: fk.child_field })) });
      });
    }
  });
  return candidates;
}

function uniqueNodeId(tableName) {
  if (!canvasNodes.has(tableName)) return tableName;
  let suffix = 2;
  while (canvasNodes.has(`${tableName}_${suffix}`)) suffix += 1;
  return `${tableName}_${suffix}`;
}

// ---- Canvas rendering ----

function nodeToVisNode(info) {
  const isRoot = info.nodeId === rootNodeId;
  const isPending = info.nodeId === pendingSourceNodeId;
  return {
    id: info.nodeId,
    label: info.nodeId === info.tableName ? info.nodeId : `${info.nodeId}\n(${info.tableName})`,
    title: isRoot ? `${info.nodeId} — tabela raiz (FROM)` : info.nodeId,
    shape: "box",
    shapeProperties: { borderRadius: 8 },
    margin: 12,
    borderWidth: isRoot ? 3 : isPending ? 3 : 1,
    color: {
      background: isRoot ? cssVar("--accent") : cssVar("--surface-2"),
      border: isPending ? cssVar("--accent") : isRoot ? cssVar("--accent") : cssVar("--cat-blue"),
    },
    font: { color: isRoot ? "#04120a" : cssVar("--text-primary"), size: 14, face: "ui-monospace, monospace" },
  };
}

function joinToVisEdge(join, index) {
  return {
    id: index,
    from: join.leftNode,
    to: join.rightNode,
    arrows: "to",
    dashes: !join.autoDetected,
    color: { color: cssVar("--text-muted") },
    label: join.fields.map((f) => `${f.left_field}=${f.right_field}`).join(", "),
    font: { size: 10, color: cssVar("--text-muted"), strokeWidth: 4, strokeColor: cssVar("--surface-1") },
  };
}

function ensureNetwork() {
  if (network) return;
  nodesDataSet = new vis.DataSet([]);
  edgesDataSet = new vis.DataSet([]);
  network = new vis.Network(
    canvasContainer,
    { nodes: nodesDataSet, edges: edgesDataSet },
    {
      physics: { stabilization: true, barnesHut: { gravitationalConstant: -4500, springLength: 150 } },
      // zoomView: false keeps mouse-wheel scrolling on the page working
      // normally over the canvas — with it on (vis-network's default), the
      // wheel zooms the graph instead of scrolling past it to the yml/SQL/
      // documentation panels below, which is exactly what look like "no
      // scroll" from the outside.
      interaction: { hover: true, zoomView: false },
      edges: { smooth: { type: "continuous", roundness: 0.4 } },
    }
  );
  network.on("click", handleCanvasClick);
  network.on("doubleClick", handleCanvasDoubleClick);
}

function syncCanvas() {
  ensureNetwork();
  nodesDataSet.clear();
  nodesDataSet.add(Array.from(canvasNodes.values()).map(nodeToVisNode));
  edgesDataSet.clear();
  edgesDataSet.add(canvasJoins.map(joinToVisEdge));
}

function handleCanvasClick(params) {
  if (params.nodes.length > 0) {
    const clickedId = params.nodes[0];
    if (!pendingSourceNodeId) {
      pendingSourceNodeId = clickedId;
      syncCanvas();
      return;
    }
    if (pendingSourceNodeId === clickedId) {
      pendingSourceNodeId = null;
      syncCanvas();
      return;
    }
    const source = pendingSourceNodeId;
    pendingSourceNodeId = null;
    syncCanvas();
    const existingIndex = canvasJoins.findIndex(
      (j) => (j.leftNode === source && j.rightNode === clickedId) || (j.leftNode === clickedId && j.rightNode === source)
    );
    if (existingIndex >= 0) {
      const join = canvasJoins[existingIndex];
      openJoinModal(join.leftNode, join.rightNode, existingIndex);
    } else {
      openJoinModal(source, clickedId, null);
    }
    return;
  }
  if (params.edges.length > 0) {
    const edgeIndex = Number(params.edges[0]);
    const join = canvasJoins[edgeIndex];
    openJoinModal(join.leftNode, join.rightNode, edgeIndex);
    return;
  }
  if (pendingSourceNodeId) {
    pendingSourceNodeId = null;
    syncCanvas();
  }
}

function handleCanvasDoubleClick(params) {
  if (params.nodes.length > 0) {
    removeNode(params.nodes[0]);
    return;
  }
  if (params.edges.length > 0) {
    removeJoin(Number(params.edges[0]));
  }
}

function removeNode(nodeId) {
  pendingSourceNodeId = null;
  canvasNodes.delete(nodeId);
  canvasJoins = canvasJoins.filter((j) => j.leftNode !== nodeId && j.rightNode !== nodeId);
  if (rootNodeId === nodeId) {
    const next = canvasNodes.keys().next();
    rootNodeId = next.done ? null : next.value;
  }
  syncCanvas();
}

function removeJoin(index) {
  pendingSourceNodeId = null;
  canvasJoins.splice(index, 1);
  syncCanvas();
}

// ---- Adding a table ----

async function addTableToCanvas(tableName) {
  const contract = await getTable(tableName);
  const nodeId = uniqueNodeId(contract.table_name);
  canvasNodes.set(nodeId, { nodeId, tableName: contract.table_name, contract });
  if (!rootNodeId) {
    rootNodeId = nodeId;
    martTypeSelect.value = contract.table_type === "Transactional" ? "FCT" : "DIM";
  }

  const allCandidates = [];
  canvasNodes.forEach((other) => {
    if (other.nodeId === nodeId) return;
    findCandidateGroups(other.contract, contract).forEach((candidate) => {
      allCandidates.push({ leftNode: other.nodeId, rightNode: nodeId, fields: candidate.fields });
    });
  });
  if (allCandidates.length === 1) {
    const candidate = allCandidates[0];
    canvasJoins.push({
      leftNode: candidate.leftNode,
      rightNode: candidate.rightNode,
      fields: candidate.fields,
      leftFilter: null,
      rightFilter: null,
      autoDetected: true,
    });
  }

  syncCanvas();
}

function renderAddAutocomplete(results) {
  if (results.length === 0) {
    addAutocomplete.classList.add("hidden");
    addAutocomplete.innerHTML = "";
    return;
  }
  addAutocomplete.innerHTML = results
    .map(
      (row) => `
        <li class="autocomplete-item" data-table-name="${row.table_name}">
          <span class="table-name">${row.table_name}</span>
          <span class="table-desc">${row.description}</span>
        </li>`
    )
    .join("");
  addAutocomplete.classList.remove("hidden");

  addAutocomplete.querySelectorAll(".autocomplete-item").forEach((item) => {
    item.addEventListener("click", async () => {
      addAutocomplete.classList.add("hidden");
      addInput.value = "";
      try {
        await addTableToCanvas(item.dataset.tableName);
      } catch (error) {
        showMessage(error.message || "Erro ao adicionar tabela.", true);
      }
    });
  });
}

/**
 * Adds a table to the canvas. Tries the typed text as an exact technical
 * table name first (the common case — SAP table names are short and
 * usually already known, e.g. "VBAP"), so most adds skip the extra
 * search-then-click step entirely; only falls back to the fuzzy
 * name/description search (with a picklist) when that exact lookup fails.
 */
async function performAdd() {
  const term = addInput.value.trim();
  if (!term) return;

  clearMessage();
  addAutocomplete.classList.add("hidden");

  try {
    await addTableToCanvas(term.toUpperCase());
    addInput.value = "";
    return;
  } catch (directError) {
    // Not an exact/known table name — fall through to fuzzy search below.
  }

  try {
    const results = await searchTables(term);
    if (results.length === 0) {
      showMessage(`Nenhuma tabela encontrada para "${term}".`, true);
    }
    renderAddAutocomplete(results);
  } catch (error) {
    showMessage(error.message || "Erro ao buscar tabelas.", true);
  }
}

// ---- Join modal ----

function fieldOptionsHtml(contract, selectedField) {
  return contract.columns
    .map((c) => `<option value="${c.column_name}" ${c.column_name === selectedField ? "selected" : ""}>${c.column_name}</option>`)
    .join("");
}

function renderFieldPairRow(leftContract, rightContract, pair) {
  const row = document.createElement("div");
  row.className = "mart-join-field-row";
  row.innerHTML = `
    <select class="mart-join-left-field">${fieldOptionsHtml(leftContract, pair?.left_field)}</select>
    <span class="join-eq">=</span>
    <select class="mart-join-right-field">${fieldOptionsHtml(rightContract, pair?.right_field)}</select>
    <button type="button" class="btn-remove-pair" title="Remover par">✕</button>
  `;
  row.querySelectorAll("select").forEach((select) => {
    select.addEventListener("change", () => {
      modalCandidateSelected = false;
    });
  });
  row.querySelector(".btn-remove-pair").addEventListener("click", () => {
    if (joinFieldsContainer.children.length > 1) {
      row.remove();
      modalCandidateSelected = false;
    }
  });
  return row;
}

function setFieldRows(leftContract, rightContract, fields) {
  joinFieldsContainer.innerHTML = "";
  fields.forEach((pair) => joinFieldsContainer.appendChild(renderFieldPairRow(leftContract, rightContract, pair)));
}

function buildFilterBlock(nodeId, contract, filter) {
  const wrap = document.createElement("div");
  wrap.className = "mart-join-filter-block";
  wrap.innerHTML = `
    <p class="mart-join-section-label" style="margin-top:0">Filtro extra (opcional) — ${escapeHtml(nodeId)}</p>
    <div class="mart-join-filter-row">
      <select class="mart-join-filter-field">
        <option value="">(nenhum)</option>
        ${fieldOptionsHtml(contract, filter?.field)}
      </select>
      <select class="mart-join-filter-op">
        <option value="=">=</option>
        <option value="!=">!=</option>
      </select>
      <input type="text" class="mart-join-filter-value" placeholder="valor" value="${filter?.value ? escapeHtml(filter.value) : ""}" />
    </div>
  `;
  if (filter?.operator) {
    wrap.querySelector(".mart-join-filter-op").value = filter.operator;
  }
  return wrap;
}

function readFilterBlock(block) {
  const field = block.querySelector(".mart-join-filter-field").value;
  if (!field) return null;
  const operator = block.querySelector(".mart-join-filter-op").value;
  const value = block.querySelector(".mart-join-filter-value").value.trim();
  return { field, operator, value };
}

function readFieldPairs() {
  return Array.from(joinFieldsContainer.querySelectorAll(".mart-join-field-row")).map((row) => ({
    left_field: row.querySelector(".mart-join-left-field").value,
    right_field: row.querySelector(".mart-join-right-field").value,
  }));
}

function openJoinModal(leftNodeId, rightNodeId, editingIndex) {
  modalLeftNodeId = leftNodeId;
  modalRightNodeId = rightNodeId;
  editingJoinIndex = editingIndex;
  modalCandidateSelected = false;

  const leftInfo = canvasNodes.get(leftNodeId);
  const rightInfo = canvasNodes.get(rightNodeId);
  const existingJoin = editingIndex !== null ? canvasJoins[editingIndex] : null;

  joinModalTitle.textContent = `Ligar ${leftNodeId} — ${rightNodeId}`;

  const candidates = findCandidateGroups(leftInfo.contract, rightInfo.contract);
  if (candidates.length > 0) {
    joinCandidatesBox.classList.remove("hidden");
    joinCandidatesList.innerHTML = candidates
      .map(
        (candidate, index) => `
          <li>
            <button type="button" class="mart-join-candidate-button" data-candidate-index="${index}">
              ${candidate.fields.map((f) => `${leftNodeId}.${f.left_field} = ${rightNodeId}.${f.right_field}`).join(" AND ")}
            </button>
          </li>`
      )
      .join("");
    joinCandidatesList.querySelectorAll(".mart-join-candidate-button").forEach((button) => {
      button.addEventListener("click", () => {
        const candidate = candidates[Number(button.dataset.candidateIndex)];
        setFieldRows(leftInfo.contract, rightInfo.contract, candidate.fields);
        modalCandidateSelected = true;
      });
    });
  } else {
    joinCandidatesBox.classList.add("hidden");
    joinCandidatesList.innerHTML = "";
  }

  const initialFields = existingJoin ? existingJoin.fields : [{ left_field: "", right_field: "" }];
  setFieldRows(leftInfo.contract, rightInfo.contract, initialFields);
  if (existingJoin) modalCandidateSelected = existingJoin.autoDetected;

  joinFiltersContainer.innerHTML = "";
  joinFiltersContainer.appendChild(buildFilterBlock(leftNodeId, leftInfo.contract, existingJoin?.leftFilter));
  joinFiltersContainer.appendChild(buildFilterBlock(rightNodeId, rightInfo.contract, existingJoin?.rightFilter));

  btnJoinRemove.classList.toggle("hidden", editingIndex === null);

  joinModal.showModal();
}

btnAddPair.addEventListener("click", () => {
  const leftInfo = canvasNodes.get(modalLeftNodeId);
  const rightInfo = canvasNodes.get(modalRightNodeId);
  joinFieldsContainer.appendChild(renderFieldPairRow(leftInfo.contract, rightInfo.contract, null));
  modalCandidateSelected = false;
});

btnJoinCancel.addEventListener("click", () => {
  joinModal.close();
});

btnJoinRemove.addEventListener("click", () => {
  if (editingJoinIndex !== null) {
    canvasJoins.splice(editingJoinIndex, 1);
  }
  joinModal.close();
  syncCanvas();
});

btnJoinSave.addEventListener("click", () => {
  const fields = readFieldPairs().filter((pair) => pair.left_field && pair.right_field);
  if (fields.length === 0) return;

  const join = {
    leftNode: modalLeftNodeId,
    rightNode: modalRightNodeId,
    fields,
    leftFilter: readFilterBlock(joinFiltersContainer.children[0]),
    rightFilter: readFilterBlock(joinFiltersContainer.children[1]),
    autoDetected: modalCandidateSelected,
  };

  if (editingJoinIndex !== null) {
    canvasJoins[editingJoinIndex] = join;
  } else {
    canvasJoins.push(join);
  }

  joinModal.close();
  syncCanvas();
});

// ---- Generation ----

function ensureMermaidInitialized() {
  if (mermaidReady || typeof mermaid === "undefined") return;
  mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
  mermaidReady = true;
}

async function renderMermaid(documentation) {
  const match = documentation.match(/```mermaid\n([\s\S]*?)```/);
  if (!match) {
    mermaidContainer.innerHTML = "";
    return;
  }
  ensureMermaidInitialized();
  try {
    const { svg } = await mermaid.render(`mart-mermaid-${++mermaidRenderSeq}`, match[1]);
    mermaidContainer.innerHTML = svg;
  } catch (error) {
    mermaidContainer.innerHTML = '<p class="mermaid-error">Não foi possível renderizar o diagrama de linhagem.</p>';
  }
}

function renderArtifacts(artifacts) {
  lastArtifacts = artifacts;
  martTypeSelect.value = artifacts.mart_type;
  schemaInput.value = artifacts.dbt_schema;

  if (artifacts.warnings.length > 0) {
    showMessage(artifacts.warnings.join(" "), false);
  } else {
    clearMessage();
  }

  ymlCode.textContent = artifacts.yml;
  Prism.highlightElement(ymlCode);
  sqlCode.textContent = artifacts.sql;
  Prism.highlightElement(sqlCode);
  docCode.textContent = artifacts.documentation;
  Prism.highlightElement(docCode);

  outputBox.classList.remove("hidden");
  docOutputBox.classList.remove("hidden");
  renderMermaid(artifacts.documentation);
}

async function generate() {
  if (!rootNodeId || canvasNodes.size === 0) {
    showMessage("Adicione ao menos uma tabela ao canvas antes de gerar.", true);
    return;
  }

  loadingCard.classList.remove("hidden");
  outputBox.classList.add("hidden");
  docOutputBox.classList.add("hidden");
  clearMessage();

  const payload = {
    tables: Array.from(canvasNodes.values()).map((n) => ({ node_id: n.nodeId, table_name: n.tableName })),
    root_node: rootNodeId,
    joins: canvasJoins.map((j) => ({
      left_node: j.leftNode,
      right_node: j.rightNode,
      fields: j.fields,
      left_filter: j.leftFilter,
      right_filter: j.rightFilter,
      auto_detected: j.autoDetected,
    })),
    mart_type: martTypeSelect.value,
    dbt_schema: schemaInput.value.trim() || null,
  };

  try {
    const artifacts = await generateMart(payload);
    renderArtifacts(artifacts);
  } catch (error) {
    showMessage(error.message || "Erro ao gerar o modelo de fato/dimensão.", true);
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
 * Clears the canvas and output. The canvas is never cleared automatically
 * by navigating elsewhere in the app (see the "Limpar canvas" button this
 * is wired to) — only this explicit user action starts a fresh workbench.
 */
function clearCanvas() {
  canvasNodes = new Map();
  canvasJoins = [];
  rootNodeId = null;
  pendingSourceNodeId = null;
  if (nodesDataSet) nodesDataSet.clear();
  if (edgesDataSet) edgesDataSet.clear();
  lastArtifacts = null;
  outputBox.classList.add("hidden");
  docOutputBox.classList.add("hidden");
  mermaidContainer.innerHTML = "";
  addInput.value = "";
  addAutocomplete.classList.add("hidden");
  clearMessage();
}

/**
 * Wires up the add-table search, the "Gerar Fato/Dimensão" button and the
 * copy/download buttons for the yml, SQL and documentation artifacts. Call
 * once at startup.
 */
export function initMartGenerator() {
  btnAdd.addEventListener("click", performAdd);
  addInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") performAdd();
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".mart-add-table")) {
      addAutocomplete.classList.add("hidden");
    }
  });

  document.getElementById("btn-generate-mart").addEventListener("click", generate);
  document.getElementById("btn-mart-clear").addEventListener("click", clearCanvas);

  document
    .getElementById("btn-copy-mart-yml")
    .addEventListener("click", () => copyToClipboard("btn-copy-mart-yml", lastArtifacts?.yml || ""));
  document
    .getElementById("btn-copy-mart-sql")
    .addEventListener("click", () => copyToClipboard("btn-copy-mart-sql", lastArtifacts?.sql || ""));
  document
    .getElementById("btn-copy-mart-doc")
    .addEventListener("click", () => copyToClipboard("btn-copy-mart-doc", lastArtifacts?.documentation || ""));

  document.getElementById("btn-download-mart-yml").addEventListener("click", () => {
    downloadFile(`${lastArtifacts?.model_name || "mart"}.yml`, lastArtifacts?.yml || "", "text/yaml");
  });
  document.getElementById("btn-download-mart-sql").addEventListener("click", () => {
    downloadFile(`${lastArtifacts?.model_name || "mart"}.sql`, lastArtifacts?.sql || "", "text/plain");
  });
  document.getElementById("btn-download-mart-doc").addEventListener("click", () => {
    downloadFile(`${lastArtifacts?.model_name || "mart"}.md`, lastArtifacts?.documentation || "", "text/markdown");
  });
}
