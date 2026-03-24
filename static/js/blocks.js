/**
 * blocks.js — Table Block Rendering
 * Draws table blocks (header, columns, keys, badges) on the canvas.
 * Reads from state, never writes to it.
 */

import { getStateRef } from './state.js';
import { getContext, applyViewportTransform, isBlockVisible } from './canvas.js';
import {
  BLOCK_MIN_WIDTH, BLOCK_MAX_WIDTH, HEADER_HEIGHT, ROW_HEIGHT,
  PADDING_H, CORNER_RADIUS, KEY_COLORS, BLOCK_COLORS, calculateBlockHeight,
} from './constants.js';

// ---- Shadow/border styles per visual state ----

function getVisualStyle(state) {
  const styles = {
    'default': {
      shadowBlur: 3, shadowOffsetY: 1, shadowColor: 'rgba(0,0,0,0.1)',
      borderColor: BLOCK_COLORS.border, borderWidth: 1, headerFill: BLOCK_COLORS.header, opacity: 1.0,
    },
    'hover': {
      shadowBlur: 6, shadowOffsetY: 4, shadowColor: 'rgba(0,0,0,0.1)',
      borderColor: BLOCK_COLORS.borderHover, borderWidth: 1, headerFill: BLOCK_COLORS.header, opacity: 1.0,
    },
    'selected': {
      shadowBlur: 6, shadowOffsetY: 4, shadowColor: 'rgba(59,130,246,0.15)',
      borderColor: BLOCK_COLORS.borderSelected, borderWidth: 2, headerFill: BLOCK_COLORS.headerSelected, opacity: 1.0,
    },
    'selected-hover': {
      shadowBlur: 6, shadowOffsetY: 4, shadowColor: 'rgba(59,130,246,0.15)',
      borderColor: BLOCK_COLORS.borderSelected, borderWidth: 2, headerFill: BLOCK_COLORS.headerSelected, opacity: 1.0,
    },
    'dragging': {
      shadowBlur: 24, shadowOffsetY: 12, shadowColor: 'rgba(0,0,0,0.15)',
      borderColor: BLOCK_COLORS.borderSelected, borderWidth: 2, headerFill: BLOCK_COLORS.headerSelected, opacity: 0.92,
    },
    'dimmed': {
      shadowBlur: 0, shadowOffsetY: 0, shadowColor: 'transparent',
      borderColor: BLOCK_COLORS.border, borderWidth: 1, headerFill: BLOCK_COLORS.header, opacity: 0.25,
    },
  };
  return styles[state] || styles['default'];
}

// ---- Visual state resolution ----

function getBlockFilterResult(tableName, activeFilters) {
  if (!activeFilters || activeFilters.length === 0) return 'none';
  for (const f of activeFilters) {
    if (f.type === 'table' && f.value === tableName) return f.mode || 'dim';
  }
  return 'none';
}

function getBlockVisualState(tableName, state, traceTableSet, selectedPathTableSet) {
  const { selectedTables, hoveredTable, hoveredColumn, hoveredConnection, activeFilters, selectedColumn } = state;

  // Trace mode: dim tables not in the trace path
  if (traceTableSet && !traceTableSet.has(tableName)) return 'dimmed';

  // Filter mode: hide or dim filtered-out tables
  const filterResult = getBlockFilterResult(tableName, activeFilters);
  if (filterResult === 'hide') return 'hidden';
  if (filterResult === 'dim') return 'dimmed';

  const hasActiveHover = hoveredTable || hoveredColumn || hoveredConnection;

  // Selected column mode: takes priority over hover — dim tables not in the full path
  if (selectedPathTableSet) {
    if (selectedTables.includes(tableName)) return 'selected';
    if (selectedPathTableSet.has(tableName)) return 'default';
    return 'dimmed';
  }

  if (selectedTables.includes(tableName) && tableName === hoveredTable) return 'selected-hover';
  if (selectedTables.includes(tableName)) return 'selected';
  if (tableName === hoveredTable) return 'hover';

  if (hasActiveHover) {
    const isRelated = tableName === hoveredTable ||
      (hoveredColumn && hoveredColumn.table === tableName) ||
      isTableInHoveredConnection(tableName, hoveredConnection);
    if (!isRelated) return 'dimmed';
  }

  return 'default';
}

/**
 * BFS from a selected column to find all reachable tables through connections.
 */
function buildSelectedPathTableSet(selectedColumn, connections) {
  if (!selectedColumn || !connections || connections.length === 0) return null;

  const visited = new Set();
  visited.add(selectedColumn.table);
  const queue = [selectedColumn.table];

  // First pass: only follow connections from the selected column itself
  for (const conn of connections) {
    if (conn.source.table === selectedColumn.table && conn.source.column === selectedColumn.column) {
      if (!visited.has(conn.target.table)) {
        visited.add(conn.target.table);
        queue.push(conn.target.table);
      }
    }
    if (conn.target.table === selectedColumn.table && conn.target.column === selectedColumn.column) {
      if (!visited.has(conn.source.table)) {
        visited.add(conn.source.table);
        queue.push(conn.source.table);
      }
    }
  }

  // BFS: follow all connections from reached tables
  let idx = 1;
  while (idx < queue.length) {
    const tbl = queue[idx++];
    for (const conn of connections) {
      let neighbor = null;
      if (conn.source.table === tbl) neighbor = conn.target.table;
      else if (conn.target.table === tbl) neighbor = conn.source.table;
      else continue;

      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        queue.push(neighbor);
      }
    }
  }

  return visited;
}

function isTableInHoveredConnection(tableName, hoveredConnection) {
  if (!hoveredConnection) return false;
  return hoveredConnection.source.table === tableName || hoveredConnection.target.table === tableName;
}

// ---- Width calculation ----

/**
 * Auto-calculate block width based on content, clamped to min/max.
 * @param {object} table - { name, columns: [{ name, type, ... }] }
 * @returns {number}
 */
export function calculateBlockWidth(table) {
  const ctx = getContext();
  if (!ctx) return BLOCK_MIN_WIDTH;

  let maxWidth = 0;

  // Measure column rows
  for (const col of table.columns) {
    ctx.font = '12px Inter, system-ui, sans-serif';
    const nameWidth = ctx.measureText(col.name).width;
    ctx.font = '11px "JetBrains Mono", monospace';
    const typeWidth = ctx.measureText(col.type || '').width;
    const rowWidth = 30 + nameWidth + 20 + typeWidth + 60;
    maxWidth = Math.max(maxWidth, rowWidth);
  }

  // Measure header
  ctx.font = '600 13px Inter, system-ui, sans-serif';
  const headerWidth = 40 + ctx.measureText(table.name).width + 40;
  maxWidth = Math.max(maxWidth, headerWidth);

  return Math.max(BLOCK_MIN_WIDTH, Math.min(BLOCK_MAX_WIDTH, maxWidth));
}

// ---- Rounded rect helper ----

function drawRoundedRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
}

// ---- Drawing functions ----

function drawBlockShadow(ctx, x, y, w, h, vs) {
  ctx.save();
  ctx.shadowBlur = vs.shadowBlur;
  ctx.shadowOffsetX = 0;
  ctx.shadowOffsetY = vs.shadowOffsetY;
  ctx.shadowColor = vs.shadowColor;
  ctx.fillStyle = BLOCK_COLORS.background;
  drawRoundedRect(ctx, x, y, w, h, CORNER_RADIUS);
  ctx.fill();
  ctx.restore();
}

function drawBlockBackground(ctx, x, y, w, h) {
  ctx.fillStyle = BLOCK_COLORS.background;
  drawRoundedRect(ctx, x, y, w, h, CORNER_RADIUS);
  ctx.fill();
}

function drawBlockBorder(ctx, x, y, w, h, vs) {
  ctx.strokeStyle = vs.borderColor;
  ctx.lineWidth = vs.borderWidth;
  drawRoundedRect(ctx, x, y, w, h, CORNER_RADIUS);
  ctx.stroke();
}

function drawHeader(ctx, x, y, w, tableName, vs, collapsed, columnCount) {
  // Header background (clip to rounded top corners)
  ctx.save();
  drawRoundedRect(ctx, x, y, w, HEADER_HEIGHT, CORNER_RADIUS);
  ctx.clip();
  ctx.fillStyle = vs.headerFill;
  ctx.fillRect(x, y, w, HEADER_HEIGHT);
  ctx.restore();

  // Header bottom divider
  ctx.strokeStyle = BLOCK_COLORS.divider;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, y + HEADER_HEIGHT);
  ctx.lineTo(x + w, y + HEADER_HEIGHT);
  ctx.stroke();

  // Table icon placeholder (small grid)
  drawTableIcon(ctx, x + PADDING_H, y + HEADER_HEIGHT / 2);

  // Table name
  ctx.fillStyle = BLOCK_COLORS.textPrimary;
  ctx.font = '600 13px Inter, system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.fillText(tableName, x + 32, y + HEADER_HEIGHT / 2);

  // Collapse chevron
  drawChevron(ctx, x + w - 28, y + HEADER_HEIGHT / 2, collapsed);

  // If collapsed, show column count badge after table name
  if (collapsed) {
    ctx.font = '600 13px Inter, system-ui, sans-serif';
    const nameWidth = ctx.measureText(tableName).width;
    drawCollapsedBadge(ctx, x + 32 + nameWidth + 8, y + HEADER_HEIGHT / 2, columnCount);
  }
}

function drawTableIcon(ctx, x, cy) {
  const size = 12;
  const top = cy - size / 2;
  ctx.strokeStyle = BLOCK_COLORS.textSecondary;
  ctx.lineWidth = 1;
  ctx.strokeRect(x, top, size, size);
  ctx.beginPath();
  ctx.moveTo(x, top + 4);
  ctx.lineTo(x + size, top + 4);
  ctx.moveTo(x, top + 8);
  ctx.lineTo(x + size, top + 8);
  ctx.stroke();
}

function drawChevron(ctx, x, cy, collapsed) {
  const size = 4;
  ctx.strokeStyle = BLOCK_COLORS.textSecondary;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  if (collapsed) {
    ctx.moveTo(x - size / 2, cy - size);
    ctx.lineTo(x + size / 2, cy);
    ctx.lineTo(x - size / 2, cy + size);
  } else {
    ctx.moveTo(x - size, cy - size / 2);
    ctx.lineTo(x, cy + size / 2);
    ctx.lineTo(x + size, cy - size / 2);
  }
  ctx.stroke();
}

function drawCollapsedBadge(ctx, textX, cy, columnCount) {
  const text = `(${columnCount} col)`;
  ctx.fillStyle = BLOCK_COLORS.textSecondary;
  ctx.font = '11px Inter, system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, textX, cy);
}

function drawColumnRows(ctx, table, x, y, w, hoveredColumn, selectedColumn) {
  const startY = y + HEADER_HEIGHT;

  for (let i = 0; i < table.columns.length; i++) {
    const col = table.columns[i];
    const rowY = startY + i * ROW_HEIGHT;

    // Selected column highlight (persistent)
    const isSelected = selectedColumn && selectedColumn.table === table.name && selectedColumn.column === col.name;
    if (isSelected) {
      ctx.fillStyle = BLOCK_COLORS.headerSelected;
      ctx.fillRect(x, rowY, w, ROW_HEIGHT);
    } else if (hoveredColumn && hoveredColumn.table === table.name && hoveredColumn.column === col.name) {
      // Row hover highlight
      ctx.fillStyle = BLOCK_COLORS.rowHover;
      ctx.fillRect(x, rowY, w, ROW_HEIGHT);
    }

    // Row divider
    if (i > 0) {
      ctx.strokeStyle = BLOCK_COLORS.divider;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x + PADDING_H, rowY);
      ctx.lineTo(x + w - PADDING_H, rowY);
      ctx.stroke();
    }

    const cy = rowY + ROW_HEIGHT / 2;

    // Key icon (backend sends key_type as string: "PK", "FK", "UQ", or null)
    drawKeyIcon(ctx, x + PADDING_H, cy, col.key_type);

    // Column name
    ctx.fillStyle = BLOCK_COLORS.columnName;
    ctx.font = '12px Inter, system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    ctx.fillText(col.name, x + 30, cy);

    // Data type (right-aligned)
    drawDataType(ctx, col.type || '', x + w - PADDING_H, cy);
  }
}

function drawKeyIcon(ctx, x, cy, keyType) {
  if (!keyType) return;

  const color = KEY_COLORS[keyType] || BLOCK_COLORS.textSecondary;
  const radius = 7;

  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x + radius, cy, radius, 0, Math.PI * 2);
  ctx.fill();

  // Label
  ctx.fillStyle = '#FFFFFF';
  ctx.font = 'bold 8px Inter, system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  ctx.fillText(keyType, x + radius, cy);
  ctx.textAlign = 'left';
}

function drawDataType(ctx, type, rightEdge, cy) {
  if (!type) return;
  ctx.fillStyle = BLOCK_COLORS.textSecondary;
  ctx.font = '11px "JetBrains Mono", monospace';
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'right';
  ctx.fillText(type, rightEdge - 4, cy);
  ctx.textAlign = 'left';
}


// ---- Main exports ----

/**
 * Redraw all table blocks. Reads state fresh every time.
 */
export function redrawAll() {
  const ctx = getContext();
  if (!ctx) return;

  const state = getStateRef();
  const tables = state.tables;
  const viewport = state.viewport;

  // Pre-build trace table set for O(1) lookups
  const traceTableSet = (state.traceResults && state.traceResults.nodes && state.traceResults.nodes.length > 0)
    ? new Set(state.traceResults.nodes.map(n => n.table))
    : null;

  // Pre-build selected column path table set for full-path highlighting
  const selectedPathTableSet = buildSelectedPathTableSet(state.selectedColumn, state.connections);

  ctx.save();
  applyViewportTransform(ctx, viewport);

  for (const table of tables) {
    const pos = state.positions[table.name];
    if (!pos) continue;

    const isCollapsed = !!state.collapsed[table.name];
    const width = pos.width || calculateBlockWidth(table);
    const height = calculateBlockHeight(table, isCollapsed);
    const block = { x: pos.x, y: pos.y, width, height };

    if (!isBlockVisible(block)) continue;

    const visualState = getBlockVisualState(table.name, state, traceTableSet, selectedPathTableSet);
    if (visualState === 'hidden') continue;
    const vs = getVisualStyle(visualState);

    ctx.globalAlpha = vs.opacity;

    drawBlockShadow(ctx, pos.x, pos.y, width, height, vs);
    drawBlockBackground(ctx, pos.x, pos.y, width, height);
    drawBlockBorder(ctx, pos.x, pos.y, width, height, vs);
    drawHeader(ctx, pos.x, pos.y, width, table.name, vs, isCollapsed, table.columns.length);

    if (!isCollapsed) {
      drawColumnRows(ctx, table, pos.x, pos.y, width, state.hoveredColumn, state.selectedColumn);
    }

    ctx.globalAlpha = 1.0;
  }

  ctx.restore();
}

/**
 * Hit-test: find which block/column is at a given canvas coordinate.
 * @param {number} canvasX
 * @param {number} canvasY
 * @returns {{ tableName: string, columnIndex: number } | null}
 */
export function getBlockAtPoint(canvasX, canvasY) {
  const state = getStateRef();

  // Iterate in reverse so topmost (last-drawn) block wins
  for (let i = state.tables.length - 1; i >= 0; i--) {
    const table = state.tables[i];
    const pos = state.positions[table.name];
    if (!pos) continue;

    const isCollapsed = !!state.collapsed[table.name];
    const width = pos.width || calculateBlockWidth(table);
    const height = calculateBlockHeight(table, isCollapsed);

    if (canvasX < pos.x || canvasX > pos.x + width) continue;
    if (canvasY < pos.y || canvasY > pos.y + height) continue;

    // Inside this block — determine column index
    if (isCollapsed || canvasY < pos.y + HEADER_HEIGHT) {
      return { tableName: table.name, columnIndex: -1 };
    }

    const rowOffset = canvasY - (pos.y + HEADER_HEIGHT);
    const columnIndex = Math.floor(rowOffset / ROW_HEIGHT);
    const clampedIndex = Math.min(columnIndex, table.columns.length - 1);
    return { tableName: table.name, columnIndex: clampedIndex };
  }

  return null;
}
