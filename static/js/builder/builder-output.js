/**
 * builder-output.js — DDL preview panel (right) + export controls.
 * DDL preview and validation errors are derived data, NOT stored in state.
 * Computed on builderStateChanged, held as module-local variables.
 */

import { EventBus } from '../events.js';
import { escapeHtml } from '../utils.js';
import {
  getTargetSchema, getOriginalSchema, hasOriginalSchema, getSourceMapping,
} from './builder-state.js';
import { showToast } from './builder-editors.js';

// Module-local derived data
let ddlPreview = '';
let validationErrors = [];
let migrationPreview = '';

let ddlDebounce = null;
let validationDebounce = null;

// ---- Public getters ----
export function getDDLPreview() { return ddlPreview; }
export function getValidationErrors() { return validationErrors; }
export function hasBlockingErrors() {
  return validationErrors.some(e => e.severity === 'error');
}

// ---- Init ----

export function initOutput() {
  initTabs();
  initExportButtons();
}

function initTabs() {
  const tabs = document.querySelectorAll('.builder-output__tab');
  const contents = document.querySelectorAll('.builder-output__content');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('builder-output__tab--active'));
      contents.forEach(c => c.classList.remove('builder-output__content--active'));

      tab.classList.add('builder-output__tab--active');
      const target = document.getElementById(`tab-${tab.dataset.tab}`);
      if (target) target.classList.add('builder-output__content--active');
    });
  });
}

function initExportButtons() {
  document.getElementById('copy-ddl')?.addEventListener('click', () => {
    copyToClipboard(ddlPreview, 'DDL copied to clipboard');
  });

  document.getElementById('export-sql')?.addEventListener('click', () => {
    downloadFile(ddlPreview, 'schema.sql', 'text/sql');
  });

  document.getElementById('export-json')?.addEventListener('click', () => {
    const schema = getTargetSchema();
    const json = JSON.stringify({
      version: 1,
      generator: 'DB Diagram Visualizer',
      generatedAt: new Date().toISOString(),
      schema,
      sourceMapping: getSourceMapping(),
    }, null, 2);
    downloadFile(json, 'schema.json', 'application/json');
  });

  document.getElementById('copy-migration')?.addEventListener('click', () => {
    copyToClipboard(migrationPreview, 'Migration SQL copied to clipboard');
  });

  document.getElementById('export-migration')?.addEventListener('click', () => {
    downloadFile(migrationPreview, 'migration.sql', 'text/sql');
  });
}

// ---- Refresh (called by builder-app on state change) ----

export function refreshOutput() {
  clearTimeout(ddlDebounce);
  clearTimeout(validationDebounce);

  ddlDebounce = setTimeout(refreshDDL, 300);
  validationDebounce = setTimeout(refreshValidation, 500);
  refreshMigration();
}

async function refreshDDL() {
  const schema = getTargetSchema();
  if (!schema.tables.length && !schema.enums.length) {
    ddlPreview = '-- Generated DDL will appear here as you build your schema';
    renderDDL();
    return;
  }

  try {
    const resp = await fetch('/api/builder/generate-ddl', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schema }),
    });

    if (resp.ok) {
      const data = await resp.json();
      ddlPreview = data.sql || '';
      EventBus.emit('builderDDLGenerated', { sql: ddlPreview });
    }
  } catch {
    ddlPreview = '-- Error generating DDL';
  }

  renderDDL();
}

async function refreshValidation() {
  const schema = getTargetSchema();
  if (!schema.tables.length) {
    validationErrors = [];
    renderValidation();
    return;
  }

  try {
    const resp = await fetch('/api/builder/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schema }),
    });

    if (resp.ok) {
      const data = await resp.json();
      validationErrors = data.issues || [];
      EventBus.emit('builderValidationRan', { errors: validationErrors });
    }
  } catch {
    validationErrors = [];
  }

  renderValidation();
}

async function refreshMigration() {
  const schema = getTargetSchema();
  const original = getOriginalSchema();
  const sourceMapping = getSourceMapping();

  if (!schema.tables.length) {
    migrationPreview = '-- Migration SQL will appear here';
    renderMigration();
    return;
  }

  try {
    const resp = await fetch('/api/builder/generate-migration', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        original: original || null,
        modified: schema,
        sourceMapping: Object.keys(sourceMapping).length ? sourceMapping : undefined,
      }),
    });

    if (resp.ok) {
      const data = await resp.json();
      const parts = [];
      if (data.schemaSql) parts.push(data.schemaSql);
      if (data.dataSql) parts.push(data.dataSql);
      migrationPreview = parts.join('\n\n') || '-- No migration needed';
    }
  } catch {
    migrationPreview = '-- Error generating migration';
  }

  renderMigration();
}

// ---- Renderers ----

function renderDDL() {
  const el = document.getElementById('ddl-preview');
  if (el) el.textContent = ddlPreview;
}

function renderValidation() {
  const container = document.getElementById('validation-list');
  if (!container) return;

  if (validationErrors.length === 0) {
    container.innerHTML = `
      <div class="builder-validation__item builder-validation__item--ok">
        <span class="builder-validation__icon">&#10003;</span>
        <span>Schema is valid — no issues found</span>
      </div>
    `;
    return;
  }

  container.innerHTML = validationErrors.map(issue => {
    const severity = issue.severity || 'info';
    const icon = severity === 'error' ? '&#10007;' : severity === 'warning' ? '&#9888;' : '&#8505;';
    const cssClass = `builder-validation__item--${severity}`;

    let location = '';
    if (issue.table) location += issue.table;
    if (issue.column) location += `.${issue.column}`;
    if (issue.constraint) location += ` [${issue.constraint}]`;
    const locationHtml = location ? `<strong>${escapeHtml(location)}</strong>: ` : '';

    return `
      <div class="builder-validation__item ${cssClass}">
        <span class="builder-validation__icon">${icon}</span>
        <span>${locationHtml}${escapeHtml(issue.message)}</span>
      </div>
    `;
  }).join('');
}

function renderMigration() {
  const el = document.getElementById('migration-preview');
  if (el) el.textContent = migrationPreview;
}

// ---- Helpers ----

function copyToClipboard(text, successMsg) {
  if (!text || text === '-- Generated DDL will appear here as you build your schema'
             || text === '-- Migration SQL will appear here') {
    showToast('Nothing to copy');
    return;
  }
  navigator.clipboard.writeText(text).then(
    () => showToast(successMsg || 'Copied!'),
    () => showToast('Copy failed'),
  );
}

function downloadFile(content, filename, mimeType) {
  if (!content || content === '-- Generated DDL will appear here as you build your schema'
               || content === '-- Migration SQL will appear here') {
    showToast('Nothing to export');
    return;
  }
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  showToast(`Exported ${filename}`);
}
