/**
 * builder-state.js — Single source of truth for builder schema state.
 * All mutations go through exported functions. Every mutation emits builderStateChanged.
 */

import { EventBus } from '../events.js';

// ---- State ----
const state = {
  targetSchema: {
    name: 'public',
    tables: [],
    enums: [],
  },
  sourceMapping: {},
  activeEditor: null,
  isDirty: false,
};

// originalSchema — frozen snapshot of imported SQL baseline.
// NOT part of reactive state. Module-local only.
// null when building from scratch.
let originalSchema = null;

// ---- Emit helper ----
function emit(key) {
  state.isDirty = true;
  EventBus.emit('builderStateChanged', { key });
}

// ---- Schema getters ----
export function getTargetSchema() {
  return state.targetSchema;
}

export function getSourceMapping() {
  return state.sourceMapping;
}

export function getActiveEditor() {
  return state.activeEditor;
}

export function getIsDirty() {
  return state.isDirty;
}

// ---- Original schema (for diff-based migration) ----
export function setOriginalSchema(schema) {
  originalSchema = structuredClone(schema);
}

export function getOriginalSchema() {
  return originalSchema;
}

export function hasOriginalSchema() {
  return originalSchema !== null;
}

export function clearOriginalSchema() {
  originalSchema = null;
}

// ---- Full schema setters ----
export function setTargetSchema(schema) {
  state.targetSchema = schema;
  emit('targetSchema');
}

export function resetState() {
  state.targetSchema = { name: 'public', tables: [], enums: [] };
  state.sourceMapping = {};
  state.activeEditor = null;
  state.isDirty = false;
  originalSchema = null;
  EventBus.emit('builderStateChanged', { key: 'reset' });
}

// ---- Table mutations ----
export function addTable(table) {
  state.targetSchema.tables.push(table);
  emit('tables');
  EventBus.emit('builderTableAdded', { table });
}

export function removeTable(tableName) {
  state.targetSchema.tables = state.targetSchema.tables.filter(t => t.name !== tableName);
  // Clean source mappings for removed table
  for (const key of Object.keys(state.sourceMapping)) {
    if (key.startsWith(tableName + '.')) {
      delete state.sourceMapping[key];
    }
  }
  emit('tables');
  EventBus.emit('builderTableRemoved', { tableName });
}

export function updateTable(tableName, changes) {
  const table = findTable(tableName);
  if (!table) return;
  Object.assign(table, changes);
  emit('tables');
  EventBus.emit('builderTableUpdated', { tableName, changes });
}

export function findTable(tableName) {
  return state.targetSchema.tables.find(t => t.name === tableName) || null;
}

// ---- Column mutations ----
export function addColumn(tableName, column) {
  const table = findTable(tableName);
  if (!table) return;
  table.columns.push(column);
  emit('columns');
  EventBus.emit('builderColumnAdded', { tableName, column });
}

export function removeColumn(tableName, columnName) {
  const table = findTable(tableName);
  if (!table) return;
  table.columns = table.columns.filter(c => c.name !== columnName);
  // Clean source mapping
  const mappingKey = `${tableName}.${columnName}`;
  delete state.sourceMapping[mappingKey];
  emit('columns');
  EventBus.emit('builderColumnRemoved', { tableName, columnName });
}

export function updateColumn(tableName, columnName, changes) {
  const table = findTable(tableName);
  if (!table) return;
  const col = table.columns.find(c => c.name === columnName);
  if (!col) return;
  Object.assign(col, changes);
  emit('columns');
  EventBus.emit('builderColumnUpdated', { tableName, columnName, changes });
}

// ---- Constraint mutations ----
export function addConstraint(tableName, constraint) {
  const table = findTable(tableName);
  if (!table) return;
  table.constraints.push(constraint);
  emit('constraints');
  EventBus.emit('builderConstraintAdded', { tableName, constraint });
}

export function removeConstraint(tableName, constraintName) {
  const table = findTable(tableName);
  if (!table) return;
  table.constraints = table.constraints.filter(c => c.name !== constraintName);
  emit('constraints');
  EventBus.emit('builderConstraintRemoved', { tableName, constraintName });
}

// ---- Index mutations ----
export function addIndex(tableName, index) {
  const table = findTable(tableName);
  if (!table) return;
  table.indexes.push(index);
  emit('indexes');
}

export function removeIndex(tableName, indexName) {
  const table = findTable(tableName);
  if (!table) return;
  table.indexes = table.indexes.filter(i => i.name !== indexName);
  emit('indexes');
}

// ---- Enum mutations ----
export function addEnum(enumDef) {
  state.targetSchema.enums.push(enumDef);
  emit('enums');
  EventBus.emit('builderEnumAdded', { enum: enumDef });
}

export function removeEnum(enumName) {
  state.targetSchema.enums = state.targetSchema.enums.filter(e => e.name !== enumName);
  emit('enums');
  EventBus.emit('builderEnumRemoved', { enumName });
}

export function updateEnum(enumName, changes) {
  const enumDef = state.targetSchema.enums.find(e => e.name === enumName);
  if (!enumDef) return;
  Object.assign(enumDef, changes);
  emit('enums');
  EventBus.emit('builderEnumUpdated', { enumName, changes });
}

// ---- Source mapping mutations ----
export function setSourceMapping(targetPath, source) {
  state.sourceMapping[targetPath] = source;
  emit('sourceMapping');
  EventBus.emit('builderSourceMapped', { targetPath, source });
}

export function removeSourceMapping(targetPath) {
  delete state.sourceMapping[targetPath];
  emit('sourceMapping');
}

// ---- Active editor ----
export function setActiveEditor(editor) {
  state.activeEditor = editor;
  EventBus.emit('builderStateChanged', { key: 'activeEditor' });
}

export function clearActiveEditor() {
  state.activeEditor = null;
  EventBus.emit('builderStateChanged', { key: 'activeEditor' });
}
