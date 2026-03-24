/**
 * builder-pickers.js — Type selector dropdown + constraint picker + index picker UI.
 */

import { EventBus } from '../events.js';
import { escapeHtml } from '../utils.js';
import {
  findTable, addConstraint, addIndex,
  getTargetSchema,
} from './builder-state.js';
import { FK_ACTIONS, INDEX_TYPES } from './builder-constants.js';

let activeConstraintTable = null;

export function initPickers() {
  EventBus.on('builderOpenConstraintPicker', openConstraintPicker);
  EventBus.on('builderOpenIndexPicker', openIndexPicker);

  document.getElementById('constraint-close')?.addEventListener('click', closeConstraintPicker);
  document.getElementById('constraint-cancel')?.addEventListener('click', closeConstraintPicker);
  document.getElementById('constraint-apply')?.addEventListener('click', applyConstraint);

  document.querySelector('.builder-constraint-picker__backdrop')?.addEventListener('click', closeConstraintPicker);
}

// ---- Constraint Picker ----

function openConstraintPicker({ tableName }) {
  activeConstraintTable = tableName;
  const table = findTable(tableName);
  if (!table) return;

  const modal = document.getElementById('constraint-picker');
  if (!modal) return;

  document.getElementById('constraint-table-name').textContent = tableName;

  const body = document.getElementById('constraint-body');
  body.innerHTML = _buildConstraintForm(table);

  _wireConstraintTabs(body, table);

  modal.hidden = false;
}

function closeConstraintPicker() {
  const modal = document.getElementById('constraint-picker');
  if (modal) modal.hidden = true;
  activeConstraintTable = null;
}

function applyConstraint() {
  if (!activeConstraintTable) return;

  const body = document.getElementById('constraint-body');
  if (!body) return;

  const activeTab = body.querySelector('.builder-constraint-picker__type-select button.active');
  const constraintType = activeTab?.dataset.type || 'pk';
  const table = findTable(activeConstraintTable);
  if (!table) return;

  let constraint = null;

  if (constraintType === 'pk') {
    const cols = _getCheckedColumns(body, 'pk-col-');
    if (cols.length === 0) return;
    const name = body.querySelector('#pk-name')?.value || `${activeConstraintTable}_pkey`;
    constraint = { type: 'pk', columns: cols, name };
  }

  if (constraintType === 'fk') {
    const srcCol = body.querySelector('#fk-src-col')?.value;
    const refTable = body.querySelector('#fk-ref-table')?.value;
    const refCol = body.querySelector('#fk-ref-col')?.value;
    const onDelete = body.querySelector('#fk-on-delete')?.value || 'NO ACTION';
    const onUpdate = body.querySelector('#fk-on-update')?.value || 'NO ACTION';
    const name = body.querySelector('#fk-name')?.value || `${activeConstraintTable}_${srcCol}_fkey`;

    if (!srcCol || !refTable || !refCol) return;
    constraint = {
      type: 'fk', columns: [srcCol], refTable, refColumns: [refCol],
      onDelete, onUpdate, name,
    };
  }

  if (constraintType === 'unique') {
    const cols = _getCheckedColumns(body, 'uq-col-');
    if (cols.length === 0) return;
    const name = body.querySelector('#uq-name')?.value || `${activeConstraintTable}_${cols[0]}_key`;
    constraint = { type: 'unique', columns: cols, name };
  }

  if (constraintType === 'check') {
    const expr = body.querySelector('#check-expr')?.value?.trim();
    if (!expr) return;
    const name = body.querySelector('#check-name')?.value || `${activeConstraintTable}_check`;
    constraint = { type: 'check', expression: expr, columns: [], name };
  }

  if (constraint) {
    addConstraint(activeConstraintTable, constraint);
    closeConstraintPicker();
  }
}

function _buildConstraintForm(table) {
  const schema = getTargetSchema();
  const otherTables = schema.tables.filter(t => t.name !== table.name);

  return `
    <div class="builder-constraint-picker__type-select">
      <button class="active" data-type="pk">Primary Key</button>
      <button data-type="fk">Foreign Key</button>
      <button data-type="unique">Unique</button>
      <button data-type="check">Check</button>
    </div>

    <div id="constraint-form-pk">
      <label>Columns</label>
      <div class="builder-column-select">
        ${table.columns.map(c => `
          <label><input type="checkbox" id="pk-col-${escapeHtml(c.name)}" value="${escapeHtml(c.name)}"> ${escapeHtml(c.name)}</label>
        `).join('')}
      </div>
      <div class="builder-field" style="margin-top:8px">
        <label for="pk-name">Constraint Name</label>
        <input type="text" id="pk-name" class="builder-field__input" value="${table.name}_pkey">
      </div>
    </div>

    <div id="constraint-form-fk" hidden>
      <div class="builder-field">
        <label for="fk-src-col">Column</label>
        <select id="fk-src-col" class="builder-field__select">
          ${table.columns.map(c => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`).join('')}
        </select>
      </div>
      <div class="builder-field">
        <label for="fk-ref-table">References Table</label>
        <select id="fk-ref-table" class="builder-field__select">
          ${schema.tables.map(t => `<option value="${escapeHtml(t.name)}">${escapeHtml(t.name)}</option>`).join('')}
        </select>
      </div>
      <div class="builder-field">
        <label for="fk-ref-col">References Column</label>
        <select id="fk-ref-col" class="builder-field__select" id="fk-ref-col">
          <!-- Updated dynamically -->
        </select>
      </div>
      <div class="builder-field">
        <label for="fk-on-delete">ON DELETE</label>
        <select id="fk-on-delete" class="builder-field__select">
          ${FK_ACTIONS.map(a => `<option value="${a}">${a}</option>`).join('')}
        </select>
      </div>
      <div class="builder-field">
        <label for="fk-on-update">ON UPDATE</label>
        <select id="fk-on-update" class="builder-field__select">
          ${FK_ACTIONS.map(a => `<option value="${a}">${a}</option>`).join('')}
        </select>
      </div>
      <div class="builder-field">
        <label for="fk-name">Constraint Name</label>
        <input type="text" id="fk-name" class="builder-field__input" value="${table.name}_fkey">
      </div>
    </div>

    <div id="constraint-form-unique" hidden>
      <label>Columns</label>
      <div class="builder-column-select">
        ${table.columns.map(c => `
          <label><input type="checkbox" id="uq-col-${escapeHtml(c.name)}" value="${escapeHtml(c.name)}"> ${escapeHtml(c.name)}</label>
        `).join('')}
      </div>
      <div class="builder-field" style="margin-top:8px">
        <label for="uq-name">Constraint Name</label>
        <input type="text" id="uq-name" class="builder-field__input" value="${table.name}_key">
      </div>
    </div>

    <div id="constraint-form-check" hidden>
      <div class="builder-field">
        <label for="check-expr">Expression</label>
        <input type="text" id="check-expr" class="builder-field__input" placeholder='"age" >= 0'>
      </div>
      <div class="builder-field">
        <label for="check-name">Constraint Name</label>
        <input type="text" id="check-name" class="builder-field__input" value="${table.name}_check">
      </div>
    </div>
  `;
}

function _wireConstraintTabs(body, table) {
  const tabs = body.querySelectorAll('.builder-constraint-picker__type-select button');
  const forms = {
    pk: body.querySelector('#constraint-form-pk'),
    fk: body.querySelector('#constraint-form-fk'),
    unique: body.querySelector('#constraint-form-unique'),
    check: body.querySelector('#constraint-form-check'),
  };

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      for (const [key, form] of Object.entries(forms)) {
        if (form) form.hidden = key !== tab.dataset.type;
      }
    });
  });

  // Update FK ref columns when ref table changes
  const refTableSelect = body.querySelector('#fk-ref-table');
  const refColSelect = body.querySelector('#fk-ref-col');
  if (refTableSelect && refColSelect) {
    const updateRefCols = () => {
      const refTableName = refTableSelect.value;
      const refTable = getTargetSchema().tables.find(t => t.name === refTableName);
      refColSelect.innerHTML = (refTable?.columns || []).map(c =>
        `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`
      ).join('');
    };
    refTableSelect.addEventListener('change', updateRefCols);
    updateRefCols();
  }

  // Auto-update FK constraint name
  const srcColSelect = body.querySelector('#fk-src-col');
  const fkNameInput = body.querySelector('#fk-name');
  if (srcColSelect && fkNameInput) {
    srcColSelect.addEventListener('change', () => {
      fkNameInput.value = `${activeConstraintTable}_${srcColSelect.value}_fkey`;
    });
  }
}

function _getCheckedColumns(body, prefix) {
  const checked = [];
  body.querySelectorAll(`input[id^="${prefix}"]`).forEach(cb => {
    if (cb.checked) checked.push(cb.value);
  });
  return checked;
}

// ---- Index Picker (inline prompt) ----

function openIndexPicker({ tableName }) {
  const table = findTable(tableName);
  if (!table) return;

  // Use the constraint picker modal repurposed for indexes
  const cols = table.columns.map(c => c.name);
  if (cols.length === 0) return;

  const colName = cols[0];
  const indexName = `${tableName}_${colName}_idx`;

  addIndex(tableName, {
    name: indexName,
    columns: [colName],
    type: 'btree',
    unique: false,
  });
}
