/**
 * rebuilder.js — Schema rebuild UI for the diagram page.
 *
 * Generates a complete redesigned PostgreSQL schema from loaded CSVs +
 * detected relationships, then shows DDL + decisions report in a modal
 * with copy-to-clipboard buttons.
 */

import { escapeHtml } from './utils.js';

const MODAL_ID = 'rebuilder-modal';
const OPEN_CLASS = 'rebuilder-modal--open';

let currentResult = null;
let activeTab = 'ddl';

export function initRebuilder() {
  const btn = document.getElementById('btn-rebuilder');
  if (btn) btn.addEventListener('click', openModal);

  const modal = ensureModal();
  modal.addEventListener('click', onModalClick);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.classList.contains(OPEN_CLASS)) {
      closeModal();
    }
  });
}

async function openModal() {
  const modal = ensureModal();
  modal.classList.add(OPEN_CLASS);
  modal.setAttribute('aria-hidden', 'false');
  await runRebuild();
}

function closeModal() {
  const modal = document.getElementById(MODAL_ID);
  if (!modal) return;
  modal.classList.remove(OPEN_CLASS);
  modal.setAttribute('aria-hidden', 'true');
}

async function runRebuild() {
  const content = document.getElementById('rebuilder-content');
  if (!content) return;
  content.innerHTML = '<div class="rebuilder-empty">Rebuilding schema…</div>';

  try {
    const resp = await fetch('/api/rebuild-schema', { method: 'POST' });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    currentResult = await resp.json();
    renderResult();
  } catch (err) {
    content.innerHTML = `<div class="rebuilder-empty rebuilder-empty--error">Rebuild failed: ${escapeHtml(String(err))}</div>`;
  }
}

function renderResult() {
  const content = document.getElementById('rebuilder-content');
  if (!content || !currentResult) return;

  const schema = currentResult.schema || { tables: [], enums: [] };
  const decisions = currentResult.decisions || [];
  const tableCount = (schema.tables || []).length;
  const enumCount = (schema.enums || []).length;
  const fkCount = decisions.filter(d => d.kind === 'foreign_key').length;
  const surrogateCount = decisions.filter(d => d.kind === 'surrogate_pk').length;
  const renameCount = decisions.filter(d => d.kind === 'rename_table' || d.kind === 'rename_column').length;

  const summary = document.getElementById('rebuilder-summary');
  if (summary) {
    summary.innerHTML = `
      <span class="rebuilder-stat">${tableCount} tables</span>
      <span class="rebuilder-stat">${enumCount} enums</span>
      <span class="rebuilder-stat">${fkCount} FKs</span>
      <span class="rebuilder-stat">${surrogateCount} surrogate PKs</span>
      <span class="rebuilder-stat">${renameCount} renames</span>
    `;
  }

  renderActiveTab();
}

function renderActiveTab() {
  const content = document.getElementById('rebuilder-content');
  if (!content || !currentResult) return;

  document.querySelectorAll('.rebuilder-tab').forEach(btn => {
    btn.classList.toggle('rebuilder-tab--active', btn.dataset.tab === activeTab);
  });

  if (activeTab === 'ddl') {
    const ddl = currentResult.ddl || '';
    content.innerHTML = `<pre class="rebuilder-code"><code>${escapeHtml(ddl)}</code></pre>`;
  } else if (activeTab === 'report') {
    const report = currentResult.report || '';
    content.innerHTML = `<pre class="rebuilder-code rebuilder-code--markdown"><code>${escapeHtml(report)}</code></pre>`;
  } else if (activeTab === 'decisions') {
    content.innerHTML = renderDecisionsTable(currentResult.decisions || []);
  }
}

function renderDecisionsTable(decisions) {
  if (decisions.length === 0) {
    return '<div class="rebuilder-empty">No decisions recorded.</div>';
  }
  const rows = decisions.map(d => {
    const where = d.table
      ? (d.column ? `${d.table}.${d.column}` : d.table)
      : '—';
    const detail = buildDecisionDetail(d);
    return `<tr>
      <td><code>${escapeHtml(d.kind)}</code></td>
      <td><code>${escapeHtml(where)}</code></td>
      <td>${escapeHtml(detail)}</td>
    </tr>`;
  }).join('');
  return `
    <table class="rebuilder-table">
      <thead><tr><th>Kind</th><th>Location</th><th>Detail</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function buildDecisionDetail(d) {
  switch (d.kind) {
    case 'rename_table':
    case 'rename_column':
      return `${d.source} → ${d.target}`;
    case 'column_type':
      return `${d.source_type} → ${d.target_type}${d.not_null ? ' NOT NULL' : ''} — ${d.reason}`;
    case 'create_enum':
      return `${d.enum_name} (${(d.values || []).length} values) — ${d.reason}`;
    case 'surrogate_pk':
      return `${d.column} — ${d.reason}`;
    case 'foreign_key':
      return `${d.from_table}.${d.from_column} → ${d.to_table}.${d.to_column} (${d.relationship}, ${d.confidence})`;
    default:
      return d.reason || '';
  }
}

function onModalClick(e) {
  const target = e.target;
  if (!(target instanceof HTMLElement)) return;

  if (target.dataset.action === 'close' || target.classList.contains('rebuilder-modal__backdrop')) {
    closeModal();
    return;
  }
  if (target.dataset.tab) {
    activeTab = target.dataset.tab;
    renderActiveTab();
    return;
  }
  if (target.dataset.action === 'copy-ddl') {
    writeClipboard(currentResult?.ddl || '', 'DDL copied');
    return;
  }
  if (target.dataset.action === 'copy-report') {
    writeClipboard(currentResult?.report || '', 'Report copied — paste into your LLM');
    return;
  }
  if (target.dataset.action === 'download-ddl') {
    downloadText('rebuilt_schema.sql', currentResult?.ddl || '');
    return;
  }
  if (target.dataset.action === 'refresh') {
    runRebuild();
    return;
  }
}

async function writeClipboard(text, msg) {
  if (!text) { flashToast('Nothing to copy'); return; }
  try {
    await navigator.clipboard.writeText(text);
    flashToast(msg);
  } catch {
    flashToast('Clipboard write failed');
  }
}

function downloadText(filename, text) {
  if (!text) { flashToast('Nothing to download'); return; }
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  flashToast('DDL downloaded');
}

function flashToast(msg) {
  const toast = document.getElementById('toast');
  const msgEl = document.getElementById('toast-message');
  if (!toast || !msgEl) return;
  msgEl.textContent = msg;
  toast.hidden = false;
  toast.classList.add('toast--visible');
  setTimeout(() => {
    toast.classList.remove('toast--visible');
    toast.hidden = true;
  }, 2200);
}

function ensureModal() {
  let modal = document.getElementById(MODAL_ID);
  if (modal) return modal;

  modal = document.createElement('div');
  modal.id = MODAL_ID;
  modal.className = 'rebuilder-modal';
  modal.setAttribute('aria-hidden', 'true');
  modal.setAttribute('aria-label', 'Schema rebuilder');
  modal.innerHTML = `
    <div class="rebuilder-modal__backdrop" data-action="close"></div>
    <div class="rebuilder-modal__dialog" role="dialog">
      <header class="rebuilder-modal__header">
        <div>
          <h2 class="rebuilder-modal__title">Rebuilt Schema</h2>
          <div class="rebuilder-modal__summary" id="rebuilder-summary"></div>
        </div>
        <button class="rebuilder-modal__close" data-action="close" aria-label="Close">&times;</button>
      </header>
      <nav class="rebuilder-tabs">
        <button class="rebuilder-tab rebuilder-tab--active" data-tab="ddl">DDL</button>
        <button class="rebuilder-tab" data-tab="report">Report</button>
        <button class="rebuilder-tab" data-tab="decisions">Decisions</button>
      </nav>
      <main class="rebuilder-modal__content" id="rebuilder-content">
        <div class="rebuilder-empty">Click Rebuild to generate a schema.</div>
      </main>
      <footer class="rebuilder-modal__footer">
        <button class="rebuilder-btn rebuilder-btn--secondary" data-action="refresh">Rebuild</button>
        <button class="rebuilder-btn" data-action="copy-ddl">Copy DDL</button>
        <button class="rebuilder-btn" data-action="copy-report">Copy report for LLM</button>
        <button class="rebuilder-btn rebuilder-btn--secondary" data-action="download-ddl">Download .sql</button>
      </footer>
    </div>
  `;
  document.body.appendChild(modal);
  return modal;
}
