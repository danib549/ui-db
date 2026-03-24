/**
 * builder-relationships.js — FK relationship wiring between target tables.
 * Handles source column drops onto target tables for source mapping.
 */

import { EventBus } from '../events.js';
import {
  addColumn, addConstraint, setSourceMapping, findTable,
  getTargetSchema,
} from './builder-state.js';
import { DEFAULT_COLUMN } from './builder-constants.js';

export function initRelationships() {
  EventBus.on('builderSourceDropped', handleSourceDrop);
}

/**
 * Handle a source column dropped onto a target table.
 * Creates a new column in the target table mapped to the source.
 */
function handleSourceDrop({ sourceTable, sourceColumn, targetTable }) {
  const table = findTable(targetTable);
  if (!table) return;

  // Check if column with same name already exists
  const existingCol = table.columns.find(c => c.name === sourceColumn.toLowerCase());
  if (existingCol) {
    // Just map the existing column
    setSourceMapping(`${targetTable}.${existingCol.name}`, {
      sourceTable,
      sourceColumn,
      transform: null,
    });
    return;
  }

  // Create new column with source column name (lowercased for PG convention)
  const colName = sourceColumn.toLowerCase().replace(/[^a-z0-9_]/g, '_');
  const newCol = {
    ...DEFAULT_COLUMN,
    name: colName,
    type: 'text', // will be refined by type-suggest
  };

  addColumn(targetTable, newCol);

  // Set source mapping
  setSourceMapping(`${targetTable}.${colName}`, {
    sourceTable,
    sourceColumn,
    transform: null,
  });

  // Request type suggestion from backend
  suggestType(sourceTable, sourceColumn, targetTable, colName);
}

async function suggestType(sourceTable, sourceColumn, targetTable, targetColumn) {
  try {
    const resp = await fetch('/api/builder/type-suggest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        table: sourceTable,
        column: sourceColumn,
        sourceType: 'VARCHAR',
      }),
    });

    if (!resp.ok) return;

    const suggestion = await resp.json();
    if (suggestion.type && suggestion.type !== 'text') {
      const table = findTable(targetTable);
      if (!table) return;
      const col = table.columns.find(c => c.name === targetColumn);
      if (col) {
        col.type = suggestion.type;
        if (suggestion.nullable !== undefined) col.nullable = suggestion.nullable;
        if (suggestion.identity) col.identity = suggestion.identity;
        EventBus.emit('builderStateChanged', { key: 'columns' });
      }
    }
  } catch {
    // Silent failure — type remains 'text'
  }
}
