/**
 * search.js — Cross-table value search UI.
 * Debounced search input, results panel, click-to-pan.
 */

import { EventBus } from './events.js';
import * as State from './state.js';
import { escapeHtml } from './utils.js';

/** Emitted when user clicks trace on a search result */
export const TRACE_REQUEST_EVENT = 'traceRequested';

let debounceTimer = null;
let abortController = null;

export function initSearch() {
  const input = document.getElementById('search-input');
  if (!input) return;

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => handleSearch(input.value.trim()), 300);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      input.value = '';
      clearSearch();
    }
  });
}

async function handleSearch(query) {
  if (!query) {
    clearSearch();
    return;
  }

  if (abortController) abortController.abort();
  abortController = new AbortController();

  try {
    const response = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, mode: 'contains', scope: 'all' }),
      signal: abortController.signal,
    });
    const results = await response.json();
    State.setSearchResults(results);
    renderResults(results);
  } catch (err) {
    if (err.name !== 'AbortError') console.error('Search failed:', err);
  }
}

function clearSearch() {
  State.clearSearchResults();
  renderResults(null);
}

function renderResults(results) {
  const panel = document.getElementById('search-results');
  if (!panel) return;

  if (!results || !results.matches || results.matches.length === 0) {
    panel.innerHTML = '';
    panel.hidden = true;
    return;
  }

  panel.hidden = false;
  const grouped = groupByTable(results.matches);

  panel.innerHTML = Object.entries(grouped).map(([table, matches]) => `
    <div class="search-results__group">
      <div class="search-results__table-name">${escapeHtml(table)}</div>
      ${matches.slice(0, 10).map(m => `
        <div class="search-results__item" data-table="${escapeHtml(m.table)}" data-column="${escapeHtml(m.column)}" data-value="${escapeHtml(m.value)}">
          <span class="search-results__column">${escapeHtml(m.column)}</span>
          <span class="search-results__value">${escapeHtml(m.value)}</span>
          <button class="search-results__trace-btn" title="Trace this value across tables">&#x21CC;</button>
        </div>
      `).join('')}
    </div>
  `).join('');

  panel.querySelectorAll('.search-results__item').forEach(item => {
    item.addEventListener('click', (e) => {
      if (e.target.classList.contains('search-results__trace-btn')) return;
      EventBus.emit('panToTable', item.dataset.table);
    });
  });

  panel.querySelectorAll('.search-results__trace-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const item = btn.closest('.search-results__item');
      EventBus.emit(TRACE_REQUEST_EVENT, {
        table: item.dataset.table,
        column: item.dataset.column,
        value: item.dataset.value,
      });
    });
  });
}

function groupByTable(matches) {
  const groups = {};
  for (const m of matches) {
    if (!groups[m.table]) groups[m.table] = [];
    groups[m.table].push(m);
  }
  return groups;
}

