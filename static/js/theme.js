/**
 * theme.js — Dark/light theme toggle.
 * Manages body.dark class, swaps canvas color constants,
 * persists preference to localStorage, and emits themeChanged.
 */

import { EventBus } from './events.js';
import { applyTheme } from './constants.js';

const STORAGE_KEY = 'db-diagram-theme';

let isDark = false;

export function initTheme() {
  const saved = localStorage.getItem(STORAGE_KEY);
  isDark = saved === 'dark';
  apply();
  wireToggle();
}

export function toggleTheme() {
  isDark = !isDark;
  apply();
}

export function getIsDark() {
  return isDark;
}

function apply() {
  document.body.classList.toggle('dark', isDark);
  applyTheme(isDark);
  localStorage.setItem(STORAGE_KEY, isDark ? 'dark' : 'light');
  EventBus.emit('themeChanged', isDark);
}

function wireToggle() {
  const btn = document.getElementById('btn-theme');
  if (!btn) return;
  btn.addEventListener('click', toggleTheme);
}
