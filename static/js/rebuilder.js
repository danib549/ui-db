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

// Option catalog — mirrors DEFAULT_OPTIONS in schema_optimizer.py
const OPTION_CATALOG = [
  {
    group: 'Data-Driven Structure',
    options: [
      { key: 'mn_to_1n_downgrade',   label: 'Downgrade M:N → 1:N',          enabled: true,  mode: 'apply', flagOnly: false },
      { key: 'inline_lookup_tables', label: 'Inline thin lookup tables',    enabled: false, mode: 'apply', flagOnly: false },
      { key: 'merge_1_1_pairs',      label: 'Merge 1:1 pairs',              enabled: false, mode: 'flag',  flagOnly: false },
      { key: 'drop_orphan_tables',   label: 'Flag orphan tables',           enabled: true,  mode: 'flag',  flagOnly: true },
    ],
  },
  {
    group: 'Column Optimization',
    options: [
      { key: 'type_downsizing',       label: 'Type downsizing',              enabled: true,  mode: 'apply', flagOnly: false },
      { key: 'strict_nullability',    label: 'Strict NOT NULL',              enabled: true,  mode: 'apply', flagOnly: false },
      { key: 'enum_discovery',        label: 'ENUM discovery',               enabled: true,  mode: 'apply', flagOnly: false },
      { key: 'dead_column_detection', label: 'Dead column detection',        enabled: false, mode: 'flag',  flagOnly: true },
    ],
  },
  {
    group: 'Indexes & Foreign Keys',
    options: [
      { key: 'collapse_redundant_indexes', label: 'Collapse redundant indexes', enabled: true,  mode: 'apply', flagOnly: false },
      { key: 'missing_fk_indexes',         label: 'Add missing FK indexes',     enabled: true,  mode: 'apply', flagOnly: false },
      { key: 'implicit_fk_discovery',      label: 'Discover implicit FKs',      enabled: false, mode: 'apply', flagOnly: false },
    ],
  },
  {
    group: 'Advanced (Flag Only)',
    options: [
      { key: 'eav_to_jsonb',                   label: 'EAV → JSONB',                enabled: false, mode: 'flag', flagOnly: true },
      { key: 'vertical_split_fat_tables',      label: 'Vertical split candidates',  enabled: false, mode: 'flag', flagOnly: true },
      { key: 'time_series_partition_candidates', label: 'Time-series partitioning', enabled: false, mode: 'flag', flagOnly: true },
    ],
  },
  {
    group: 'Data Integrity (Flag Only)',
    options: [
      { key: 'dangling_reference_detect', label: 'Dangling FK references', enabled: false, mode: 'flag', flagOnly: true },
      { key: 'soft_delete_ghosting',      label: 'Soft-delete ghosting',    enabled: false, mode: 'flag', flagOnly: true },
    ],
  },
];

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
    const resp = await fetch('/api/rebuild-schema', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ options: collectOptions() }),
    });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    currentResult = await resp.json();
    renderResult();
  } catch (err) {
    content.innerHTML = `<div class="rebuilder-empty rebuilder-empty--error">Rebuild failed: ${escapeHtml(String(err))}</div>`;
  }
}

function collectOptions() {
  const out = {};
  for (const group of OPTION_CATALOG) {
    for (const opt of group.options) {
      const enabledEl = document.getElementById(`ropt-en-${opt.key}`);
      const modeEl = document.getElementById(`ropt-mode-${opt.key}`);
      out[opt.key] = {
        enabled: enabledEl ? enabledEl.checked : opt.enabled,
        mode: opt.flagOnly ? 'flag' : (modeEl ? modeEl.value : opt.mode),
      };
    }
  }
  return out;
}

function renderResult() {
  const content = document.getElementById('rebuilder-content');
  if (!content || !currentResult) return;

  const schema = currentResult.schema || { tables: [], enums: [] };
  const decisions = currentResult.decisions || [];
  const flags = currentResult.flags || [];
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
      <span class="rebuilder-stat rebuilder-stat--flags">${flags.length} flags</span>
    `;
  }

  // Update flag tab badge
  const flagsTab = document.querySelector('.rebuilder-tab[data-tab="flags"]');
  if (flagsTab) {
    flagsTab.textContent = flags.length > 0 ? `Flags (${flags.length})` : 'Flags';
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
  } else if (activeTab === 'flags') {
    content.innerHTML = renderFlagsTable(currentResult.flags || []);
  } else if (activeTab === 'viz') {
    content.innerHTML = renderVisualization(currentResult.schema || { tables: [], enums: [] });
  }
}

// Visualization constants
const VIZ_CARD_WIDTH = 240;
const VIZ_ROW_HEIGHT = 22;
const VIZ_HEADER_HEIGHT = 34;
const VIZ_CARD_PADDING = 10;
const VIZ_GAP_X = 60;
const VIZ_GAP_Y = 50;
const VIZ_COLS = 3;
const VIZ_MARGIN = 30;

function renderVisualization(schema) {
  const tables = schema.tables || [];
  if (tables.length === 0) {
    return '<div class="rebuilder-empty">No tables to visualize.</div>';
  }
  const positions = computeVizLayout(tables);
  const anchors = computeVizAnchors(tables, positions);
  const fks = collectVizFKs(tables);
  const canvasW = VIZ_COLS * VIZ_CARD_WIDTH + (VIZ_COLS - 1) * VIZ_GAP_X + VIZ_MARGIN * 2;
  const lastRow = Math.floor((tables.length - 1) / VIZ_COLS);
  const canvasH = (lastRow + 1) * (maxRowHeight(tables, positions, lastRow) + VIZ_GAP_Y) + VIZ_MARGIN;

  const linesSvg = fks.map(fk => renderVizLine(fk, anchors)).filter(Boolean).join('');
  const cards = tables.map(t => renderVizCard(t, positions.get(t.name))).join('');

  return `
    <div class="rebuilder-viz" style="width:${canvasW}px;height:${canvasH}px;">
      <svg class="rebuilder-viz__lines" width="${canvasW}" height="${canvasH}">
        <defs>
          <marker id="viz-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill="#6366f1"/>
          </marker>
        </defs>
        ${linesSvg}
      </svg>
      ${cards}
    </div>
  `;
}

function computeVizLayout(tables) {
  const positions = new Map();
  let rowTops = [VIZ_MARGIN];
  let rowMax = 0;
  tables.forEach((t, i) => {
    const row = Math.floor(i / VIZ_COLS);
    const col = i % VIZ_COLS;
    if (col === 0 && row > 0) {
      rowTops.push(rowTops[row - 1] + rowMax + VIZ_GAP_Y);
      rowMax = 0;
    }
    const height = cardHeight(t);
    if (height > rowMax) rowMax = height;
    const x = VIZ_MARGIN + col * (VIZ_CARD_WIDTH + VIZ_GAP_X);
    const y = rowTops[row];
    positions.set(t.name, { x, y, w: VIZ_CARD_WIDTH, h: height });
  });
  return positions;
}

function maxRowHeight(tables, positions, row) {
  let max = 0;
  for (let i = row * VIZ_COLS; i < Math.min(tables.length, (row + 1) * VIZ_COLS); i++) {
    const p = positions.get(tables[i].name);
    if (p && p.h > max) max = p.h;
  }
  return max || VIZ_HEADER_HEIGHT;
}

function cardHeight(table) {
  const cols = (table.columns || []).length;
  return VIZ_HEADER_HEIGHT + cols * VIZ_ROW_HEIGHT + VIZ_CARD_PADDING * 2;
}

function computeVizAnchors(tables, positions) {
  const anchors = new Map();
  tables.forEach(t => {
    const pos = positions.get(t.name);
    if (!pos) return;
    const colAnchors = new Map();
    (t.columns || []).forEach((c, i) => {
      const y = pos.y + VIZ_HEADER_HEIGHT + VIZ_CARD_PADDING + i * VIZ_ROW_HEIGHT + VIZ_ROW_HEIGHT / 2;
      colAnchors.set(c.name, { left: pos.x, right: pos.x + pos.w, y });
    });
    anchors.set(t.name, { pos, cols: colAnchors });
  });
  return anchors;
}

function collectVizFKs(tables) {
  const fks = [];
  tables.forEach(t => {
    (t.constraints || []).forEach(c => {
      if (c.type !== 'fk') return;
      fks.push({
        from_table: t.name,
        from_column: (c.columns || [])[0],
        to_table: c.refTable,
        to_column: (c.refColumns || [])[0],
      });
    });
  });
  return fks;
}

function renderVizLine(fk, anchors) {
  const src = anchors.get(fk.from_table);
  const tgt = anchors.get(fk.to_table);
  if (!src || !tgt) return '';
  const srcCol = src.cols.get(fk.from_column);
  const tgtCol = tgt.cols.get(fk.to_column);
  if (!srcCol || !tgtCol) return '';
  // Pick left or right edge of each side
  const srcOnLeft = src.pos.x + src.pos.w / 2 < tgt.pos.x + tgt.pos.w / 2;
  const x1 = srcOnLeft ? srcCol.right : srcCol.left;
  const x2 = srcOnLeft ? tgtCol.left : tgtCol.right;
  const y1 = srcCol.y;
  const y2 = tgtCol.y;
  const dx = Math.abs(x2 - x1);
  const cx1 = x1 + (srcOnLeft ? dx * 0.4 : -dx * 0.4);
  const cx2 = x2 + (srcOnLeft ? -dx * 0.4 : dx * 0.4);
  return `<path d="M${x1},${y1} C${cx1},${y1} ${cx2},${y2} ${x2},${y2}" class="rebuilder-viz__line" marker-end="url(#viz-arrow)"/>`;
}

function renderVizCard(table, pos) {
  if (!pos) return '';
  const cols = (table.columns || []).map(c => {
    const badges = [];
    if (c.isPrimaryKey) badges.push('<span class="rebuilder-viz__badge rebuilder-viz__badge--pk">PK</span>');
    if (c.isUnique) badges.push('<span class="rebuilder-viz__badge rebuilder-viz__badge--uq">UQ</span>');
    const isFk = (table.constraints || []).some(ct => ct.type === 'fk' && (ct.columns || []).includes(c.name));
    if (isFk) badges.push('<span class="rebuilder-viz__badge rebuilder-viz__badge--fk">FK</span>');
    const nullMark = c.nullable ? '' : '<span class="rebuilder-viz__nn">*</span>';
    return `
      <div class="rebuilder-viz__col">
        <span class="rebuilder-viz__colname">${escapeHtml(c.name)}${nullMark}</span>
        <span class="rebuilder-viz__coltype">${escapeHtml(c.type || '')}</span>
        ${badges.join('')}
      </div>`;
  }).join('');
  return `
    <div class="rebuilder-viz__card" style="left:${pos.x}px;top:${pos.y}px;width:${pos.w}px;">
      <div class="rebuilder-viz__header">${escapeHtml(table.name)}</div>
      <div class="rebuilder-viz__body">${cols}</div>
    </div>`;
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

function renderFlagsTable(flags) {
  if (flags.length === 0) {
    return '<div class="rebuilder-empty">No flags raised. Enable flag-mode options to see advisories.</div>';
  }
  const sev = { error: 0, warning: 1, info: 2 };
  const sorted = [...flags].sort((a, b) => (sev[a.severity] ?? 3) - (sev[b.severity] ?? 3));
  const rows = sorted.map(f => {
    const where = f.table
      ? (f.column ? `${f.table}.${f.column}` : f.table)
      : '—';
    return `<tr class="rebuilder-flag-row rebuilder-flag-row--${escapeHtml(f.severity || 'info')}">
      <td><span class="rebuilder-sev rebuilder-sev--${escapeHtml(f.severity || 'info')}">${escapeHtml(f.severity || 'info')}</span></td>
      <td><code>${escapeHtml(f.rule || '')}</code></td>
      <td><code>${escapeHtml(where)}</code></td>
      <td>${escapeHtml(f.title || '')}<br><span class="rebuilder-flag-reason">${escapeHtml(f.reason || '')}</span></td>
    </tr>`;
  }).join('');
  return `
    <table class="rebuilder-table rebuilder-flags-table">
      <thead><tr><th>Severity</th><th>Rule</th><th>Location</th><th>Detail</th></tr></thead>
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
    case 'enum_discover':
      return `${d.enum_name} (${(d.values || []).length} values) — ${d.reason}`;
    case 'surrogate_pk':
      return `${d.column} — ${d.reason}`;
    case 'foreign_key':
      return `${d.from_table}.${d.from_column} → ${d.to_table}.${d.to_column} (${d.relationship}, ${d.confidence})`;
    case 'mn_downgrade':
      return `junction '${d.table}' removed — FK on '${d.keep_table}.${d.new_column}' → '${d.drop_table_ref}'`;
    case 'inline_lookup':
      return `'${d.table}' inlined into '${d.inlined_into}' as '${d.column}'`;
    case 'merge_1_1':
      return `'${d.table}' merged into '${d.merged_into}' — ${d.reason}`;
    case 'type_downsize':
      return `${d.from_type} → ${d.to_type} — ${d.reason}`;
    case 'strict_not_null':
      return d.reason;
    case 'drop_redundant_index':
      return `'${d.index}' dropped (covered by '${d.covered_by}')`;
    case 'add_fk_index':
      return `index '${d.index}' on (${(d.columns || []).join(', ')})`;
    case 'implicit_fk':
      return `'${d.table}.${d.column}' → '${d.target_table}.${d.target_column}' (overlap ${d.overlap})`;
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

function renderOptionsPanel() {
  const groups = OPTION_CATALOG.map(group => {
    const rows = group.options.map(opt => {
      const checked = opt.enabled ? 'checked' : '';
      const modeControl = opt.flagOnly
        ? '<span class="rebuilder-option-pill">flag only</span>'
        : `<select class="rebuilder-option-mode" id="ropt-mode-${opt.key}">
             <option value="apply"${opt.mode === 'apply' ? ' selected' : ''}>apply</option>
             <option value="flag"${opt.mode === 'flag' ? ' selected' : ''}>flag</option>
           </select>`;
      return `
        <label class="rebuilder-option-row${opt.flagOnly ? ' rebuilder-option-row--flag-only' : ''}">
          <input type="checkbox" id="ropt-en-${opt.key}" ${checked}>
          <span class="rebuilder-option-label">${escapeHtml(opt.label)}</span>
          ${modeControl}
        </label>`;
    }).join('');
    return `
      <details class="rebuilder-option-group" open>
        <summary class="rebuilder-option-group__summary">${escapeHtml(group.group)}</summary>
        <div class="rebuilder-option-group__body">${rows}</div>
      </details>`;
  }).join('');
  return `<section class="rebuilder-options" aria-label="Optimization options">${groups}</section>`;
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
      ${renderOptionsPanel()}
      <nav class="rebuilder-tabs">
        <button class="rebuilder-tab rebuilder-tab--active" data-tab="ddl">DDL</button>
        <button class="rebuilder-tab" data-tab="viz">Visualization</button>
        <button class="rebuilder-tab" data-tab="report">Report</button>
        <button class="rebuilder-tab" data-tab="decisions">Decisions</button>
        <button class="rebuilder-tab" data-tab="flags">Flags</button>
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
