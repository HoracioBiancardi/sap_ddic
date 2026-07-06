/**
 * Tab switching for the analytical section (Dicionário / Linhagem / Contrato JSON).
 *
 * Plain class toggling — no framework needed for three mutually-exclusive panels.
 */

/**
 * Wires up click listeners on all `.tab-button` elements.
 * @param {(tabName: string) => void} [onActivate] - Optional callback fired
 *   with the tab's data-tab value whenever it becomes active (used to
 *   lazily render the lineage graph only once it becomes visible).
 */
export function initTabs(onActivate) {
  const buttons = document.querySelectorAll(".tab-button");

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.tab;

      buttons.forEach((b) => b.classList.toggle("active", b === button));
      document.querySelectorAll(".tab-content").forEach((panel) => {
        panel.classList.toggle("hidden", panel.id !== `tab-${target}`);
      });

      if (onActivate) {
        onActivate(target);
      }
    });
  });
}
