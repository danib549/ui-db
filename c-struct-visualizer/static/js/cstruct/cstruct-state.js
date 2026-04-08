/**
 * cstruct-state.js — Single source of truth for the C struct visualizer.
 * All mutations go through exported functions. Every mutation emits events.
 */

import { EventBus } from '../events.js';

// ---- Internal state ----
const state = {
  structs: [],        // [{name, totalSize, alignment, packed, isUnion:false, fields:[...]}]
  unions: [],         // [{name, totalSize, alignment, packed, isUnion:true, fields:[...]}]
  functions: [],      // [{name, returnType, returnStruct, isFunction:true, params:[...], fields:[...]}]
  typedefs: {},       // {typedef_name: canonical_name}
  enums: [],          // [{name, values:[{name, value}]}]
  connections: [],    // [{source, target, type:'nested'|'param'|'return'|'uses'|'call', field}]
  positions: {},      // {entityName: {x, y, width, height}}
  viewport: { panX: 0, panY: 0, zoom: 1.0 },
  collapsed: {},      // {entityName: true}
  hoveredEntity: null,
  hoveredField: null, // {entity, fieldIndex}
  selectedEntity: null,
  targetArch: 'arm',
  endianness: 'little',
  warnings: [],
  showStdlib: false,  // Whether to show standard C library items in sidebar
  fileContents: {},   // {filename: sourceCodeString} — for source preview modal
  searchQuery: '',
  activeTypeFilters: null,  // null = show all, Set(['struct','union',...]) = show only these
  activeFileFilters: null,  // null = show all, Set(['sensor.h',...]) = show only these
  focusedEntity: null,      // entity name for connection-based filtering (show it + its graph)
  hiddenEntities: {},       // {entityName: true} — per-entity visibility toggle from sidebar
  activeLayout: 'top-down', // current layout mode
  fileContainers: {},       // {filename: {x, y, width, height}} — for by-file layout
  showCallConnections: false, // whether to show function-to-function call lines
  showDepConnections: true,   // whether to show struct dependency lines (nested, param, return, uses)
  globals: [],          // [{name, type, storage, sourceFile, structRef}]
  macros: [],           // [{name, value, sourceFile}]
  includes: [],         // [{source, target, line, depth}]
  callGraphRoot: null,  // entity name for call graph focus
  callGraphDepth: 2,    // max BFS depth for call graph
  memoryMapEntity: null, // entity name for byte-level memory map view
};

// ---- Getters (read-only access) ----

export function getState() {
  return state;
}

export function getStructs() {
  return state.structs;
}

export function getUnions() {
  return state.unions;
}

export function getFunctions() {
  return state.functions;
}

export function getAllEntities() {
  const all = [...state.structs, ...state.unions, ...state.functions];
  if (!state.showStdlib) {
    return all.filter(e => !e.isStdlib);
  }
  return all;
}

export function getShowStdlib() {
  return state.showStdlib;
}

export function setShowStdlib(show) {
  state.showStdlib = show;
  EventBus.emit('cstructStateChanged', { key: 'showStdlib' });
}

export function getEntity(name) {
  return state.structs.find(s => s.name === name)
    || state.unions.find(u => u.name === name)
    || state.functions.find(f => f.name === name);
}

export function getTypedefs() {
  return state.typedefs;
}

export function getEnums() {
  return state.enums;
}

export function getConnections() {
  return state.connections;
}

export function getPositions() {
  return state.positions;
}

export function getPosition(name) {
  return state.positions[name] || null;
}

export function getViewport() {
  return state.viewport;
}

export function isCollapsed(name) {
  return !!state.collapsed[name];
}

export function getHoveredEntity() {
  return state.hoveredEntity;
}

export function getHoveredField() {
  return state.hoveredField;
}

export function getSelectedEntity() {
  return state.selectedEntity;
}

export function getTargetArch() {
  return state.targetArch;
}

export function getEndianness() {
  return state.endianness;
}

export function getWarnings() {
  return state.warnings;
}

export function getFileContents() {
  return state.fileContents;
}

export function getFileContent(filename) {
  return state.fileContents[filename] || null;
}

export function getSearchQuery() {
  return state.searchQuery;
}

export function getActiveTypeFilters() {
  return state.activeTypeFilters;
}

export function getActiveFileFilters() {
  return state.activeFileFilters;
}

export function getFocusedEntity() {
  return state.focusedEntity;
}

export function getHiddenEntities() {
  return state.hiddenEntities;
}

export function getActiveLayout() {
  return state.activeLayout;
}

export function getFileContainers() {
  return state.fileContainers;
}

export function getShowCallConnections() {
  return state.showCallConnections;
}

export function getShowDepConnections() {
  return state.showDepConnections;
}

export function getGlobals() {
  return state.globals;
}

export function getMacros() {
  return state.macros;
}

export function getIncludes() {
  return state.includes;
}

export function getCallGraphRoot() {
  return state.callGraphRoot;
}

export function getCallGraphDepth() {
  return state.callGraphDepth;
}

export function getMemoryMapEntity() {
  return state.memoryMapEntity;
}

// ---- Mutators ----

export function loadParseResult(result) {
  state.structs = result.structs || [];
  state.unions = result.unions || [];
  state.typedefs = result.typedefs || {};
  state.enums = result.enums || [];
  state.connections = result.connections || [];
  state.warnings = result.warnings || [];
  state.fileContents = result.fileContents || {};
  state.collapsed = {};
  state.hoveredEntity = null;
  state.hoveredField = null;
  state.selectedEntity = null;
  state.searchQuery = '';
  state.activeTypeFilters = null;
  state.activeFileFilters = null;
  state.focusedEntity = null;
  state.hiddenEntities = {};
  state.fileContainers = {};
  state.globals = result.globals || [];
  state.macros = result.macros || [];
  state.includes = result.includes || [];
  state.callGraphRoot = null;
  state.callGraphDepth = 2;
  state.memoryMapEntity = null;

  // Map functions: create a fields array from params so block drawing works
  state.functions = (result.functions || []).map(f => ({
    ...f,
    isFunction: true,
    fields: (f.params || []).map(p => ({
      name: p.name || '(unnamed)',
      type: p.type,
      category: p.category || (p.refStruct ? (p.isPointer ? 'pointer' : 'struct') : 'integer'),
      refStruct: p.refStruct || null,
      offset: null,
      size: null,
      bitOffset: null,
      bitSize: null,
    })),
  }));

  if (result.target_info) {
    state.targetArch = result.target_info.key || 'arm';
    state.endianness = result.target_info.endianness || 'little';
  }

  const count = state.structs.length + state.unions.length + state.functions.length;
  EventBus.emit('cstructDataLoaded', { count });
  EventBus.emit('cstructStateChanged', { key: 'all' });
}

export function setPositions(positions) {
  state.positions = positions;
  EventBus.emit('cstructStateChanged', { key: 'positions' });
}

export function setPosition(name, pos) {
  state.positions[name] = pos;
  EventBus.emit('cstructStateChanged', { key: 'positions' });
}

export function setViewport(viewport) {
  state.viewport = { ...state.viewport, ...viewport };
  EventBus.emit('cstructStateChanged', { key: 'viewport' });
}

export function toggleCollapsed(name) {
  state.collapsed[name] = !state.collapsed[name];
  EventBus.emit('cstructBlockToggled', { name, collapsed: state.collapsed[name] });
  EventBus.emit('cstructStateChanged', { key: 'collapsed' });
}

export function setHoveredEntity(name) {
  if (state.hoveredEntity === name) return;
  state.hoveredEntity = name;
  EventBus.emit('cstructStateChanged', { key: 'hoveredEntity' });
}

export function setHoveredField(entity, fieldIndex) {
  state.hoveredField = entity ? { entity, fieldIndex } : null;
  EventBus.emit('cstructStateChanged', { key: 'hoveredField' });
}

export function setSelectedEntity(name) {
  state.selectedEntity = name === state.selectedEntity ? null : name;
  EventBus.emit('cstructEntitySelected', { name: state.selectedEntity });
  EventBus.emit('cstructStateChanged', { key: 'selectedEntity' });
}

export function setTargetArch(arch) {
  state.targetArch = arch;
  EventBus.emit('cstructStateChanged', { key: 'targetArch' });
}

export function setSearchQuery(query) {
  state.searchQuery = query;
  EventBus.emit('cstructStateChanged', { key: 'searchQuery' });
}

export function setActiveTypeFilters(filterSet) {
  state.activeTypeFilters = filterSet;
  EventBus.emit('cstructStateChanged', { key: 'activeTypeFilters' });
}

export function setActiveFileFilters(filterSet) {
  state.activeFileFilters = filterSet;
  EventBus.emit('cstructStateChanged', { key: 'activeFileFilters' });
}

export function setFocusedEntity(name) {
  state.focusedEntity = name;
  EventBus.emit('cstructStateChanged', { key: 'focusedEntity' });
}

export function toggleEntityVisibility(name) {
  if (state.hiddenEntities[name]) {
    delete state.hiddenEntities[name];
  } else {
    state.hiddenEntities[name] = true;
  }
  EventBus.emit('cstructStateChanged', { key: 'hiddenEntities' });
}

export function isEntityHidden(name) {
  return !!state.hiddenEntities[name];
}

export function setActiveLayout(layout) {
  state.activeLayout = layout;
  EventBus.emit('cstructStateChanged', { key: 'activeLayout' });
}

export function setFileContainers(containers) {
  state.fileContainers = containers;
  EventBus.emit('cstructStateChanged', { key: 'fileContainers' });
}

export function setShowCallConnections(show) {
  state.showCallConnections = show;
  EventBus.emit('cstructStateChanged', { key: 'showCallConnections' });
}

export function setShowDepConnections(show) {
  state.showDepConnections = show;
  EventBus.emit('cstructStateChanged', { key: 'showDepConnections' });
}

export function setCallGraphRoot(name) {
  state.callGraphRoot = name;
  EventBus.emit('cstructStateChanged', { key: 'callGraphRoot' });
}

export function setCallGraphDepth(depth) {
  state.callGraphDepth = depth;
  EventBus.emit('cstructStateChanged', { key: 'callGraphDepth' });
}

export function setMemoryMapEntity(name) {
  state.memoryMapEntity = name;
  EventBus.emit('cstructStateChanged', { key: 'memoryMapEntity' });
}

export function clearAllFilters() {
  state.searchQuery = '';
  state.activeTypeFilters = null;
  state.activeFileFilters = null;
  state.focusedEntity = null;
  state.hiddenEntities = {};
  state.selectedEntity = null;
  EventBus.emit('cstructStateChanged', { key: 'filters' });
}

export function resetState() {
  state.structs = [];
  state.unions = [];
  state.functions = [];
  state.typedefs = {};
  state.enums = [];
  state.connections = [];
  state.positions = {};
  state.viewport = { panX: 0, panY: 0, zoom: 1.0 };
  state.collapsed = {};
  state.hoveredEntity = null;
  state.hoveredField = null;
  state.selectedEntity = null;
  state.warnings = [];
  state.fileContents = {};
  state.searchQuery = '';
  state.activeTypeFilters = null;
  state.activeFileFilters = null;
  state.focusedEntity = null;
  state.hiddenEntities = {};
  state.fileContainers = {};
  state.showCallConnections = false;
  state.showDepConnections = true;
  state.globals = [];
  state.macros = [];
  state.includes = [];
  state.callGraphRoot = null;
  state.callGraphDepth = 2;
  state.memoryMapEntity = null;
  EventBus.emit('cstructStateChanged', { key: 'all' });
}
