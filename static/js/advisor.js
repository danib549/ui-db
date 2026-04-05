/**
 * advisor.js — Schema advisor UI for the diagram page.
 *
 * Fetches deterministic advisories from /api/analyze-schema (computed from
 * loaded CSV tables + detected relationships) and renders them in a
 * slide-out panel with copy-to-clipboard buttons so users can paste
 * suggestions into any external LLM.
 */

import { escapeHtml } from './utils.js';

const PANEL_ID = 'advisor-panel';
const OPEN_CLASS = 'advisor-panel--open';

let currentReport = null;

const SEVERITY_LABEL = {
  error: 'error',
  warning: 'warning',
  info: 'info',
};

const SEVERITY_ICON = {
  error: '\u2716',
  warning: '\u26A0',
  info: 'i',
};

// ---- Init ----

export function initAdvisor() {
  const btn = document.getElementById('btn-advisor');
  if (btn) btn.addEventListener('click', openPanel);

  const panel = ensurePanel();
  panel.addEventListener('click', onPanelClick);

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && panel.classList.contains(OPEN_CLASS)) {
      closePanel();
    }
  });
}

// ---- Panel open/close/refresh ----

async function openPanel() {
  const panel = ensurePanel();
  panel.classList.add(OPEN_CLASS);
  panel.setAttribute('aria-hidden', 'false');
  await refresh();
}

function closePanel() {
  const panel = document.getElementById(PANEL_ID);
  if (!panel) return;
  panel.classList.remove(OPEN_CLASS);
  panel.setAttribute('aria-hidden', 'true');
}

async function refresh() {
  const body = document.getElementById('advisor-panel-body');
  if (!body) return;
  body.innerHTML = '<div class="advisor-empty">Analyzing schema…</div>';

  try {
    const resp = await fetch('/api/analyze-schema', { method: 'POST' });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    currentReport = await resp.json();
    renderReport(currentReport);
  } catch (err) {
    body.innerHTML = `<div class="advisor-empty advisor-empty--error">Failed to analyze: ${escapeHtml(String(err))}</div>`;
  }
}

// ---- Rendering ----

function renderReport(report) {
  const body = document.getElementById('advisor-panel-body');
  const summary = document.getElementById('advisor-summary');
  if (!body || !summary) return;

  const counts = report.counts || { error: 0, warning: 0, info: 0 };
  const scores = report.scores || {};
  const stats = report.stats || {};

  summary.innerHTML = `
    <div class="advisor-counts">
      <span class="advisor-count advisor-count--error">${counts.error || 0} errors</span>
      <span class="advisor-count advisor-count--warning">${counts.warning || 0} warnings</span>
      <span class="advisor-count advisor-count--info">${counts.info || 0} info</span>
    </div>
    <div class="advisor-stats">
      ${stats.tables || 0} tables · ${stats.columns || 0} columns · ${stats.relationships || 0} relationships
    </div>
    <div class="advisor-scores">
      ${renderScoreBar('Structure', scores.structure)}
      ${renderScoreBar('Type precision', scores.type_precision)}
      ${renderScoreBar('Relationships', scores.relationships)}
    </div>
  `;

  const advisories = report.advisories || [];
  if (advisories.length === 0) {
    body.innerHTML = `
      <div class="advisor-empty advisor-empty--ok">
        No improvements suggested. Load CSVs on the diagram page first, or
        your schema already passes every rule.
      </div>
    `;
    return;
  }

  const sorted = [...advisories].sort((a, b) => {
    const order = { error: 0, warning: 1, info: 2 };
    return (order[a.severity] ?? 3) - (order[b.severity] ?? 3);
  });

  body.innerHTML = sorted.map((a, idx) => renderCard(a, idx)).join('');
}

function renderScoreBar(label, value) {
  const pct = typeof value === 'number' ? Math.round(value * 100) : 0;
  const color = pct >= 80 ? 'good' : pct >= 50 ? 'ok' : 'bad';
  return `
    <div class="advisor-score">
      <span class="advisor-score__label">${escapeHtml(label)}</span>
      <div class="advisor-score__bar">
        <div class="advisor-score__fill advisor-score__fill--${color}" style="width:${pct}%"></div>
      </div>
      <span class="advisor-score__value">${pct}%</span>
    </div>
  `;
}

function renderCard(a, idx) {
  const sev = a.severity || 'info';
  const icon = SEVERITY_ICON[sev] || SEVERITY_ICON.info;
  const loc = buildLocation(a);

  const evidenceHtml = a.evidence
    ? `<details class="advisor-card__evidence">
         <summary>Evidence</summary>
         <ul>${Object.entries(a.evidence).map(
           ([k, v]) => `<li><strong>${escapeHtml(k)}:</strong> ${escapeHtml(formatEvidenceValue(v))}</li>`,
         ).join('')}</ul>
       </details>`
    : '';

  const fixHtml = a.fix_sql
    ? `<pre class="advisor-card__sql"><code>${escapeHtml(a.fix_sql)}</code></pre>`
    : '';

  return `
    <article class="advisor-card advisor-card--${sev}" data-idx="${idx}">
      <header class="advisor-card__header">
        <span class="advisor-card__icon" aria-label="${escapeHtml(SEVERITY_LABEL[sev])}">${icon}</span>
        <div class="advisor-card__title">
          <div class="advisor-card__name">${escapeHtml(a.title || a.rule)}</div>
          ${loc ? `<div class="advisor-card__location"><code>${escapeHtml(loc)}</code></div>` : ''}
        </div>
      </header>
      <p class="advisor-card__reason">${escapeHtml(a.reason || '')}</p>
      ${evidenceHtml}
      ${fixHtml}
      <div class="advisor-card__actions">
        <button class="advisor-btn" data-action="copy-card" data-idx="${idx}">Copy for LLM</button>
        ${a.fix_sql ? '<button class="advisor-btn advisor-btn--secondary" data-action="copy-sql" data-idx="' + idx + '">Copy SQL</button>' : ''}
      </div>
    </article>
  `;
}

function buildLocation(a) {
  if (a.table && a.column) return `${a.table}.${a.column}`;
  return a.table || '';
}

function formatEvidenceValue(v) {
  if (Array.isArray(v)) return v.join(', ');
  if (v === null || v === undefined) return '—';
  return String(v);
}

// ---- Click handlers ----

function onPanelClick(e) {
  const target = e.target;
  if (!(target instanceof HTMLElement)) return;

  if (target.dataset.action === 'close') {
    closePanel();
    return;
  }
  if (target.dataset.action === 'refresh') {
    refresh();
    return;
  }
  if (target.dataset.action === 'copy-report') {
    copyFullReport();
    return;
  }
  if (target.dataset.action === 'copy-card') {
    const idx = parseInt(target.dataset.idx, 10);
    copySingleAdvisory(idx);
    return;
  }
  if (target.dataset.action === 'copy-sql') {
    const idx = parseInt(target.dataset.idx, 10);
    copyAdvisorySql(idx);
    return;
  }
}

// ---- Copy-to-clipboard flows ----

async function copyFullReport() {
  if (!currentReport || !currentReport.markdown) {
    flashToast('Nothing to copy yet');
    return;
  }
  await writeClipboard(currentReport.markdown, 'Report copied — paste into your LLM');
}

async function copySingleAdvisory(idx) {
  const advisory = (currentReport?.advisories || [])[idx];
  if (!advisory) return;
  try {
    const resp = await fetch('/api/advisory-markdown', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ advisory }),
    });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    await writeClipboard(data.markdown || '', 'Advisory copied — paste into your LLM');
  } catch {
    flashToast('Copy failed');
  }
}

async function copyAdvisorySql(idx) {
  const advisory = (currentReport?.advisories || [])[idx];
  if (!advisory?.fix_sql) return;
  await writeClipboard(advisory.fix_sql, 'SQL copied');
}

async function writeClipboard(text, successMsg) {
  try {
    await navigator.clipboard.writeText(text);
    flashToast(successMsg);
  } catch {
    flashToast('Clipboard write failed');
  }
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

// ---- DOM scaffolding ----

function ensurePanel() {
  let panel = document.getElementById(PANEL_ID);
  if (panel) return panel;

  panel = document.createElement('aside');
  panel.id = PANEL_ID;
  panel.className = 'advisor-panel';
  panel.setAttribute('aria-hidden', 'true');
  panel.setAttribute('aria-label', 'Schema advisor');
  panel.innerHTML = `
    <header class="advisor-panel__header">
      <h2 class="advisor-panel__title">Schema Advisor</h2>
      <div class="advisor-panel__actions">
        <button class="advisor-btn" data-action="copy-report" title="Copy full report for LLM">Copy full report</button>
        <button class="advisor-btn advisor-btn--secondary" data-action="refresh" title="Re-run analysis">Refresh</button>
        <button class="advisor-panel__close" data-action="close" aria-label="Close">&times;</button>
      </div>
    </header>
    <section class="advisor-panel__summary" id="advisor-summary"></section>
    <section class="advisor-panel__body" id="advisor-panel-body">
      <div class="advisor-empty">Click "Advisor" in the toolbar to scan your loaded tables.</div>
    </section>
  `;
  document.body.appendChild(panel);
  return panel;
}
