/**
 * builder-editors.js — Table editor + column editor modal UI.
 */

import { EventBus } from '../events.js';
import { escapeHtml } from '../utils.js';
import {
  findTable, updateColumn, clearActiveEditor, getActiveEditor,
  addConstraint, removeConstraint, getTargetSchema,
} from './builder-state.js';
import {
  PG_TYPE_CATEGORIES, PG_TYPE_DESCRIPTIONS, PG_TYPE_PARAMS, IDENTITY_OPTIONS,
  DEFERRABLE_OPTIONS,
} from './builder-constants.js';

// ---- Column Editor ----

export function initEditors() {
  EventBus.on('builderOpenColumnEditor', openColumnEditor);

  document.getElementById('editor-close')?.addEventListener('click', closeColumnEditor);
  document.getElementById('editor-cancel')?.addEventListener('click', closeColumnEditor);
  document.getElementById('editor-apply')?.addEventListener('click', applyColumnEditor);

  // Close on backdrop click
  document.querySelector('.builder-column-editor__backdrop')?.addEventListener('click', closeColumnEditor);
}

function openColumnEditor({ tableName, columnName }) {
  const table = findTable(tableName);
  if (!table) return;
  const col = table.columns.find(c => c.name === columnName);
  if (!col) return;

  const modal = document.getElementById('column-editor');
  if (!modal) return;

  document.getElementById('editor-table-name').textContent = tableName;
  document.getElementById('editor-col-name').textContent = columnName;

  const body = document.getElementById('editor-body');
  body.innerHTML = _buildEditorForm(col, table);

  // Show/hide params based on type
  _updateTypeParams(body, col.type);

  // Wire up the type picker
  _initTypePicker(body, col.type);

  // Identity change hides default
  const identitySelect = body.querySelector('#editor-identity');
  const defaultField = body.querySelector('#editor-default-field');
  if (identitySelect && defaultField) {
    identitySelect.addEventListener('change', () => {
      defaultField.style.display = identitySelect.value ? 'none' : '';
    });
    defaultField.style.display = identitySelect.value ? 'none' : '';
  }

  // PK toggle auto-unchecks nullable
  const pkCheckbox = body.querySelector('#editor-pk');
  const nullableCheckbox = body.querySelector('#editor-nullable');
  if (pkCheckbox && nullableCheckbox) {
    pkCheckbox.addEventListener('change', () => {
      pkCheckbox.parentElement.classList.toggle('builder-key-toggle--active', pkCheckbox.checked);
      pkCheckbox.parentElement.classList.toggle('builder-key-toggle--pk', pkCheckbox.checked);
      if (pkCheckbox.checked) {
        nullableCheckbox.checked = false;
      }
    });
  }

  // Unique toggle styling
  const uqCheckbox = body.querySelector('#editor-unique');
  if (uqCheckbox) {
    uqCheckbox.addEventListener('change', () => {
      uqCheckbox.parentElement.classList.toggle('builder-key-toggle--active', uqCheckbox.checked);
      uqCheckbox.parentElement.classList.toggle('builder-key-toggle--uq', uqCheckbox.checked);
    });
  }

  // FK toggle shows/hides FK config
  const fkCheckbox = body.querySelector('#editor-fk');
  const fkConfig = body.querySelector('#editor-fk-config');
  if (fkCheckbox && fkConfig) {
    fkCheckbox.addEventListener('change', () => {
      fkConfig.hidden = !fkCheckbox.checked;
      fkCheckbox.parentElement.classList.toggle('builder-key-toggle--active', fkCheckbox.checked);
      fkCheckbox.parentElement.classList.toggle('builder-key-toggle--fk', fkCheckbox.checked);
    });
  }

  // FK ref table change updates ref column options
  const fkTableSelect = body.querySelector('#editor-fk-table');
  const fkColSelect = body.querySelector('#editor-fk-col');
  if (fkTableSelect && fkColSelect) {
    fkTableSelect.addEventListener('change', () => {
      const schema = getTargetSchema();
      fkColSelect.innerHTML = _fkRefColOptions(schema, fkTableSelect.value, '');
    });
  }

  modal.hidden = false;
}

function closeColumnEditor() {
  const modal = document.getElementById('column-editor');
  if (modal) modal.hidden = true;
  clearActiveEditor();
}

function applyColumnEditor() {
  const editor = getActiveEditor();
  if (!editor || editor.type !== 'column') return;

  const body = document.getElementById('editor-body');
  if (!body) return;

  const changes = {};

  const nameInput = body.querySelector('#editor-name');
  if (nameInput) changes.name = nameInput.value.trim();

  const typeInput = body.querySelector('#editor-type');
  if (typeInput) {
    let type = typeInput.value.trim();
    const paramInput = body.querySelector('#editor-type-param');
    if (paramInput && paramInput.value.trim()) {
      type = `${type}(${paramInput.value.trim()})`;
    }
    changes.type = type;
  }

  const nullableInput = body.querySelector('#editor-nullable');
  if (nullableInput) changes.nullable = nullableInput.checked;

  const identityInput = body.querySelector('#editor-identity');
  if (identityInput) changes.identity = identityInput.value || null;

  const defaultInput = body.querySelector('#editor-default');
  if (defaultInput) changes.defaultValue = defaultInput.value.trim() || null;

  const checkInput = body.querySelector('#editor-check');
  if (checkInput) changes.checkExpression = checkInput.value.trim() || null;

  const commentInput = body.querySelector('#editor-comment');
  if (commentInput) changes.comment = commentInput.value.trim() || null;

  const generatedInput = body.querySelector('#editor-generated');
  if (generatedInput) changes.generatedExpression = generatedInput.value.trim() || null;

  // If generated, clear identity and default (mutually exclusive)
  if (changes.generatedExpression) {
    changes.identity = null;
    changes.defaultValue = null;
  }

  // Sync key toggles with column properties
  const pkInput = body.querySelector('#editor-pk');
  const uqInput = body.querySelector('#editor-unique');
  if (pkInput) changes.isPrimaryKey = pkInput.checked;
  if (uqInput) changes.isUnique = uqInput.checked;

  updateColumn(editor.table, editor.column, changes);

  // Handle key constraint changes
  const table = findTable(editor.table);
  const colName = changes.name || editor.column;

  if (table) {
    _applyKeyToggle(table, colName, 'pk', pkInput);
    _applyKeyToggle(table, colName, 'unique', uqInput);
    _applyFKToggle(table, colName, body);
  }

  closeColumnEditor();
}

function _applyKeyToggle(table, colName, constraintType, checkbox) {
  if (!checkbox) return;
  const wantKey = checkbox.checked;
  const suffix = constraintType === 'pk' ? 'pkey' : `${colName}_key`;
  const expectedName = `${table.name}_${suffix}`;

  const existing = table.constraints.find(c =>
    c.type === constraintType && c.columns.includes(colName)
  );

  if (wantKey && !existing) {
    addConstraint(table.name, {
      type: constraintType,
      columns: [colName],
      name: expectedName,
    });
  } else if (!wantKey && existing) {
    removeConstraint(table.name, existing.name);
  }
}

function _applyFKToggle(table, colName, body) {
  const fkCheckbox = body.querySelector('#editor-fk');
  if (!fkCheckbox) return;
  const wantFK = fkCheckbox.checked;

  const existing = table.constraints.find(c =>
    c.type === 'fk' && c.columns.includes(colName)
  );

  if (wantFK) {
    const refTable = body.querySelector('#editor-fk-table')?.value;
    const refCol = body.querySelector('#editor-fk-col')?.value;
    const onDelete = body.querySelector('#editor-fk-ondelete')?.value || 'NO ACTION';
    const deferrable = body.querySelector('#editor-fk-deferrable')?.value || '';

    if (!refTable || !refCol) return;

    if (existing) {
      removeConstraint(table.name, existing.name);
    }
    addConstraint(table.name, {
      type: 'fk',
      columns: [colName],
      refTable,
      refColumns: [refCol],
      onDelete,
      deferrable,
      onUpdate: 'NO ACTION',
      name: `${table.name}_${colName}_fkey`,
    });
  } else if (!wantFK && existing) {
    removeConstraint(table.name, existing.name);
  }
}

function _buildEditorForm(col, table) {
  const baseType = col.type.split('(')[0].trim();
  const paramMatch = col.type.match(/\((.+)\)/);
  const paramValue = paramMatch ? paramMatch[1] : '';
  const paramInfo = PG_TYPE_PARAMS[baseType];

  // Determine current key states from table constraints
  const isPK = col.isPrimaryKey || table.constraints.some(c =>
    c.type === 'pk' && c.columns.includes(col.name)
  );
  const isUnique = col.isUnique || table.constraints.some(c =>
    c.type === 'unique' && c.columns.includes(col.name)
  );
  const fkConstraint = table.constraints.find(c =>
    c.type === 'fk' && c.columns.includes(col.name)
  );
  const isFK = !!fkConstraint;

  // Build FK reference table options
  const schema = getTargetSchema();
  const fkRefTable = fkConstraint ? fkConstraint.refTable : '';
  const fkRefCol = fkConstraint ? (fkConstraint.refColumns[0] || '') : '';
  const fkOnDelete = fkConstraint ? (fkConstraint.onDelete || 'NO ACTION') : 'NO ACTION';
  const fkDeferrable = fkConstraint ? (fkConstraint.deferrable || '') : '';

  // Smart recommendations based on column name and current config
  const recs = _getRecommendations(col, table, baseType);

  return `
    ${recs ? `<div class="builder-rec">${recs}</div>` : ''}

    <div class="builder-field">
      <label for="editor-name">Column Name
        <span class="builder-info" data-tooltip="Use snake_case (e.g. first_name). Max 63 chars. Avoid PostgreSQL reserved words like user, order, group.">?</span>
      </label>
      <input type="text" id="editor-name" class="builder-field__input" value="${escapeHtml(col.name)}">
      <span class="builder-field__hint">snake_case, max 63 chars</span>
    </div>

    <div class="builder-field">
      <label for="editor-type">Data Type
        <span class="builder-info" data-tooltip="Click to browse all 60+ PostgreSQL types grouped by category. Type to search. Common choices: bigint (IDs), text/varchar (strings), timestamptz (dates), boolean, uuid, jsonb.">?</span>
      </label>
      <div class="builder-type-picker" id="editor-type-picker">
        <input type="text" id="editor-type" class="builder-type-picker__search"
               value="${escapeHtml(baseType)}" autocomplete="off" spellcheck="false"
               placeholder="Search types...">
        <div class="builder-type-picker__dropdown" id="editor-type-dropdown">
          ${_buildTypeDropdown(baseType)}
        </div>
      </div>
    </div>

    <div class="builder-field" id="editor-type-param-field" ${paramInfo ? '' : 'hidden'}>
      <label for="editor-type-param">${paramInfo ? paramInfo.label : 'Parameter'}
        <span class="builder-info" data-tooltip="varchar(255) = max 255 chars. numeric(10,2) = 10 total digits, 2 after decimal. Leave blank for unlimited (text) or default precision.">?</span>
      </label>
      <input type="text" id="editor-type-param" class="builder-field__input builder-field__input--small"
             value="${escapeHtml(paramValue)}" placeholder="${paramInfo ? paramInfo.default : ''}">
    </div>

    <div class="builder-field">
      <label class="builder-field__section-label">Keys &amp; Constraints
        <span class="builder-info" data-tooltip="Define how this column relates to the rest of your schema. Every table should have a Primary Key. Foreign Keys create relationships between tables.">?</span>
      </label>
      <div class="builder-key-toggles">
        <label class="builder-key-toggle ${isPK ? 'builder-key-toggle--active builder-key-toggle--pk' : ''}">
          <input type="checkbox" id="editor-pk" ${isPK ? 'checked' : ''}> <span class="builder-key-toggle__badge">PK</span> Primary Key
          <span class="builder-key-toggle__hint">Uniquely identifies each row</span>
        </label>
        <label class="builder-key-toggle ${isUnique ? 'builder-key-toggle--active builder-key-toggle--uq' : ''}">
          <input type="checkbox" id="editor-unique" ${isUnique ? 'checked' : ''}> <span class="builder-key-toggle__badge">UQ</span> Unique
          <span class="builder-key-toggle__hint">No duplicate values allowed</span>
        </label>
        <label class="builder-key-toggle ${isFK ? 'builder-key-toggle--active builder-key-toggle--fk' : ''}">
          <input type="checkbox" id="editor-fk" ${isFK ? 'checked' : ''}> <span class="builder-key-toggle__badge">FK</span> Foreign Key
          <span class="builder-key-toggle__hint">References a row in another table</span>
        </label>
      </div>
    </div>

    <div class="builder-field builder-fk-config" id="editor-fk-config" ${isFK ? '' : 'hidden'}>
      <div class="builder-field">
        <label for="editor-fk-table">References Table
          <span class="builder-info" data-tooltip="The parent table this column points to. The referenced column is usually the primary key of that table.">?</span>
        </label>
        <select id="editor-fk-table" class="builder-field__select">
          <option value="">-- select table --</option>
          ${schema.tables.map(t =>
            `<option value="${escapeHtml(t.name)}" ${t.name === fkRefTable ? 'selected' : ''}>${escapeHtml(t.name)}</option>`
          ).join('')}
        </select>
      </div>
      <div class="builder-field">
        <label for="editor-fk-col">References Column</label>
        <select id="editor-fk-col" class="builder-field__select">
          ${_fkRefColOptions(schema, fkRefTable, fkRefCol)}
        </select>
      </div>
      <div class="builder-field">
        <label for="editor-fk-ondelete">ON DELETE
          <span class="builder-info" data-tooltip="What happens when the referenced row is deleted:\n\nNO ACTION — block the delete (default)\nCASCADE — delete this row too\nSET NULL — set this column to NULL\nRESTRICT — block immediately\nSET DEFAULT — reset to default value">?</span>
        </label>
        <select id="editor-fk-ondelete" class="builder-field__select">
          ${['NO ACTION', 'CASCADE', 'SET NULL', 'SET DEFAULT', 'RESTRICT'].map(a =>
            `<option value="${a}" ${a === fkOnDelete ? 'selected' : ''}>${a}</option>`
          ).join('')}
        </select>
      </div>
      <div class="builder-field">
        <label for="editor-fk-deferrable">Deferrable
          <span class="builder-info" data-tooltip="Controls when the FK constraint is checked.\n\nNot deferrable: checked after each statement (default)\nInitially deferred: checked at COMMIT (useful for bulk inserts with circular FKs)\nInitially immediate: checked per-statement but can be deferred per-transaction with SET CONSTRAINTS">?</span>
        </label>
        <select id="editor-fk-deferrable" class="builder-field__select">
          ${DEFERRABLE_OPTIONS.map(opt =>
            `<option value="${opt.value}" ${fkDeferrable === opt.value ? 'selected' : ''}>${opt.label}</option>`
          ).join('')}
        </select>
      </div>
    </div>

    <div class="builder-field builder-field--toggle">
      <label>
        <input type="checkbox" id="editor-nullable" ${col.nullable ? 'checked' : ''}> Nullable
        <span class="builder-info" data-tooltip="If checked, this column can contain NULL (empty) values. Uncheck to require a value in every row. Primary keys are always NOT NULL.">?</span>
      </label>
    </div>

    <div class="builder-field">
      <label for="editor-identity">Identity
        <span class="builder-info" data-tooltip="Auto-incrementing ID column (PostgreSQL 10+). Preferred over SERIAL. Auto-increment (GENERATED ALWAYS) = PG generates values, cannot override. Auto-increment with override (GENERATED BY DEFAULT) = PG generates, but you can supply manual values.">?</span>
      </label>
      <select id="editor-identity" class="builder-field__select">
        ${IDENTITY_OPTIONS.map(opt =>
          `<option value="${opt.value}" ${col.identity === opt.value || (!col.identity && !opt.value) ? 'selected' : ''}>${opt.label}</option>`
        ).join('')}
      </select>
    </div>

    <div class="builder-field" id="editor-default-field">
      <label for="editor-default">Default Value
        <span class="builder-info" data-tooltip="Value used when no value is provided on INSERT.\n\nExamples:\nNOW() — current timestamp\ngen_random_uuid() — random UUID\n0 — zero\n'pending' — string literal\nTRUE / FALSE — boolean">?</span>
      </label>
      <input type="text" id="editor-default" class="builder-field__input"
             value="${escapeHtml(col.defaultValue || '')}" placeholder="e.g., NOW(), 0, 'pending'">
      <span class="builder-field__hint">Leave empty for no default</span>
    </div>

    <div class="builder-field">
      <label for="editor-generated">Generated / Computed Column
        <span class="builder-info" data-tooltip="A stored computed column (PG 12+). Value is calculated on INSERT/UPDATE and stored on disk.\n\nExamples:\nfirst_name || ' ' || last_name\nprice * quantity\nUPPER(email)\n\nCannot have a DEFAULT or IDENTITY when generated.">?</span>
      </label>
      <input type="text" id="editor-generated" class="builder-field__input"
             value="${escapeHtml(col.generatedExpression || '')}" placeholder='e.g., first_name || &apos; &apos; || last_name'>
      <span class="builder-field__hint">Leave empty for a regular column. Expression is STORED (computed on write).</span>
    </div>

    <div class="builder-field">
      <label for="editor-check">CHECK Expression
        <span class="builder-info" data-tooltip="A boolean expression that must be true for every row.\n\nExamples:\nage >= 0\nprice > 0 AND price < 1000000\nstatus IN ('active', 'inactive')">?</span>
      </label>
      <input type="text" id="editor-check" class="builder-field__input"
             value="${escapeHtml(col.checkExpression || '')}" placeholder='e.g., "age" >= 0'>
    </div>

    <div class="builder-field">
      <label for="editor-comment">Comment
        <span class="builder-info" data-tooltip="A description stored in the database as COMMENT ON COLUMN. Visible in psql and tools like pgAdmin. Good for documenting business meaning.">?</span>
      </label>
      <input type="text" id="editor-comment" class="builder-field__input"
             value="${escapeHtml(col.comment || '')}" placeholder="Column description">
    </div>
  `;
}

function _fkRefColOptions(schema, refTableName, selectedCol) {
  if (!refTableName) return '<option value="">-- select column --</option>';
  const refTable = schema.tables.find(t => t.name === refTableName);
  if (!refTable) return '<option value="">-- select column --</option>';
  return refTable.columns.map(c =>
    `<option value="${escapeHtml(c.name)}" ${c.name === selectedCol ? 'selected' : ''}>${escapeHtml(c.name)}</option>`
  ).join('');
}

function _getRecommendations(col, table, baseType) {
  const tips = [];
  const name = col.name.toLowerCase();

  // ID column recommendations
  if (name === 'id' && !col.identity && !col.isPrimaryKey) {
    tips.push('This looks like a primary key column. Consider enabling <strong>PK</strong>, setting type to <strong>bigint</strong>, and choosing <strong>Auto-increment (GENERATED ALWAYS)</strong> from the Identity dropdown below.');
  }
  if (name.endsWith('_id') && !table.constraints.some(c => c.type === 'fk' && c.columns.includes(col.name))) {
    tips.push('Column name ends with <strong>_id</strong> — is this a foreign key? Enable <strong>FK</strong> and select the referenced table.');
  }

  // Type recommendations
  if (baseType === 'serial' || baseType === 'bigserial' || baseType === 'smallserial') {
    tips.push('SERIAL types are legacy. Prefer type <strong>bigint</strong> + Identity set to <strong>Auto-increment (GENERATED ALWAYS)</strong> (PG 10+).');
  }
  if (baseType === 'timestamp') {
    tips.push('Consider <strong>timestamptz</strong> instead — it stores UTC and handles timezones correctly.');
  }
  if (baseType === 'json') {
    tips.push('Consider <strong>jsonb</strong> instead — it\'s binary, faster to query, and supports GIN indexing.');
  }
  if (baseType === 'money') {
    tips.push('The money type is locale-dependent. Consider <strong>numeric(15,2)</strong> for currency.');
  }
  if (baseType === 'char') {
    tips.push('Fixed-length char pads with spaces. <strong>varchar</strong> or <strong>text</strong> is usually better.');
  }
  if (baseType === 'hstore') {
    tips.push('hstore requires an extension. <strong>jsonb</strong> is the modern alternative with better indexing.');
  }

  // Name-based suggestions
  if ((name === 'email' || name.endsWith('_email')) && baseType !== 'varchar') {
    tips.push('Email columns typically use <strong>varchar(320)</strong> (max RFC 5321 length).');
  }
  if ((name === 'created_at' || name === 'updated_at') && !col.defaultValue) {
    tips.push(`Consider adding default <strong>NOW()</strong> for automatic timestamps.`);
  }
  if (name === 'uuid' || name.endsWith('_uuid') || name === 'external_id') {
    if (baseType !== 'uuid') {
      tips.push('This looks like a UUID column. Consider type <strong>uuid</strong> with default <strong>gen_random_uuid()</strong>.');
    }
  }
  if ((name === 'is_active' || name.startsWith('is_') || name.startsWith('has_')) && baseType !== 'boolean') {
    tips.push('Boolean flag column — consider type <strong>boolean</strong> with default <strong>TRUE</strong> or <strong>FALSE</strong>.');
  }
  if (name === 'status' && baseType === 'text') {
    tips.push('Status columns with limited values work well as a custom <strong>ENUM type</strong> or <strong>varchar</strong> with a CHECK constraint.');
  }

  // Generated column hints
  if (name === 'full_name' || name === 'display_name') {
    tips.push('Consider making this a <strong>Generated Column</strong>: <code>first_name || \' \' || last_name</code>');
  }
  if (name === 'total' || name === 'subtotal' || name === 'line_total') {
    tips.push('If this is computed from other columns, consider a <strong>Generated Column</strong>: <code>price * quantity</code>');
  }

  // Generated + identity/default conflict
  if (col.generatedExpression && col.identity) {
    tips.push('A generated column cannot also have <strong>IDENTITY</strong>. Remove one.');
  }
  if (col.generatedExpression && col.defaultValue) {
    tips.push('A generated column cannot also have a <strong>DEFAULT</strong>. Remove one.');
  }

  if (tips.length === 0) return '';
  return tips.map(t => `<div class="builder-rec__item"><span class="builder-rec__icon">&#9889;</span> ${t}</div>`).join('');
}

function _allTypes() {
  const all = new Set();
  for (const types of Object.values(PG_TYPE_CATEGORIES)) {
    for (const t of types) all.add(t);
  }
  return [...all];
}

function _buildTypeDropdown(selectedType, filter = '') {
  const filterLower = filter.toLowerCase();
  let html = '';

  for (const [category, types] of Object.entries(PG_TYPE_CATEGORIES)) {
    const filtered = types.filter(t =>
      !filterLower || t.toLowerCase().includes(filterLower) ||
      (PG_TYPE_DESCRIPTIONS[t] || '').toLowerCase().includes(filterLower)
    );
    if (filtered.length === 0) continue;

    html += `<div class="builder-type-picker__category">${escapeHtml(category)}</div>`;
    for (const t of filtered) {
      const selected = t === selectedType ? ' builder-type-picker__item--selected' : '';
      const desc = PG_TYPE_DESCRIPTIONS[t] || '';
      html += `
        <div class="builder-type-picker__item${selected}" data-type="${escapeHtml(t)}">
          <span class="builder-type-picker__name">${escapeHtml(t)}</span>
          <span class="builder-type-picker__desc">${escapeHtml(desc)}</span>
        </div>`;
    }
  }

  if (!html) {
    html = '<div class="builder-type-picker__empty">No matching types</div>';
  }

  return html;
}

function _initTypePicker(body, currentType) {
  const input = body.querySelector('#editor-type');
  const dropdown = body.querySelector('#editor-type-dropdown');
  if (!input || !dropdown) return;

  const openDropdown = () => {
    dropdown.classList.add('builder-type-picker__dropdown--open');
    _filterDropdown(dropdown, input.value, currentType);
  };

  const closeDropdown = () => {
    dropdown.classList.remove('builder-type-picker__dropdown--open');
  };

  const selectType = (type) => {
    input.value = type;
    currentType = type;
    closeDropdown();
    _updateTypeParams(body, type);
  };

  // Open on focus/click
  input.addEventListener('focus', openDropdown);
  input.addEventListener('click', openDropdown);

  // Filter as you type
  input.addEventListener('input', () => {
    _filterDropdown(dropdown, input.value, currentType);
    if (!dropdown.classList.contains('builder-type-picker__dropdown--open')) {
      openDropdown();
    }
    _updateTypeParams(body, input.value);
  });

  // Click on dropdown item
  dropdown.addEventListener('mousedown', (e) => {
    // Use mousedown instead of click so it fires before input blur
    const item = e.target.closest('.builder-type-picker__item');
    if (item) {
      e.preventDefault();
      selectType(item.dataset.type);
    }
  });

  // Close on blur (with delay to allow click on dropdown)
  input.addEventListener('blur', () => {
    setTimeout(closeDropdown, 150);
  });

  // Keyboard navigation
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeDropdown();
      input.blur();
      return;
    }

    if (e.key === 'Enter') {
      const highlighted = dropdown.querySelector('.builder-type-picker__item--highlight');
      if (highlighted) {
        e.preventDefault();
        selectType(highlighted.dataset.type);
      } else {
        closeDropdown();
      }
      return;
    }

    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!dropdown.classList.contains('builder-type-picker__dropdown--open')) {
        openDropdown();
        return;
      }
      _navigateDropdown(dropdown, e.key === 'ArrowDown' ? 1 : -1);
    }
  });
}

function _filterDropdown(dropdown, filter, selectedType) {
  dropdown.innerHTML = _buildTypeDropdown(selectedType, filter);
}

function _navigateDropdown(dropdown, direction) {
  const items = [...dropdown.querySelectorAll('.builder-type-picker__item')];
  if (items.length === 0) return;

  const current = dropdown.querySelector('.builder-type-picker__item--highlight');
  let idx = current ? items.indexOf(current) : -1;

  if (current) current.classList.remove('builder-type-picker__item--highlight');

  idx += direction;
  if (idx < 0) idx = items.length - 1;
  if (idx >= items.length) idx = 0;

  items[idx].classList.add('builder-type-picker__item--highlight');
  items[idx].scrollIntoView({ block: 'nearest' });
}

function _updateTypeParams(body, typeStr) {
  const baseType = typeStr.split('(')[0].trim().toLowerCase();
  const paramField = body.querySelector('#editor-type-param-field');
  const paramInput = body.querySelector('#editor-type-param');
  const paramInfo = PG_TYPE_PARAMS[baseType];

  if (paramField) {
    paramField.hidden = !paramInfo;
  }
  if (paramInfo && paramInput) {
    const label = paramField?.querySelector('label');
    if (label) label.textContent = paramInfo.label;
    if (!paramInput.value) paramInput.placeholder = String(paramInfo.default);
  }
}

// ---- Confirmation Dialog ----

let confirmCallback = null;

export function showConfirm(message, onConfirm) {
  const dialog = document.getElementById('confirm-dialog');
  const messageEl = document.getElementById('confirm-message');
  if (!dialog || !messageEl) {
    if (confirm(message)) onConfirm();
    return;
  }

  messageEl.textContent = message;
  confirmCallback = onConfirm;
  dialog.hidden = false;

  const cancelBtn = document.getElementById('confirm-cancel');
  const okBtn = document.getElementById('confirm-ok');

  const cleanup = () => {
    dialog.hidden = true;
    confirmCallback = null;
    cancelBtn?.removeEventListener('click', onCancel);
    okBtn?.removeEventListener('click', onOk);
  };

  const onCancel = () => cleanup();
  const onOk = () => {
    if (confirmCallback) confirmCallback();
    cleanup();
  };

  cancelBtn?.addEventListener('click', onCancel);
  okBtn?.addEventListener('click', onOk);

  document.querySelector('.builder-confirm__backdrop')?.addEventListener('click', onCancel, { once: true });
}

// ---- Toast ----

let toastTimeout;

export function showToast(message) {
  const toast = document.getElementById('builder-toast');
  const msgEl = document.getElementById('builder-toast-message');
  if (!toast || !msgEl) return;

  msgEl.textContent = message;
  toast.classList.add('builder-toast--visible');

  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => {
    toast.classList.remove('builder-toast--visible');
  }, 2000);
}
