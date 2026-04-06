/**
 * utils.js — Shared utility functions.
 */

const _escDiv = document.createElement('div');

/** Escape a string for safe HTML insertion. */
export function escapeHtml(str) {
  _escDiv.textContent = String(str);
  return _escDiv.innerHTML;
}
