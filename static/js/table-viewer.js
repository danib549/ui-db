/**
 * table-viewer.js — Modal popup showing table data in an Excel-like grid.
 * Clicking a cell value triggers a trace across FK relationships.
 * Pure DOM module — no canvas interaction, no state mutations.
 */

import { EventBus } from './events.js';
import * as State from './state.js';
import { escapeHtml as esc } from './utils.js';

let modalEl = null;

export function initTableViewer() {
  EventBus.on('openTableViewer', openViewer);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeViewer();
  });
}

async function openViewer(tableName) {
  closeViewer();

  const table = State.getTables().find((t) => t.name === tableName);
  if (!table) return;

  // Build modal shell immediately with loading state
  modalEl = document.createElement('div');
  modalEl.className = 'table-viewer';
  modalEl.innerHTML = `
    <div class="table-viewer__backdrop"></div>
    <div class="table-viewer__dialog">
      <div class="table-viewer__header">
        <span class="table-viewer__title">${esc(tableName)}</span>
        <button class="table-viewer__close">&times;</button>
      </div>
      <div class="table-viewer__grid">
        <div class="table-viewer__loading">Loading data...</div>
      </div>
    </div>
  `;
  document.body.appendChild(modalEl);

  modalEl.querySelector('.table-viewer__backdrop').addEventListener('click', closeViewer);
  modalEl.querySelector('.table-viewer__close').addEventListener('click', closeViewer);

  try {
    const params = new URLSearchParams({ table: tableName });
    const resp = await fetch(`/api/table-data?${params}`);
    const data = await resp.json();

    if (!modalEl) return; // closed while loading
    renderGrid(data);
  } catch (err) {
    console.error('Failed to load table data:', err);
    closeViewer();
  }
}

function renderGrid(data) {
  const gridEl = modalEl.querySelector('.table-viewer__grid');
  if (!gridEl) return;

  const { table, columns, rows } = data;

  if (!rows || rows.length === 0) {
    gridEl.innerHTML = '<div class="table-viewer__empty">No data</div>';
    return;
  }

  const theadCells = columns.map((col) => {
    const badge = col.key_type
      ? `<span class="table-viewer__badge table-viewer__badge--${col.key_type.toLowerCase()}">${esc(col.key_type)}</span>`
      : '';
    return `<th class="table-viewer__th">${esc(col.name)}${badge}</th>`;
  }).join('');

  const tbodyRows = rows.map((row) =>
    '<tr>' + row.map((val, ci) =>
      `<td class="table-viewer__td" data-col="${esc(columns[ci].name)}" data-val="${esc(val)}">${esc(val)}</td>`
    ).join('') + '</tr>'
  ).join('');

  gridEl.innerHTML = `
    <div class="table-viewer__count">${rows.length} row${rows.length !== 1 ? 's' : ''}</div>
    <div class="table-viewer__scroll">
      <table class="table-viewer__table">
        <thead><tr>${theadCells}</tr></thead>
        <tbody>${tbodyRows}</tbody>
      </table>
    </div>
  `;

  // Cell click → trace
  gridEl.querySelectorAll('.table-viewer__td').forEach((td) => {
    td.addEventListener('click', () => {
      const column = td.dataset.col;
      const value = td.dataset.val;
      if (!value || value === '') return;
      closeViewer();
      EventBus.emit('traceRequested', { table, column, value });
    });
  });
}

function closeViewer() {
  if (modalEl) {
    modalEl.remove();
    modalEl = null;
  }
}
