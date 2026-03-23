/**
 * state.js — Central State Store
 * Single source of truth for the entire application.
 * All mutations emit events via EventBus.
 */

import { EventBus } from './events.js';

const initialState = () => ({
  tables: [],
  positions: {},
  connections: [],
  filters: {},
  viewport: { panX: 0, panY: 0, zoom: 1.0 },
  collapsed: {},
  groups: {},
  selectedTables: [],
  hoveredTable: null,
  hoveredColumn: null,
  hoveredConnection: null,
  activeFilters: [],
  searchQuery: null,
  searchMode: 'contains',
  searchResults: null,
  traceResults: null,
});

const state = initialState();

/** Emit both a specific event and the generic stateChanged event. */
const emitChange = (specificEvent, data, key) => {
  EventBus.emit(specificEvent, data);
  if (specificEvent !== 'stateChanged') {
    EventBus.emit('stateChanged', { key: key || specificEvent });
  }
};

// --------------- Tables ---------------

export const addTable = (table) => {
  state.tables.push(table);
  emitChange('tableAdded', table, 'tables');
};

export const removeTable = (tableName) => {
  state.tables = state.tables.filter((t) => t.name !== tableName);
  delete state.positions[tableName];
  delete state.collapsed[tableName];
  state.connections = state.connections.filter(
    (c) => c.source.table !== tableName && c.target.table !== tableName
  );
  state.selectedTables = state.selectedTables.filter((n) => n !== tableName);
  emitChange('tableRemoved', tableName, 'tables');
};

export const setTables = (tables) => {
  state.tables = tables;
  emitChange('stateChanged', { key: 'tables' }, 'tables');
};

export const getTables = () => [...state.tables];

export const getTableNames = () => state.tables.map((t) => t.name);

// --------------- Positions ---------------

export const moveBlock = (tableName, pos) => {
  state.positions[tableName] = { ...state.positions[tableName], ...pos };
  emitChange('tableMoved', { tableName, pos }, 'positions');
};

export const setPosition = (tableName, pos) => {
  state.positions[tableName] = { ...state.positions[tableName], ...pos };
  // No tableMoved event — used for layout animation
  EventBus.emit('stateChanged', { key: 'positions' });
};

export const setPositions = (positions) => {
  state.positions = { ...positions };
  emitChange('layoutChanged', positions, 'positions');
};

export const getPositions = () => JSON.parse(JSON.stringify(state.positions));

// --------------- Connections ---------------

export const setConnections = (connections) => {
  state.connections = connections;
  emitChange('stateChanged', { key: 'connections' }, 'connections');
};

export const addConnection = (conn) => {
  state.connections.push(conn);
  emitChange('connectionAdded', conn, 'connections');
};

export const removeConnection = (conn) => {
  state.connections = state.connections.filter(
    (c) =>
      !(
        c.source.table === conn.source.table &&
        c.source.column === conn.source.column &&
        c.target.table === conn.target.table &&
        c.target.column === conn.target.column
      )
  );
  emitChange('connectionRemoved', conn, 'connections');
};

export const removeConnectionsForTable = (tableName) => {
  state.connections = state.connections.filter(
    (c) => c.source.table !== tableName && c.target.table !== tableName
  );
  emitChange('stateChanged', { key: 'connections' }, 'connections');
};

export const getConnections = () => [...state.connections];

// --------------- Filters ---------------

export const applyFilter = (filter) => {
  state.activeFilters.push(filter);
  emitChange('filterChanged', state.activeFilters, 'activeFilters');
};

export const clearFilters = () => {
  state.activeFilters = [];
  emitChange('filterChanged', state.activeFilters, 'activeFilters');
};

export const setActiveFilters = (filters) => {
  state.activeFilters = Array.isArray(filters) ? filters : [];
  emitChange('filterChanged', state.activeFilters, 'activeFilters');
};

// --------------- Viewport ---------------

export const setViewport = (viewport) => {
  Object.assign(state.viewport, viewport);
  emitChange('viewportChanged', { ...state.viewport }, 'viewport');
};

export const getViewport = () => ({ ...state.viewport });

// --------------- Collapse ---------------

export const toggleCollapse = (tableName) => {
  const wasCollapsed = !!state.collapsed[tableName];
  state.collapsed[tableName] = !wasCollapsed;
  const event = wasCollapsed ? 'blockExpanded' : 'blockCollapsed';
  emitChange(event, tableName, 'collapsed');
};

// --------------- Groups ---------------

export const setGroups = (groups) => {
  state.groups = { ...groups };
  emitChange('stateChanged', { key: 'groups' }, 'groups');
};

export const getGroups = () => ({ ...state.groups });

// --------------- Search ---------------

export const setSearchResults = (results) => {
  state.searchResults = results;
  emitChange('searchResultsReady', results, 'searchResults');
};

export const clearSearchResults = () => {
  state.searchResults = null;
  state.searchQuery = null;
  emitChange('searchCleared', null, 'searchResults');
};

// --------------- Trace ---------------

export const setTraceResults = (trace) => {
  state.traceResults = trace;
  emitChange('traceResultsReady', trace, 'traceResults');
};

// --------------- Hover / Selection (with no-op guards) ---------------

export const setHoveredTable = (tableName) => {
  if (state.hoveredTable === tableName) return;
  state.hoveredTable = tableName;
  emitChange('stateChanged', { key: 'hoveredTable' }, 'hoveredTable');
};

export const setHoveredColumn = (col) => {
  if (state.hoveredColumn === col) return;
  if (col && state.hoveredColumn && col.table === state.hoveredColumn.table && col.column === state.hoveredColumn.column) return;
  state.hoveredColumn = col;
  emitChange('stateChanged', { key: 'hoveredColumn' }, 'hoveredColumn');
};

export const setHoveredConnection = (conn) => {
  if (state.hoveredConnection === conn) return;
  state.hoveredConnection = conn;
  emitChange('stateChanged', { key: 'hoveredConnection' }, 'hoveredConnection');
};

export const setSelectedTables = (tables) => {
  state.selectedTables = [...tables];
  emitChange('stateChanged', { key: 'selectedTables' }, 'selectedTables');
};

// --------------- Full State ---------------

/** Read-only direct reference — use in render pipeline for performance. Never mutate. */
export const getStateRef = () => state;

/** Deep clone — use only when you need a snapshot (export, undo stack). */
export const getState = () => JSON.parse(JSON.stringify(state));

export const reset = () => {
  const fresh = initialState();
  Object.keys(fresh).forEach((key) => {
    state[key] = fresh[key];
  });
  emitChange('stateReset', null, 'all');
};

export const exportState = getState;

export const importState = (data) => {
  Object.keys(data).forEach((key) => {
    if (key in state) {
      state[key] = data[key];
    }
  });
  emitChange('stateReset', null, 'all');
};
