/**
 * connections.js — THE IRON RULE Module
 * Connection lines MUST be fully recalculated and redrawn on every state change.
 * redrawAll() is the single entry point. Never cache line positions.
 */

import { getStateRef } from './state.js';
import { getContext, applyViewportTransform } from './canvas.js';
import {
  ROW_HEIGHT, HEADER_HEIGHT, TICK_LENGTH, CIRCLE_RADIUS,
  CROW_FOOT_SPREAD, CROW_FOOT_LENGTH, LINE_HIT_THRESHOLD,
  CONNECTION_COLORS, DIMMED_COLOR,
} from './constants.js';

// ---- Trace animation state ----
let traceAnimOffset = 0;
let traceAnimRunning = false;

let traceRenderFn = null;

/** Start the dash animation loop. Only redraws connections layer via renderFn. */
export function startTraceAnimation(renderFn) {
  traceRenderFn = renderFn;
  if (traceAnimRunning) return;
  traceAnimRunning = true;
  function tick() {
    if (!traceAnimRunning) return;
    traceAnimOffset = (traceAnimOffset + 0.5) % 24;
    traceRenderFn();
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

/** Stop the dash animation loop. */
export function stopTraceAnimation() {
  traceAnimRunning = false;
  traceAnimOffset = 0;
  traceRenderFn = null;
}

// ---- Anchor point calculation ----

function calculateAnchorPoint(block, columnIndex, side) {
  const x = side === 'left' ? block.x : block.x + block.width;
  if (block.collapsed) {
    return { x, y: block.y + HEADER_HEIGHT / 2, side };
  }
  const y = block.y + HEADER_HEIGHT + (columnIndex * ROW_HEIGHT) + (ROW_HEIGHT / 2);
  return { x, y, side };
}

function chooseSides(sourceBlock, targetBlock) {
  const srcCenter = sourceBlock.x + sourceBlock.width / 2;
  const tgtCenter = targetBlock.x + targetBlock.width / 2;
  if (srcCenter <= tgtCenter) {
    return { sourceSide: 'right', targetSide: 'left' };
  }
  return { sourceSide: 'left', targetSide: 'right' };
}

function getColumnIndex(tableName, columnName) {
  const tables = getStateRef().tables;
  const table = tables.find(t => t.name === tableName);
  if (!table) return 0;
  const idx = table.columns.findIndex(c => c.name === columnName);
  return idx >= 0 ? idx : 0;
}

// ---- Bezier math ----

function computeControlOffset(source, target) {
  const distance = Math.abs(target.x - source.x);
  return Math.min(100, distance * 0.4);
}

function cubicBezierPoint(t, p0, p1, p2, p3) {
  const mt = 1 - t;
  return {
    x: mt * mt * mt * p0.x + 3 * mt * mt * t * p1.x + 3 * mt * t * t * p2.x + t * t * t * p3.x,
    y: mt * mt * mt * p0.y + 3 * mt * mt * t * p1.y + 3 * mt * t * t * p2.y + t * t * t * p3.y,
  };
}

function getControlPoints(source, target) {
  const offset = computeControlOffset(source, target);
  const cp1x = source.x + (source.side === 'right' ? offset : -offset);
  const cp2x = target.x + (target.side === 'left' ? -offset : offset);
  return {
    cp1: { x: cp1x, y: source.y },
    cp2: { x: cp2x, y: target.y },
  };
}

// ---- Drawing primitives ----

function drawConnectionLine(ctx, source, target, style) {
  const { cp1, cp2 } = getControlPoints(source, target);

  ctx.beginPath();
  ctx.moveTo(source.x, source.y);
  ctx.bezierCurveTo(cp1.x, cp1.y, cp2.x, cp2.y, target.x, target.y);
  ctx.strokeStyle = style.color;
  ctx.lineWidth = style.width;
  ctx.setLineDash(style.dash || []);
  ctx.globalAlpha = style.opacity;
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.globalAlpha = 1.0;
}

function drawSelfReferenceLoop(ctx, sourceAnchor, targetAnchor, style) {
  const loopOffset = 60;
  ctx.beginPath();
  ctx.moveTo(sourceAnchor.x, sourceAnchor.y);
  ctx.bezierCurveTo(
    sourceAnchor.x + loopOffset, sourceAnchor.y,
    targetAnchor.x + loopOffset, targetAnchor.y,
    targetAnchor.x, targetAnchor.y
  );
  ctx.strokeStyle = style.color;
  ctx.lineWidth = style.width;
  ctx.setLineDash(style.dash || []);
  ctx.globalAlpha = style.opacity;
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.globalAlpha = 1.0;
}

// ---- Cardinality indicators ----

function drawOneSide(ctx, anchor, style) {
  const dir = anchor.side === 'left' ? -1 : 1;
  const tx = anchor.x + dir * TICK_LENGTH;

  ctx.strokeStyle = style.color;
  ctx.lineWidth = style.width;
  ctx.globalAlpha = style.opacity;

  ctx.beginPath();
  ctx.moveTo(tx, anchor.y - CROW_FOOT_SPREAD);
  ctx.lineTo(tx, anchor.y + CROW_FOOT_SPREAD);
  ctx.stroke();
  ctx.globalAlpha = 1.0;
}

function drawManySide(ctx, anchor, style) {
  const dir = anchor.side === 'left' ? -1 : 1;
  const tipX = anchor.x;
  const baseX = anchor.x + dir * CROW_FOOT_LENGTH;

  ctx.strokeStyle = style.color;
  ctx.lineWidth = style.width;
  ctx.globalAlpha = style.opacity;

  ctx.beginPath();
  ctx.moveTo(baseX, anchor.y - CROW_FOOT_SPREAD);
  ctx.lineTo(tipX, anchor.y);
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(baseX, anchor.y + CROW_FOOT_SPREAD);
  ctx.lineTo(tipX, anchor.y);
  ctx.stroke();

  ctx.globalAlpha = 1.0;
}

function drawCardinalityIndicators(ctx, connection, sourceAnchor, targetAnchor, style) {
  const type = connection.type || 'one-to-many';
  if (type === 'one-to-one') {
    drawOneSide(ctx, sourceAnchor, style);
    drawOneSide(ctx, targetAnchor, style);
  } else if (type === 'one-to-many') {
    drawManySide(ctx, sourceAnchor, style);
    drawOneSide(ctx, targetAnchor, style);
  } else if (type === 'many-to-many') {
    drawManySide(ctx, sourceAnchor, style);
    drawManySide(ctx, targetAnchor, style);
  }
}

// ---- Style resolution ----

function isHighlighted(connection, interactionState) {
  const { hoveredTable, hoveredColumn, hoveredConnection, selectedColumn } = interactionState;

  if (hoveredConnection) {
    return connection.source.table === hoveredConnection.source.table &&
      connection.source.column === hoveredConnection.source.column &&
      connection.target.table === hoveredConnection.target.table &&
      connection.target.column === hoveredConnection.target.column;
  }
  if (hoveredColumn) {
    return (connection.source.table === hoveredColumn.table && connection.source.column === hoveredColumn.column) ||
      (connection.target.table === hoveredColumn.table && connection.target.column === hoveredColumn.column);
  }
  if (hoveredTable) {
    return connection.source.table === hoveredTable || connection.target.table === hoveredTable;
  }
  return false;
}

/**
 * BFS from a selected column to find all connections to highlight (locked hover mode).
 * Returns a Set of connection keys ("srcTable.srcCol->tgtTable.tgtCol").
 * Follows ALL connection types to show the full relationship path.
 */
function buildSelectedColumnPathSet(selectedColumn, connections) {
  if (!selectedColumn || !connections || connections.length === 0) return null;

  const pathSet = new Set();
  const visitedTables = new Set();
  visitedTables.add(selectedColumn.table);

  // BFS: follow ALL connections from the selected column's table to show full path
  const queue = [selectedColumn.table];
  let idx = 0;

  while (idx < queue.length) {
    const tableName = queue[idx++];
    for (const conn of connections) {
      let neighbor = null;
      if (conn.source.table === tableName) neighbor = conn.target.table;
      else if (conn.target.table === tableName) neighbor = conn.source.table;
      else continue;

      pathSet.add(connKey(conn));
      if (!visitedTables.has(neighbor)) {
        visitedTables.add(neighbor);
        queue.push(neighbor);
      }
    }
  }

  return pathSet;
}

function connKey(conn) {
  return `${conn.source.table}.${conn.source.column}->${conn.target.table}.${conn.target.column}`;
}

function isDimmed(connection, interactionState) {
  const { hoveredTable, hoveredColumn, hoveredConnection } = interactionState;
  const hasActiveHover = hoveredTable || hoveredColumn || hoveredConnection;

  if (!hasActiveHover) return false;
  return !isHighlighted(connection, interactionState);
}

function buildTraceEdgeSet(traceResults) {
  if (!traceResults || !traceResults.edges || traceResults.edges.length === 0) return null;
  const set = new Set();
  for (const e of traceResults.edges) {
    set.add(`${e.from_table}->${e.to_table}`);
    set.add(`${e.to_table}->${e.from_table}`);
  }
  return set;
}

function isTraced(connection, traceEdgeSet) {
  if (!traceEdgeSet) return false;
  return traceEdgeSet.has(`${connection.source.table}->${connection.target.table}`);
}

function hasActiveTrace(traceEdgeSet) {
  return traceEdgeSet !== null;
}

function getFilterResult(connection, activeFilters) {
  if (!activeFilters || activeFilters.length === 0) return 'none';
  const mode = activeFilters[0].mode || 'dim';

  for (const f of activeFilters) {
    if (f.type === 'rel' && f.value === connection.type) return mode;
    if (f.type === 'table' && (f.value === connection.source.table || f.value === connection.target.table)) return mode;
  }
  return 'none';
}

function resolveConnectionStyle(connection, interactionState, traceEdgeSet, selectedPathSet) {
  const isSelfRef = connection.source.table === connection.target.table;
  const baseColor = isSelfRef
    ? CONNECTION_COLORS['self']
    : (CONNECTION_COLORS[connection.type] || CONNECTION_COLORS['one-to-many']);

  // Trace mode: only draw traced lines, skip everything else
  if (hasActiveTrace(traceEdgeSet)) {
    if (isTraced(connection, traceEdgeSet)) {
      return { color: '#EF4444', width: 3.5, dash: [8, 4], opacity: 1.0, animate: true };
    }
    return null;
  }

  // Filter mode: hide or dim filtered-out connections
  const filterResult = getFilterResult(connection, interactionState.activeFilters);
  if (filterResult === 'hide') return null;
  if (filterResult === 'dim') {
    return { color: DIMMED_COLOR, width: 1, dash: [4, 4], opacity: 0.15 };
  }

  // Locked hover mode: highlight connections from selected column's table, dim others
  if (interactionState.selectedColumn) {
    if (selectedPathSet && selectedPathSet.has(connKey(connection))) {
      return { color: baseColor, width: 2.5, dash: [], opacity: 1.0 };
    }
    return { color: DIMMED_COLOR, width: 1, dash: [4, 4], opacity: 0.15 };
  }

  if (isHighlighted(connection, interactionState)) {
    return { color: baseColor, width: 2.5, dash: [], opacity: 1.0 };
  }

  if (isDimmed(connection, interactionState)) {
    return { color: DIMMED_COLOR, width: 1, dash: [4, 4], opacity: 0.15 };
  }
  return { color: baseColor, width: 1.5, dash: [], opacity: 1.0 };
}

// ---- Block lookup helper ----

function buildBlockMap(state) {
  const map = {};
  for (const table of state.tables) {
    const pos = state.positions[table.name];
    if (!pos) continue;
    map[table.name] = {
      x: pos.x,
      y: pos.y,
      width: pos.width || 200,
      height: pos.height || 200,
      collapsed: !!state.collapsed[table.name],
    };
  }
  return map;
}

// ---- THE MAIN FUNCTION ----

/**
 * redrawAll — THE IRON RULE implementation.
 * Clears connection layer, reads ALL state, draws ALL connections fresh.
 * Safe to call at any time (idempotent). Never caches anything.
 */
export function redrawAll() {
  const ctx = getContext();
  if (!ctx) return;

  const state = getStateRef();
  const blocks = buildBlockMap(state);
  const interactionState = {
    hoveredTable: state.hoveredTable,
    hoveredColumn: state.hoveredColumn,
    hoveredConnection: state.hoveredConnection,
    selectedColumn: state.selectedColumn,
    activeFilters: state.activeFilters,
  };
  const traceEdgeSet = buildTraceEdgeSet(state.traceResults);
  const selectedPathSet = buildSelectedColumnPathSet(state.selectedColumn, state.connections);

  ctx.save();
  applyViewportTransform(ctx, state.viewport);

  for (const connection of state.connections) {
    drawSingleConnection(ctx, connection, blocks, interactionState, traceEdgeSet, selectedPathSet);
  }

  ctx.restore();
}

function drawSingleConnection(ctx, connection, blocks, interactionState, traceEdgeSet, selectedPathSet) {
  const srcBlock = blocks[connection.source.table];
  const tgtBlock = blocks[connection.target.table];
  if (!srcBlock || !tgtBlock) return;

  const style = resolveConnectionStyle(connection, interactionState, traceEdgeSet, selectedPathSet);
  if (!style) return; // null = skip (e.g. non-traced during active trace)

  if (style.animate) {
    ctx.lineDashOffset = -traceAnimOffset;
  }

  const isSelfRef = connection.source.table === connection.target.table;

  const srcColIdx = getColumnIndex(connection.source.table, connection.source.column);
  const tgtColIdx = getColumnIndex(connection.target.table, connection.target.column);

  if (isSelfRef) {
    const sourceAnchor = calculateAnchorPoint(srcBlock, srcColIdx, 'right');
    const targetAnchor = calculateAnchorPoint(tgtBlock, tgtColIdx, 'right');
    drawSelfReferenceLoop(ctx, sourceAnchor, targetAnchor, style);
    drawCardinalityIndicators(ctx, connection, sourceAnchor, targetAnchor, style);
    ctx.lineDashOffset = 0;
    return;
  }

  const { sourceSide, targetSide } = chooseSides(srcBlock, tgtBlock);
  const sourceAnchor = calculateAnchorPoint(srcBlock, srcColIdx, sourceSide);
  const targetAnchor = calculateAnchorPoint(tgtBlock, tgtColIdx, targetSide);

  drawConnectionLine(ctx, sourceAnchor, targetAnchor, style);
  drawCardinalityIndicators(ctx, connection, sourceAnchor, targetAnchor, style);
  ctx.lineDashOffset = 0;
}

// ---- Hit detection ----

/**
 * Check if a point (in canvas coords) is near any connection line.
 * @param {number} canvasX
 * @param {number} canvasY
 * @returns {object|null} The connection object, or null.
 */
export function isPointNearConnection(canvasX, canvasY) {
  const state = getStateRef();
  const blocks = buildBlockMap(state);
  const point = { x: canvasX, y: canvasY };

  for (const connection of state.connections) {
    const srcBlock = blocks[connection.source.table];
    const tgtBlock = blocks[connection.target.table];
    if (!srcBlock || !tgtBlock) continue;

    const isSelfRef = connection.source.table === connection.target.table;
    const srcColIdx = getColumnIndex(connection.source.table, connection.source.column);
    const tgtColIdx = getColumnIndex(connection.target.table, connection.target.column);

    if (isSelfRef) {
      if (isNearSelfRefLoop(point, srcBlock, srcColIdx, tgtColIdx)) return connection;
    } else {
      if (isNearNormalConnection(point, srcBlock, tgtBlock, srcColIdx, tgtColIdx)) return connection;
    }
  }
  return null;
}

function isNearNormalConnection(point, srcBlock, tgtBlock, srcColIdx, tgtColIdx) {
  const { sourceSide, targetSide } = chooseSides(srcBlock, tgtBlock);
  const source = calculateAnchorPoint(srcBlock, srcColIdx, sourceSide);
  const target = calculateAnchorPoint(tgtBlock, tgtColIdx, targetSide);
  const { cp1, cp2 } = getControlPoints(source, target);
  return isPointNearBezier(point, source, cp1, cp2, target);
}

function isNearSelfRefLoop(point, block, srcColIdx, tgtColIdx) {
  const source = calculateAnchorPoint(block, srcColIdx, 'right');
  const target = calculateAnchorPoint(block, tgtColIdx, 'right');
  const loopOffset = 60;
  const cp1 = { x: source.x + loopOffset, y: source.y };
  const cp2 = { x: target.x + loopOffset, y: target.y };
  return isPointNearBezier(point, source, cp1, cp2, target);
}

function isPointNearBezier(point, p0, p1, p2, p3) {
  const steps = 20;
  let minDist = Infinity;
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const bp = cubicBezierPoint(t, p0, p1, p2, p3);
    const dist = Math.hypot(point.x - bp.x, point.y - bp.y);
    minDist = Math.min(minDist, dist);
  }
  return minDist <= LINE_HIT_THRESHOLD;
}

// Event subscriptions removed — app.js render() pipeline calls redrawAll() directly.
// This avoids double-rendering (connections drawn twice per event).
