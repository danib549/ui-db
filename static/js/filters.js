/**
 * filters.js — Interactive filter panel for key types, relationship types, and tables.
 * Filters update state.activeFilters, triggering connection/block re-rendering.
 */

import { EventBus } from './events.js';
import * as State from './state.js';

let dimMode = true; // true = dim filtered-out elements, false = hide them

export function initFilters() {
  EventBus.on('tableAdded', rebuildFilterPanel);
  EventBus.on('tableRemoved', rebuildFilterPanel);
  EventBus.on('stateReset', rebuildFilterPanel);

  const toggleBtn = document.getElementById('btn-filter-toggle');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', toggleFilterPanel);
  }

  rebuildFilterPanel();
}

function toggleFilterPanel() {
  const section = document.querySelector('.sidebar__section--filters');
  if (!section) return;
  section.classList.toggle('sidebar__section--collapsed');
}

function rebuildFilterPanel() {
  const panel = document.getElementById('filter-panel');
  if (!panel) return;

  const state = State.getStateRef();
  const tables = state.tables;
  const connections = state.connections;

  const keyTypes = extractKeyTypes(tables);
  const relTypes = extractRelTypes(connections);

  panel.innerHTML = `
    ${renderFilterGroup('Key Types', keyTypes, 'key')}
    ${renderFilterGroup('Relationships', relTypes, 'rel')}
    ${renderTableGroup(tables)}
    ${renderControls()}
  `;

  wireFilterEvents(panel);
}

function extractKeyTypes(tables) {
  const types = new Set();
  for (const t of tables) {
    for (const c of t.columns) {
      if (c.key_type) types.add(c.key_type);
    }
  }
  return [...types];
}

function extractRelTypes(connections) {
  const types = new Set();
  for (const c of connections) {
    if (c.type) types.add(c.type);
  }
  return [...types];
}

function renderFilterGroup(title, items, prefix) {
  if (items.length === 0) return '';
  const checkboxes = items.map(item => `
    <label class="filter-panel__checkbox">
      <input type="checkbox" data-filter-type="${prefix}" data-filter-value="${item}" checked>
      <span>${item}</span>
    </label>
  `).join('');
  return `<div class="filter-panel__group">
    <div class="filter-panel__group-title">${title}</div>
    ${checkboxes}
  </div>`;
}

function renderTableGroup(tables) {
  if (tables.length === 0) return '';
  const checkboxes = tables.map(t => `
    <label class="filter-panel__checkbox">
      <input type="checkbox" data-filter-type="table" data-filter-value="${t.name}" checked>
      <span>${t.name}</span>
    </label>
  `).join('');
  return `<div class="filter-panel__group">
    <div class="filter-panel__group-title">Tables</div>
    ${checkboxes}
  </div>`;
}

function renderControls() {
  return `
    <div class="filter-panel__controls">
      <label class="filter-panel__checkbox">
        <input type="checkbox" id="filter-dim-toggle" ${dimMode ? 'checked' : ''}>
        <span>Dim (uncheck to hide)</span>
      </label>
      <button class="toolbar__btn filter-panel__clear" id="btn-clear-filters">Clear All</button>
    </div>
  `;
}

function wireFilterEvents(panel) {
  panel.querySelectorAll('input[data-filter-type]').forEach(cb => {
    cb.addEventListener('change', () => applyCurrentFilters(panel));
  });

  const dimToggle = document.getElementById('filter-dim-toggle');
  if (dimToggle) {
    dimToggle.addEventListener('change', (e) => {
      dimMode = e.target.checked;
      applyCurrentFilters(panel);
    });
  }

  const clearBtn = document.getElementById('btn-clear-filters');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      panel.querySelectorAll('input[data-filter-type]').forEach(cb => { cb.checked = true; });
      State.clearFilters();
    });
  }
}

function applyCurrentFilters(panel) {
  const unchecked = [...panel.querySelectorAll('input[data-filter-type]:not(:checked)')];

  if (unchecked.length === 0) {
    State.clearFilters();
    return;
  }

  const filters = unchecked.map(cb => ({
    type: cb.dataset.filterType,
    value: cb.dataset.filterValue,
    mode: dimMode ? 'dim' : 'hide',
  }));

  State.setActiveFilters(filters);
}
