/**
 * Minimal shared application state.
 *
 * A plain mutable object is enough at this scale — no reactive framework is
 * needed for a single search box driving a handful of DOM regions.
 */
export const state = {
  currentTable: null,
  contract: null,
};
