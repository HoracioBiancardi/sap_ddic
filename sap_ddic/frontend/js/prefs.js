/**
 * Persists the chosen UI theme (corporate / green-neutral / cyber-dark, see
 * css/theme.css) in localStorage and applies it to `<body class>` on boot.
 */

const THEME_KEY = "ui_theme";
const DEFAULT_THEME = "cyber-dark";

/**
 * Reads the persisted theme name, falling back to the default.
 * @returns {string}
 */
export function getTheme() {
  return localStorage.getItem(THEME_KEY) || DEFAULT_THEME;
}

/**
 * Persists and applies a theme by name.
 * @param {string} theme - One of "corporate" | "green-neutral" | "cyber-dark".
 */
export function setTheme(theme) {
  localStorage.setItem(THEME_KEY, theme);
  document.body.className = `theme-${theme}`;
}

/**
 * Applies the persisted theme to `<body>`. Called once at boot.
 */
export function applyPrefsOnBoot() {
  document.body.className = `theme-${getTheme()}`;
}
