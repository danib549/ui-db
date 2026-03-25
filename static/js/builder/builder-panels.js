/**
 * builder-panels.js — Source panel (left) + target panel (center) rendering.
 */

import { EventBus } from '../events.js';
import { escapeHtml } from '../utils.js';
import {
  getTargetSchema, addTable, removeTable, updateTable,
  addColumn, removeColumn, findTable,
  addEnum, removeEnum, updateEnum,
  setTargetSchema, setOriginalSchema, clearOriginalSchema,
  setActiveEditor, getSourceMapping,
  removeConstraint, removeIndex,
} from './builder-state.js';
import { DEFAULT_TABLE, DEFAULT_COLUMN } from './builder-constants.js';
import { showConfirm, showToast } from './builder-editors.js';

let sourceTablesCache = [];
let sourceSearchFilter = '';

// ---- Source Panel ----

export async function renderSourcePanel() {
  await loadSourceTables();
  renderSourceList();
  initSourceImport();
}

async function loadSourceTables() {
  try {
    const resp = await fetch('/api/builder/source-tables');
    if (resp.ok) {
      const data = await resp.json();
      sourceTablesCache = data.tables || [];
    }
  } catch {
    sourceTablesCache = [];
  }
}

function renderSourceList() {
  const container = document.getElementById('source-table-list');
  if (!container) return;

  const emptyEl = document.getElementById('source-empty');
  const filtered = sourceTablesCache.filter(t =>
    !sourceSearchFilter || t.name.toLowerCase().includes(sourceSearchFilter.toLowerCase())
  );

  if (filtered.length === 0) {
    if (emptyEl) emptyEl.hidden = false;
    container.querySelectorAll('.builder-source__table').forEach(el => el.remove());
    return;
  }

  if (emptyEl) emptyEl.hidden = true;

  // Remove existing table entries
  container.querySelectorAll('.builder-source__table').forEach(el => el.remove());

  for (const table of filtered) {
    const div = document.createElement('div');
    div.className = 'builder-source__table';
    div.dataset.table = table.name;

    const cols = table.columns || [];
    div.innerHTML = `
      <div class="builder-source__table-header">
        <span class="builder-source__arrow">&#9654;</span>
        <span class="builder-source__table-name">${escapeHtml(table.name)}</span>
        <span class="builder-source__col-count">${cols.length} cols</span>
      </div>
      <div class="builder-source__columns" hidden>
        ${cols.map(c => `
          <div class="builder-source__column" draggable="true" data-table="${escapeHtml(table.name)}" data-column="${escapeHtml(c.name)}">
            ${_keyIcon(c)}
            <span class="builder-source__col-name">${escapeHtml(c.name)}</span>
            <span class="builder-source__col-type">${escapeHtml(c.type || '')}</span>
          </div>
        `).join('')}
      </div>
    `;

    const header = div.querySelector('.builder-source__table-header');
    const colsDiv = div.querySelector('.builder-source__columns');
    const arrow = div.querySelector('.builder-source__arrow');

    header.addEventListener('click', () => {
      const hidden = colsDiv.hidden;
      colsDiv.hidden = !hidden;
      arrow.classList.toggle('builder-source__arrow--expanded', !hidden);
    });

    // Drag events for source columns
    div.querySelectorAll('.builder-source__column').forEach(colEl => {
      colEl.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/plain', JSON.stringify({
          sourceTable: colEl.dataset.table,
          sourceColumn: colEl.dataset.column,
        }));
        e.dataTransfer.effectAllowed = 'copy';
      });
    });

    container.appendChild(div);
  }
}

function _keyIcon(col) {
  const keys = col.keys || [];
  if (keys.includes('PK')) {
    return '<span class="builder-source__key-icon builder-source__key-icon--pk">&#9679;</span>';
  }
  if (keys.includes('FK')) {
    return '<span class="builder-source__key-icon builder-source__key-icon--fk">&#9679;</span>';
  }
  return '<span class="builder-source__key-icon" style="visibility:hidden">&#9679;</span>';
}

function initSourceImport() {
  const searchInput = document.getElementById('source-search');
  if (searchInput) {
    let debounceTimer;
    searchInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        sourceSearchFilter = searchInput.value;
        renderSourceList();
      }, 200);
    });
  }

  initSqlImport();
}

function initSqlImport() {
  const zone = document.getElementById('sql-import-zone');
  const fileInput = document.getElementById('sql-file-input');
  const statusEl = document.getElementById('sql-import-status');
  const infoEl = document.getElementById('sql-import-info');
  const clearBtn = document.getElementById('sql-import-clear');

  if (!zone || !fileInput) return;

  zone.addEventListener('click', () => fileInput.click());

  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    zone.classList.add('builder-source__import-zone--dragover');
  });

  zone.addEventListener('dragleave', () => {
    zone.classList.remove('builder-source__import-zone--dragover');
  });

  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('builder-source__import-zone--dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith('.sql')) {
      uploadSqlFile(file);
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) {
      uploadSqlFile(fileInput.files[0]);
      fileInput.value = '';
    }
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      clearOriginalSchema();
      setTargetSchema({ name: 'public', tables: [], enums: [] });
      if (statusEl) statusEl.hidden = true;
      if (zone) zone.hidden = false;
      showToast('Imported schema cleared');
    });
  }
}

async function uploadSqlFile(file) {
  const zone = document.getElementById('sql-import-zone');
  const statusEl = document.getElementById('sql-import-status');
  const infoEl = document.getElementById('sql-import-info');

  const formData = new FormData();
  formData.append('file', file);

  try {
    const resp = await fetch('/api/builder/import-sql', { method: 'POST', body: formData });
    const data = await resp.json();

    if (!resp.ok) {
      showToast(data.error || 'Import failed');
      return;
    }

    const schema = data.schema;
    const warnings = data.warnings || [];

    setTargetSchema(schema);
    setOriginalSchema(schema);

    if (zone) zone.hidden = true;
    if (statusEl) statusEl.hidden = false;
    if (infoEl) {
      infoEl.textContent = `Imported: ${schema.tables.length} tables, ${schema.enums.length} enums`;
      if (warnings.length > 0) {
        infoEl.textContent += ` (${warnings.length} warnings)`;
      }
    }

    showToast(`Imported ${schema.tables.length} tables from SQL`);
    EventBus.emit('builderSqlImported', { tableCount: schema.tables.length, warnings });

  } catch (err) {
    showToast('Failed to import SQL file');
  }
}

// ---- Target Panel ----

export function renderTargetPanel() {
  const schema = getTargetSchema();
  const container = document.getElementById('target-tables');
  const emptyEl = document.getElementById('target-empty');
  if (!container) return;

  if (schema.tables.length === 0) {
    if (emptyEl) emptyEl.hidden = false;
    container.querySelectorAll('.builder-table-card').forEach(el => el.remove());
  } else {
    if (emptyEl) emptyEl.hidden = true;
    renderTableCards(container, schema.tables);
  }

  renderEnumCards(schema.enums);
}

function renderTableCards(container, tables) {
  // Remove stale cards
  container.querySelectorAll('.builder-table-card').forEach(el => el.remove());

  for (const table of tables) {
    const card = createTableCard(table);
    container.appendChild(card);
  }
}

function createTableCard(table) {
  const card = document.createElement('div');
  card.className = 'builder-table-card';
  card.dataset.table = table.name;

  const sourceMapping = getSourceMapping();

  card.innerHTML = `
    <div class="builder-table-card__header">
      <input class="builder-table-card__name" value="${escapeHtml(table.name)}" spellcheck="false">
      <select class="builder-table-card__type">
        <option value="permanent" ${table.tableType === 'permanent' ? 'selected' : ''}>Table</option>
        <option value="temp" ${table.tableType === 'temp' ? 'selected' : ''}>Temp</option>
        <option value="unlogged" ${table.tableType === 'unlogged' ? 'selected' : ''}>Unlogged</option>
      </select>
      <button class="builder-table-card__delete" title="Remove table">&times;</button>
    </div>
    <div class="builder-table-card__columns">
      ${table.columns.map(col => _renderColumnRow(table.name, col, sourceMapping)).join('')}
    </div>
    <button class="builder-table-card__add-column">+ Add Column</button>
    <div class="builder-table-card__constraints">
      ${table.constraints.map(c => {
        const warn = _constraintWarning(c, table);
        const warnIcon = warn ? `<span class="builder-constraint-badge__warn" title="${escapeHtml(warn)}">&#9888;</span>` : '';
        return `<span class="builder-constraint-badge ${warn ? 'builder-constraint-badge--warn' : ''}" data-constraint="${escapeHtml(c.name)}" title="${escapeHtml(c.name)}">
          ${warnIcon}${escapeHtml(_constraintLabel(c))}
          <button class="builder-constraint-badge__delete" data-constraint="${escapeHtml(c.name)}" title="Remove constraint">&times;</button>
        </span>`;
      }).join('')}
      <button class="builder-table-card__add-constraint">+ Constraint</button>
    </div>
    <div class="builder-table-card__indexes">
      ${(table.indexes || []).map(idx => `<span class="builder-index-badge" data-index="${escapeHtml(idx.name)}">
        idx: ${escapeHtml(idx.columns.join(', '))} (${idx.type})
        <button class="builder-index-badge__delete" data-index="${escapeHtml(idx.name)}" title="Remove index">&times;</button>
      </span>`).join('')}
      <button class="builder-table-card__add-index">+ Index</button>
    </div>
  `;

  // Wire events
  const nameInput = card.querySelector('.builder-table-card__name');
  nameInput.addEventListener('blur', () => {
    const newName = nameInput.value.trim();
    if (newName && newName !== table.name) {
      updateTable(table.name, { name: newName });
    }
  });
  nameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') nameInput.blur();
  });

  card.querySelector('.builder-table-card__type').addEventListener('change', (e) => {
    updateTable(table.name, { tableType: e.target.value });
  });

  card.querySelector('.builder-table-card__delete').addEventListener('click', () => {
    showConfirm(`Delete table "${table.name}" and all its columns?`, () => {
      removeTable(table.name);
    });
  });

  card.querySelector('.builder-table-card__add-column').addEventListener('click', () => {
    const newCol = { ...DEFAULT_COLUMN, name: `column_${table.columns.length + 1}` };
    addColumn(table.name, newCol);
  });

  // Column row events
  card.querySelectorAll('.builder-column-row').forEach(row => {
    const colName = row.dataset.column;

    row.querySelector('.builder-column-row__name')?.addEventListener('blur', (e) => {
      const newName = e.target.value.trim();
      if (newName && newName !== colName) {
        const col = table.columns.find(c => c.name === colName);
        if (col) col.name = newName;
        EventBus.emit('builderStateChanged', { key: 'columns' });
      }
    });

    row.querySelector('.builder-column-row__type-btn')?.addEventListener('click', () => {
      setActiveEditor({ type: 'column', table: table.name, column: colName });
      EventBus.emit('builderOpenColumnEditor', { tableName: table.name, columnName: colName });
    });

    row.querySelector('.builder-column-row__edit')?.addEventListener('click', () => {
      setActiveEditor({ type: 'column', table: table.name, column: colName });
      EventBus.emit('builderOpenColumnEditor', { tableName: table.name, columnName: colName });
    });

    row.querySelector('.builder-column-row__delete')?.addEventListener('click', () => {
      removeColumn(table.name, colName);
    });
  });

  // Constraint delete buttons
  card.querySelectorAll('.builder-constraint-badge__delete').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const name = btn.dataset.constraint;
      showConfirm(`Remove constraint "${name}"?`, () => {
        removeConstraint(table.name, name);
      });
    });
  });

  // Index delete buttons
  card.querySelectorAll('.builder-index-badge__delete').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const name = btn.dataset.index;
      showConfirm(`Remove index "${name}"?`, () => {
        removeIndex(table.name, name);
      });
    });
  });

  // Constraint/index add buttons
  card.querySelector('.builder-table-card__add-constraint')?.addEventListener('click', () => {
    EventBus.emit('builderOpenConstraintPicker', { tableName: table.name });
  });

  card.querySelector('.builder-table-card__add-index')?.addEventListener('click', () => {
    EventBus.emit('builderOpenIndexPicker', { tableName: table.name });
  });

  // Drop target for source column mapping
  card.addEventListener('dragover', (e) => {
    e.preventDefault();
    card.classList.add('builder-drop-target');
  });

  card.addEventListener('dragleave', () => {
    card.classList.remove('builder-drop-target');
  });

  card.addEventListener('drop', (e) => {
    e.preventDefault();
    card.classList.remove('builder-drop-target');
    try {
      const data = JSON.parse(e.dataTransfer.getData('text/plain'));
      if (data.sourceTable && data.sourceColumn) {
        EventBus.emit('builderSourceDropped', {
          sourceTable: data.sourceTable,
          sourceColumn: data.sourceColumn,
          targetTable: table.name,
        });
      }
    } catch { /* ignore invalid drag data */ }
  });

  return card;
}

function _renderColumnRow(tableName, col, sourceMapping) {
  const badges = [];
  if (col.isPrimaryKey) badges.push('<span class="builder-badge builder-badge--pk">PK</span>');
  if (col.isUnique) badges.push('<span class="builder-badge builder-badge--uq">UQ</span>');
  if (!col.nullable) badges.push('<span class="builder-badge builder-badge--nn">NN</span>');
  if (col.identity) badges.push('<span class="builder-badge builder-badge--identity">ID</span>');

  // Check if this column has FK constraint
  const schema = getTargetSchema();
  const table = schema.tables.find(t => t.name === tableName);
  if (table) {
    const hasFk = table.constraints.some(c =>
      c.type === 'fk' && c.columns.includes(col.name)
    );
    if (hasFk) badges.push('<span class="builder-badge builder-badge--fk">FK</span>');
  }

  const mappingKey = `${tableName}.${col.name}`;
  const mapping = sourceMapping[mappingKey];
  const mappingHtml = mapping
    ? `<span class="builder-mapping__source" title="Mapped from ${escapeHtml(mapping.sourceTable)}.${escapeHtml(mapping.sourceColumn)}">&#8592;</span>`
    : '';

  return `
    <div class="builder-column-row" data-column="${escapeHtml(col.name)}">
      <span class="builder-column-row__grip">&#8942;&#8942;</span>
      <input class="builder-column-row__name" value="${escapeHtml(col.name)}" spellcheck="false">
      <button class="builder-column-row__type-btn">${escapeHtml(col.type)}</button>
      <div class="builder-column-row__badges">${badges.join('')}${mappingHtml}</div>
      <button class="builder-column-row__edit" title="Edit column">&#9998;</button>
      <button class="builder-column-row__delete" title="Remove column">&times;</button>
    </div>
  `;
}

function _constraintLabel(c) {
  if (c.type === 'pk') return `PK: ${c.columns.join(', ')}`;
  if (c.type === 'fk') return `FK: ${c.columns.join(', ')} → ${c.refTable}.${c.refColumns.join(', ')}`;
  if (c.type === 'unique') return `UQ: ${c.columns.join(', ')}`;
  if (c.type === 'check') return `CHK: ${c.expression}`;
  return c.name;
}

function _constraintWarning(c, table) {
  const schema = getTargetSchema();

  // FK: check target table and column exist
  if (c.type === 'fk') {
    const refTable = schema.tables.find(t => t.name === c.refTable);
    if (!refTable) return `Referenced table "${c.refTable}" does not exist`;
    const refColNames = new Set(refTable.columns.map(col => col.name));
    for (const rc of c.refColumns) {
      if (!refColNames.has(rc)) return `Referenced column "${c.refTable}.${rc}" does not exist`;
    }
    // Check source columns exist in this table
    const srcColNames = new Set(table.columns.map(col => col.name));
    for (const sc of c.columns) {
      if (!srcColNames.has(sc)) return `Source column "${sc}" does not exist in this table`;
    }
  }

  // PK/Unique: check columns exist
  if (c.type === 'pk' || c.type === 'unique') {
    const colNames = new Set(table.columns.map(col => col.name));
    for (const col of c.columns) {
      if (!colNames.has(col)) return `Column "${col}" does not exist in this table`;
    }
  }

  // Duplicate PK
  if (c.type === 'pk') {
    const pkCount = table.constraints.filter(x => x.type === 'pk').length;
    if (pkCount > 1) return 'Multiple PRIMARY KEY constraints — only one allowed per table';
  }

  return '';
}

let editingEnumName = null;

function renderEnumCards(enums) {
  const container = document.getElementById('target-enums');
  if (!container) return;
  container.innerHTML = '';

  for (const e of enums) {
    const isEditing = editingEnumName === e.name;
    const card = document.createElement('div');
    card.className = 'builder-enum-card' + (isEditing ? ' builder-enum-card--editing' : '');

    if (isEditing) {
      card.innerHTML = `
        <div class="builder-enum-editor">
          <div class="builder-enum-editor__row">
            <label>Name</label>
            <input type="text" class="builder-enum-editor__name" value="${escapeHtml(e.name)}" spellcheck="false" />
          </div>
          <div class="builder-enum-editor__row">
            <label>Values <span class="builder-enum-editor__hint">(one per line)</span></label>
            <textarea class="builder-enum-editor__values" rows="${Math.max(3, e.values.length + 1)}" spellcheck="false">${e.values.map(v => escapeHtml(v)).join('\n')}</textarea>
          </div>
          <div class="builder-enum-editor__actions">
            <button class="builder-btn builder-btn--small builder-btn--primary builder-enum-editor__save">Save</button>
            <button class="builder-btn builder-btn--small builder-btn--secondary builder-enum-editor__cancel">Cancel</button>
          </div>
        </div>
      `;

      const saveBtn = card.querySelector('.builder-enum-editor__save');
      const cancelBtn = card.querySelector('.builder-enum-editor__cancel');
      const nameInput = card.querySelector('.builder-enum-editor__name');
      const valuesArea = card.querySelector('.builder-enum-editor__values');

      saveBtn.addEventListener('click', () => {
        const newName = nameInput.value.trim();
        const newValues = valuesArea.value.split('\n').map(v => v.trim()).filter(Boolean);
        if (!newName) { showToast('Enum name cannot be empty'); return; }
        if (newValues.length === 0) { showToast('Enum must have at least one value'); return; }
        const schema = getTargetSchema();
        if (newName !== e.name && schema.enums.some(x => x.name === newName)) {
          showToast(`Enum "${newName}" already exists`); return;
        }
        updateEnum(e.name, { name: newName, values: newValues });
        editingEnumName = null;
        renderEnumCards(getTargetSchema().enums);
      });

      cancelBtn.addEventListener('click', () => {
        editingEnumName = null;
        renderEnumCards(getTargetSchema().enums);
      });
    } else {
      card.innerHTML = `
        <span class="builder-enum-card__name">${escapeHtml(e.name)}</span>
        <span class="builder-enum-card__values">(${e.values.map(v => escapeHtml(v)).join(', ')})</span>
        <button class="builder-enum-card__edit" title="Edit enum">&#9998;</button>
        <button class="builder-enum-card__delete" title="Remove enum">&times;</button>
      `;

      card.querySelector('.builder-enum-card__edit').addEventListener('click', () => {
        editingEnumName = e.name;
        renderEnumCards(enums);
      });

      card.querySelector('.builder-enum-card__delete').addEventListener('click', () => {
        showConfirm(`Delete enum type "${e.name}"?`, () => removeEnum(e.name));
      });
    }

    container.appendChild(card);
  }
}

// ---- Init ----

export function initPanels() {
  // Add table button
  document.getElementById('btn-add-table')?.addEventListener('click', () => {
    const schema = getTargetSchema();
    const name = `table_${schema.tables.length + 1}`;
    const table = {
      ...DEFAULT_TABLE,
      name,
      columns: [
        { ...DEFAULT_COLUMN, name: 'id', type: 'bigint', nullable: false, identity: 'ALWAYS', isPrimaryKey: true },
      ],
      constraints: [{ type: 'pk', columns: ['id'], name: `${name}_pkey` }],
    };
    addTable(table);
  });

  // Add enum button
  document.getElementById('btn-add-enum')?.addEventListener('click', () => {
    const schema = getTargetSchema();
    const name = `enum_${schema.enums.length + 1}`;
    addEnum({ name, values: ['value_1', 'value_2'] });
  });
}
