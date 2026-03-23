/**
 * trace.js — Value tracing across FK relationships.
 * Triggered by per-result trace buttons in search.js.
 * Shows trace path in #trace-panel with clear button.
 */

import { EventBus } from './events.js';
import * as State from './state.js';
import { TRACE_REQUEST_EVENT } from './search.js';
import { escapeHtml as esc } from './utils.js';

export function initTrace() {
  EventBus.on(TRACE_REQUEST_EVENT, onTraceRequest);
  EventBus.on('searchCleared', clearTrace);
}

async function onTraceRequest({ table, column, value }) {
  try {
    const response = await fetch('/api/trace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ table, column, value, depth: 5 }),
    });
    const trace = await response.json();
    State.setTraceResults(trace);
    renderTracePath(trace);
  } catch (err) {
    console.error('Trace failed:', err);
  }
}

function clearTrace() {
  State.setTraceResults(null);
  const panel = document.getElementById('trace-panel');
  if (panel) panel.innerHTML = '';
}

function renderTracePath(trace) {
  const panel = document.getElementById('trace-panel');
  if (!panel || !trace || !trace.nodes || trace.nodes.length === 0) {
    if (panel) panel.innerHTML = '<div class="trace-panel__empty">No connections found</div>';
    return;
  }

  const nodesHtml = trace.nodes.map(n => `
    <div class="trace-node" data-table="${esc(n.table)}">
      <span class="trace-node__depth">d${n.depth}</span>
      <strong>${esc(n.table)}</strong>.${esc(n.column)}
      <span class="trace-node__values">${n.values.slice(0, 3).map(v => esc(v)).join(', ')}</span>
    </div>
  `).join('<div class="trace-arrow">&rarr;</div>');

  panel.innerHTML = `
    <div class="trace-path">${nodesHtml}</div>
    <button class="toolbar__btn trace-btn--clear" id="btn-clear-trace">Clear Trace</button>
  `;

  document.getElementById('btn-clear-trace').addEventListener('click', clearTrace);

  panel.querySelectorAll('.trace-node').forEach(node => {
    node.addEventListener('click', () => {
      EventBus.emit('panToTable', node.dataset.table);
    });
  });
}

