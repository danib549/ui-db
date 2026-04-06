/**
 * cstruct-state.js — Single source of truth for the C struct visualizer.
 * All mutations go through exported functions. Every mutation emits events.
 */

import { EventBus } from '../events.js';

// ---- Internal state ----
const state = {
  structs: [],        // [{name, totalSize, alignment, packed, isUnion:false, fields:[...]}]
  unions: [],         // [{name, totalSize, alignment, packed, isUnion:true, fields:[...]}]
  typedefs: {},       // {typedef_name: canonical_name}
  enums: [],          // [{name, values:[{name, value}]}]
  connections: [],    // [{source, target, type:'nested', field}]
  positions: {},      // {entityName: {x, y, width, height}}
  viewport: { panX: 0, panY: 0, zoom: 1.0 },
  collapsed: {},      // {entityName: true}
  hoveredEntity: null,
  hoveredField: null, // {entity, fieldIndex}
  selectedEntity: null,
  targetArch: 'arm',
  endianness: 'little',
  warnings: [],
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

export function getAllEntities() {
  return [...state.structs, ...state.unions];
}

export function getEntity(name) {
  return state.structs.find(s => s.name === name)
    || state.unions.find(u => u.name === name);
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

// ---- Mutators ----

export function loadParseResult(result) {
  state.structs = result.structs || [];
  state.unions = result.unions || [];
  state.typedefs = result.typedefs || {};
  state.enums = result.enums || [];
  state.connections = result.connections || [];
  state.warnings = result.warnings || [];
  state.collapsed = {};
  state.hoveredEntity = null;
  state.hoveredField = null;
  state.selectedEntity = null;

  if (result.target_info) {
    state.targetArch = result.target_info.key || 'arm';
    state.endianness = result.target_info.endianness || 'little';
  }

  EventBus.emit('cstructDataLoaded', { count: state.structs.length + state.unions.length });
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

export function resetState() {
  state.structs = [];
  state.unions = [];
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
  EventBus.emit('cstructStateChanged', { key: 'all' });
}
