/**
 * JSON contract viewer: syntax highlighting, clipboard copy and file download.
 */

/**
 * Renders a contract as syntax-highlighted JSON.
 * @param {object} contract - The SAPTableMetadata contract.
 */
export function renderJson(contract) {
  const code = document.getElementById("json-code");
  code.textContent = JSON.stringify(contract, null, 2);
  Prism.highlightElement(code);
}

/**
 * Wires up the copy and download buttons for the JSON viewer.
 * @param {() => object} getContract - Returns the currently displayed contract.
 */
export function initJsonToolbar(getContract) {
  const copyButton = document.getElementById("btn-copy");
  const downloadButton = document.getElementById("btn-download");

  copyButton.addEventListener("click", async () => {
    const json = JSON.stringify(getContract(), null, 2);
    await navigator.clipboard.writeText(json);
    const original = copyButton.textContent;
    copyButton.textContent = "Copiado!";
    setTimeout(() => {
      copyButton.textContent = original;
    }, 1500);
  });

  downloadButton.addEventListener("click", () => {
    const contract = getContract();
    const json = JSON.stringify(contract, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = url;
    link.download = `sap_schema_${contract.table_name}.json`;
    link.click();

    URL.revokeObjectURL(url);
  });
}
