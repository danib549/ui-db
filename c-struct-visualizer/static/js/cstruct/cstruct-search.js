/**
 * cstruct-search.js — Search index, filter logic, and toolbar interactions.
 * Manages the search/filter toolbar above the canvas.
 */

import { EventBus } from '../events.js';
import {
  getAllEntities, getConnections, getState,
  getActiveTypeFilters, getActiveFileFilters, getFocusedEntity,
  getHiddenEntities,
  setActiveTypeFilters, setActiveFileFilters, setFocusedEntity,
  clearAllFilters, getShowStdlib, setShowStdlib,
  setSelectedEntity, getSelectedEntity,
} from './cstruct-state.js';

// ---- Search index ----
let searchIndex = [];
let debounceTimer = null;

function buildSearchIndex() {
  searchIndex = [];
  const entities = getAllEntities();
  const state = getState();

  // Also include stdlib-filtered entities for complete index
  const allEntities = [...state.structs, ...state.unions, ...state.functions];

  for (const entity of allEntities) {
    const displayName = entity.displayName || entity.name;
    const entityType = entity.isFunction ? 'function' : entity.isUnion ? 'union' : 'struct';

    // Index the entity itself
    searchIndex.push({
      type: entityType,
      name: entity.name,
      displayName,
      label: displayName,
      sourceFile: entity.sourceFile || null,
      entityName: entity.name,
      matchField: null,
    });

    // Index fields/params (all categories: integer, float, pointer, array, struct, bitfield, enum)
    const fields = entity.fields || [];
    for (const field of fields) {
      if (field.category === 'padding') continue;
      const bitInfo = field.bitSize ? `:${field.bitSize}` : '';
      searchIndex.push({
        type: 'field',
        name: field.name,
        displayName: `${displayName}.${field.name}`,
        label: `${field.name}${bitInfo} : ${field.type}`,
        sourceFile: entity.sourceFile || null,
        entityName: entity.name,
        matchField: field.name,
        fieldType: field.type,
        category: field.category || 'integer',
      });
    }
  }

  // Index enums
  for (const en of (state.enums || [])) {
    searchIndex.push({
      type: 'enum',
      name: en.name,
      displayName: en.name,
      label: en.name,
      sourceFile: en.sourceFile || null,
      entityName: null,
      matchField: null,
    });
    for (const val of (en.values || [])) {
      searchIndex.push({
        type: 'enum-value',
        name: val.name,
        displayName: `${en.name}.${val.name}`,
        label: `${val.name} = ${val.value}`,
        sourceFile: en.sourceFile || null,
        entityName: null,
        matchField: null,
        parentEnum: en.name,
      });
    }
  }
}

function performSearch(query) {
  if (!query || query.length < 1) return [];

  const q = query.toLowerCase();
  const results = [];

  for (const entry of searchIndex) {
    const matchName = entry.name.toLowerCase().includes(q);
    const matchDisplay = entry.displayName.toLowerCase().includes(q);
    const matchType = entry.fieldType && entry.fieldType.toLowerCase().includes(q);
    const matchCategory = entry.category && entry.category.toLowerCase().includes(q);

    if (matchName || matchDisplay || matchType || matchCategory) {
      results.push(entry);
    }
    if (results.length >= 50) break;
  }

  return results;
}

// ---- Filter logic ----

/**
 * Returns a Set of entity names that should be visible on the canvas.
 * Returns null if no filters are active (show everything).
 */
export function getVisibleEntities() {
  const typeFilters = getActiveTypeFilters();
  const fileFilters = getActiveFileFilters();
  const showStdlib = getShowStdlib();
  const hidden = getHiddenEntities();

  const hasTypeFilter = typeFilters !== null;
  const hasFileFilter = fileFilters !== null;
  const hasHidden = Object.keys(hidden).length > 0;

  // If no hard filters active and stdlib is shown, return null (show all)
  if (!hasTypeFilter && !hasFileFilter && !hasHidden && showStdlib) {
    return null;
  }

  const state = getState();
  const allEntities = [...state.structs, ...state.unions, ...state.functions];
  let visible = allEntities;

  // Stdlib filter
  if (!showStdlib) {
    visible = visible.filter(e => !e.isStdlib);
  }

  // Per-entity hidden (sidebar checkboxes)
  if (hasHidden) {
    visible = visible.filter(e => !hidden[e.name]);
  }

  // Type filters
  if (hasTypeFilter) {
    visible = visible.filter(e => {
      if (e.isFunction) return typeFilters.has('function');
      if (e.isUnion) return typeFilters.has('union');
      return typeFilters.has('struct');
    });
  }

  // File filters
  if (hasFileFilter) {
    visible = visible.filter(e => e.sourceFile && fileFilters.has(e.sourceFile));
  }

  return new Set(visible.map(e => e.name));
}

/**
 * Returns a Set of entity names in the focused entity's connected subgraph.
 * Returns null if no focus is active.
 */
export function getFocusedSubgraph() {
  const focused = getFocusedEntity();
  if (!focused) return null;

  const connections = getConnections();
  const connected = new Set([focused]);
  const queue = [focused];
  while (queue.length > 0) {
    const current = queue.shift();
    for (const conn of connections) {
      if (conn.source === current && !connected.has(conn.target)) {
        connected.add(conn.target);
        queue.push(conn.target);
      } else if (conn.target === current && !connected.has(conn.source)) {
        connected.add(conn.source);
        queue.push(conn.source);
      }
    }
  }
  return connected;
}

/**
 * Check if any filter is currently active.
 */
export function hasActiveFilters() {
  return getActiveTypeFilters() !== null
    || getActiveFileFilters() !== null
    || getFocusedEntity() !== null
    || Object.keys(getHiddenEntities()).length > 0;
}

/** Force-select an entity (no toggle). Deselect first if already selected. */
function forceSelectEntity(name) {
  if (getSelectedEntity() === name) {
    // Already selected — just pan
    EventBus.emit('cstructEntitySelected', { name });
    return;
  }
  // If something else is selected, clear it first (setSelectedEntity toggles)
  if (getSelectedEntity() !== null) {
    setSelectedEntity(getSelectedEntity()); // toggles off
  }
  setSelectedEntity(name); // toggles on
}

// ---- Toolbar DOM interactions ----

export function initSearch() {
  EventBus.on('cstructDataLoaded', () => {
    buildSearchIndex();
    showToolbar();
    updateFileFilterDropdown();
    syncStdlibChip();
  });

  const searchInput = document.getElementById('cstruct-search');
  const clearBtn = document.getElementById('search-clear');
  const resultsEl = document.getElementById('search-results');
  const resetBtn = document.getElementById('filter-reset');
  const fileFilterBtn = document.getElementById('file-filter-btn');
  const fileDropdown = document.getElementById('file-filter-dropdown');
  const stdlibChip = document.getElementById('stdlib-chip');

  if (!searchInput) return;

  // Search input — pan camera to first match, don't filter
  searchInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      const query = searchInput.value.trim();
      clearBtn.hidden = !query;
      showSearchResults(query);
      // Select + pan to first matching entity
      if (query) {
        const results = performSearch(query);
        const firstEntity = results.find(r => r.entityName);
        if (firstEntity) {
          forceSelectEntity(firstEntity.entityName);
        }
      }
    }, 150);
  });

  // Clear search
  clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    clearBtn.hidden = true;
    resultsEl.hidden = true;
    // Clear focused entity if trace was active
    setFocusedEntity(null);
    updateResetButton();
  });

  // Type filter chips
  document.querySelectorAll('.filter-chip[data-type]').forEach(chip => {
    chip.addEventListener('click', () => {
      chip.classList.toggle('filter-chip--active');
      updateTypeFilters();
      updateResetButton();
    });
  });

  // Stdlib chip
  if (stdlibChip) {
    stdlibChip.addEventListener('click', () => {
      const newState = !getShowStdlib();
      setShowStdlib(newState);
      syncStdlibChip();
      updateResetButton();
    });
  }

  // Trace checkbox — unchecking clears focused entity
  const traceCheckbox = document.getElementById('search-trace-checkbox');
  if (traceCheckbox) {
    traceCheckbox.addEventListener('change', () => {
      if (!traceCheckbox.checked) {
        setFocusedEntity(null);
      }
      updateResetButton();
    });
  }

  // File filter dropdown
  if (fileFilterBtn) {
    fileFilterBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      fileDropdown.hidden = !fileDropdown.hidden;
    });
    // Close dropdown on click outside
    document.addEventListener('click', () => {
      if (fileDropdown) fileDropdown.hidden = true;
    });
    if (fileDropdown) {
      fileDropdown.addEventListener('click', (e) => e.stopPropagation());
    }
  }

  // Reset all
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      searchInput.value = '';
      clearAllFilters();
      setShowStdlib(false);
      // Re-activate all type chips
      document.querySelectorAll('.filter-chip[data-type]').forEach(c => {
        c.classList.add('filter-chip--active');
      });
      syncStdlibChip();
      resultsEl.hidden = true;
      clearBtn.hidden = true;
      // Uncheck trace checkbox
      const tc = document.getElementById('search-trace-checkbox');
      if (tc) tc.checked = false;
      updateFileFilterDropdown();
      updateResetButton();
    });
  }

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    // '/' to focus search (if not typing in an input)
    if (e.key === '/' && document.activeElement.tagName !== 'INPUT') {
      e.preventDefault();
      searchInput.focus();
    }
    // Escape: clear trace/focus, clear search if focused
    if (e.key === 'Escape') {
      // Always clear focus/trace and selection
      setFocusedEntity(null);
      if (getSelectedEntity()) setSelectedEntity(getSelectedEntity()); // toggle off
      const tc = document.getElementById('search-trace-checkbox');
      if (tc) tc.checked = false;

      if (document.activeElement === searchInput) {
        searchInput.value = '';
        searchInput.blur();
        clearBtn.hidden = true;
      }
      resultsEl.hidden = true;
      updateResetButton();
    }
  });
}

function showToolbar() {
  const toolbar = document.getElementById('cstruct-toolbar');
  if (toolbar) toolbar.hidden = false;
}

function syncStdlibChip() {
  const chip = document.getElementById('stdlib-chip');
  if (!chip) return;
  if (getShowStdlib()) {
    chip.classList.add('filter-chip--active');
  } else {
    chip.classList.remove('filter-chip--active');
  }
}

function updateTypeFilters() {
  const activeTypes = new Set();
  document.querySelectorAll('.filter-chip[data-type]').forEach(chip => {
    if (chip.classList.contains('filter-chip--active')) {
      activeTypes.add(chip.dataset.type);
    }
  });
  // If all types are active, set null (no filter)
  if (activeTypes.size === 3) {
    setActiveTypeFilters(null);
  } else {
    setActiveTypeFilters(activeTypes);
  }
}

function showSearchResults(query) {
  const resultsEl = document.getElementById('search-results');
  if (!query) {
    resultsEl.hidden = true;
    return;
  }

  const results = performSearch(query);
  if (results.length === 0) {
    resultsEl.hidden = true;
    return;
  }

  // Group results by type
  const groups = {};
  for (const r of results) {
    const key = r.type;
    if (!groups[key]) groups[key] = [];
    groups[key].push(r);
  }

  const groupLabels = {
    struct: 'Structs', union: 'Unions', function: 'Functions',
    enum: 'Enums', field: 'Fields', 'enum-value': 'Enum Values',
  };

  let html = '';
  for (const [type, items] of Object.entries(groups)) {
    html += `<div class="search-results__group">`;
    html += `<div class="search-results__group-label">${groupLabels[type] || type}</div>`;
    for (const item of items.slice(0, 10)) {
      const badge = type === 'struct' ? 'S' : type === 'union' ? 'U'
        : type === 'function' ? 'F' : type === 'enum' || type === 'enum-value' ? 'E' : '';
      const badgeClass = type === 'function' ? 'sidebar__badge--function'
        : type === 'union' ? 'sidebar__badge--union'
        : type === 'enum' || type === 'enum-value' ? 'sidebar__badge--enum'
        : 'sidebar__badge--struct';
      const categoryTag = item.category ? ` [${item.category}]` : '';
      const meta = (item.sourceFile || '') + categoryTag;
      const entityAttr = item.entityName ? `data-entity="${item.entityName}"` : '';
      html += `<div class="search-results__item" ${entityAttr}>
        <span class="sidebar__badge ${badgeClass}">${badge}</span>
        <span class="search-results__item-name">${escapeHtml(item.label)}</span>
        <span class="search-results__item-meta">${escapeHtml(meta)}</span>
      </div>`;
    }
    html += `</div>`;
  }

  resultsEl.innerHTML = html;
  resultsEl.hidden = false;

  // Click handlers for results
  resultsEl.querySelectorAll('.search-results__item').forEach(item => {
    item.addEventListener('click', () => {
      const entityName = item.dataset.entity;
      if (entityName) {
        // If trace checkbox is checked, filter to show only this entity + subgraph
        const traceCheckbox = document.getElementById('search-trace-checkbox');
        if (traceCheckbox && traceCheckbox.checked) {
          setFocusedEntity(entityName);
        }
        // Select + pan to entity
        forceSelectEntity(entityName);
      }
      resultsEl.hidden = true;
      updateResetButton();
    });
  });
}

function updateFileFilterDropdown() {
  const dropdown = document.getElementById('file-filter-dropdown');
  if (!dropdown) return;

  const state = getState();
  const allEntities = [...state.structs, ...state.unions, ...state.functions];
  const files = new Set();
  for (const e of allEntities) {
    if (e.sourceFile) files.add(e.sourceFile);
  }

  if (files.size === 0) {
    dropdown.innerHTML = '<div class="file-filter-dropdown__item" style="color:var(--chrome-text-secondary)">No files loaded</div>';
    return;
  }

  const currentFilter = getActiveFileFilters();
  let html = '';
  for (const file of [...files].sort()) {
    const checked = !currentFilter || currentFilter.has(file) ? 'checked' : '';
    html += `<label class="file-filter-dropdown__item">
      <input type="checkbox" value="${escapeHtml(file)}" ${checked}>
      ${escapeHtml(file)}
    </label>`;
  }
  dropdown.innerHTML = html;

  // Bind change events
  dropdown.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', () => {
      const checked = dropdown.querySelectorAll('input:checked');
      const allCbs = dropdown.querySelectorAll('input[type="checkbox"]');
      if (checked.length === allCbs.length) {
        setActiveFileFilters(null);
      } else {
        const selected = new Set();
        checked.forEach(c => selected.add(c.value));
        setActiveFileFilters(selected);
      }
      updateResetButton();
    });
  });
}

function updateResetButton() {
  const btn = document.getElementById('filter-reset');
  if (btn) {
    btn.hidden = !hasActiveFilters();
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
