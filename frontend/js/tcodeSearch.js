/**
 * "Transações" view: search SAP transaction codes (standard or customer-built)
 * and show their program, package and standard/custom classification.
 *
 * Self-contained screen module, same shape as dbtGenerator.js/martGenerator.js
 * — own search box (not the topbar's table search), own autocomplete list,
 * own detail rendering, wired up once via initTcodeSearch().
 */

import { getTransactionContract, searchTcodes } from "./api.js";

const tcodeInput = document.getElementById("tcode-search-input");
const btnSearch = document.getElementById("btn-tcode-search");
const searchLoading = document.getElementById("tcode-search-loading");
const autocompleteList = document.getElementById("tcode-autocomplete-list");
const warningsBox = document.getElementById("tcode-warnings");
const factsBox = document.getElementById("tcode-summary-facts");

const CLASSIFICATION_ACCENT = {
  Standard: "var(--cat-green)",
  Customizada: "var(--cat-orange)",
};

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

function renderAutocomplete(results) {
  if (results.length === 0) {
    autocompleteList.classList.add("hidden");
    autocompleteList.innerHTML = "";
    return;
  }

  autocompleteList.innerHTML = results
    .map(
      (row) => `
        <li class="autocomplete-item" data-tcode="${escapeHtml(row.tcode)}">
          <span class="table-name">${escapeHtml(row.tcode)}</span>
          <span class="table-desc">${escapeHtml(row.description)}</span>
        </li>`
    )
    .join("");
  autocompleteList.classList.remove("hidden");

  autocompleteList.querySelectorAll(".autocomplete-item").forEach((item) => {
    item.addEventListener("click", () => {
      tcodeInput.value = item.dataset.tcode;
      autocompleteList.classList.add("hidden");
      selectTcode(item.dataset.tcode);
    });
  });
}

function renderFacts(contract) {
  const items = [
    { label: "Transação", value: contract.tcode, accent: "var(--cat-blue)" },
    { label: "Descrição", value: contract.description, accent: "var(--cat-blue)" },
    { label: "Programa", value: contract.program_name || "-", accent: "var(--cat-violet)" },
    { label: "Pacote", value: contract.package || "-", accent: "var(--cat-violet)" },
    {
      label: "Classificação",
      value: contract.classification,
      accent: CLASSIFICATION_ACCENT[contract.classification],
    },
  ];

  factsBox.innerHTML = items
    .map(
      (item) => `
        <div class="fact-item">
          <span class="fact-dot" style="--accent: ${item.accent}"></span>
          <div>
            <p class="fact-label">${escapeHtml(item.label)}</p>
            <p class="fact-value">${escapeHtml(item.value)}</p>
          </div>
        </div>`
    )
    .join("");
  factsBox.classList.remove("hidden");
}

async function selectTcode(tcode) {
  clearMessage();
  try {
    const contract = await getTransactionContract(tcode);
    renderFacts(contract);
  } catch (error) {
    factsBox.classList.add("hidden");
    showMessage(error.message || "Erro ao buscar a transação.", true);
  }
}

async function performSearch() {
  const term = tcodeInput.value.trim();
  if (!term) return;

  clearMessage();
  renderAutocomplete([]);
  searchLoading.classList.remove("hidden");
  btnSearch.disabled = true;

  try {
    const results = await searchTcodes(term.toUpperCase());
    if (results.length === 1) {
      // A single hit (the common case — an exact/near-exact tcode) skips
      // the extra picklist step and goes straight to the detail view.
      await selectTcode(results[0].tcode);
    } else if (results.length === 0) {
      factsBox.classList.add("hidden");
      showMessage(`Nenhuma transação encontrada para "${term}".`, true);
    } else {
      renderAutocomplete(results);
    }
  } catch (error) {
    showMessage(error.message || "Erro ao buscar transações.", true);
  } finally {
    searchLoading.classList.add("hidden");
    btnSearch.disabled = false;
  }
}

export function initTcodeSearch() {
  btnSearch.addEventListener("click", performSearch);

  tcodeInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      performSearch();
    }
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest("#view-tcode")) {
      autocompleteList.classList.add("hidden");
    }
  });
}
