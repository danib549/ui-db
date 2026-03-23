/**
 * layout.js — Layout algorithms and animated transitions.
 * Each algorithm returns a position map { tableName: {x, y} }.
 * animateLayout smoothly transitions between position maps.
 */

import * as State from './state.js';
import { calculateBlockWidth } from './blocks.js';
import { HEADER_HEIGHT, ROW_HEIGHT, calculateBlockHeight } from './constants.js';

// ---- Undo stack ----

const layoutUndoStack = [];

// ---- Public API ----

/** Left-to-right dependency layout. Roots at column 0, children rightward. */
export function leftToRightLayout() {
  const tables = State.getTables();
  const connections = State.getConnections();
  const positions = State.getPositions();
  if (tables.length === 0) return {};

  const { columns, maxDepth } = buildDependencyColumns(tables, connections);
  return placeColumnsLR(columns, maxDepth, tables, positions);
}

/** Top-to-bottom dependency layout. Roots at row 0, children downward. */
export function topToBottomLayout() {
  const tables = State.getTables();
  const connections = State.getConnections();
  const positions = State.getPositions();
  if (tables.length === 0) return {};

  const { columns } = buildDependencyColumns(tables, connections);
  return placeColumnsTB(columns, tables, positions);
}

/** Force-directed physics simulation layout. */
export function forceDirectedLayout() {
  const tables = State.getTables();
  const connections = State.getConnections();
  const positions = State.getPositions();
  if (tables.length === 0) return {};

  return runForceSimulation(tables, connections, positions);
}

/** Simple alphabetical grid layout. */
export function gridLayout() {
  const tables = State.getTables();
  const positions = State.getPositions();
  if (tables.length === 0) return {};

  return placeGrid(tables, positions);
}

/** Animate from current positions to target positions. */
export function animateLayout(currentPositions, targetPositions, duration = 350) {
  const startTime = performance.now();

  function step(now) {
    const t = Math.min((now - startTime) / duration, 1);
    const eased = easeInOutCubic(t);

    for (const table of Object.keys(targetPositions)) {
      const from = currentPositions[table];
      const to = targetPositions[table];
      if (!from || !to) continue;
      State.setPosition(table, {
        x: from.x + (to.x - from.x) * eased,
        y: from.y + (to.y - from.y) * eased,
      });
    }

    if (t < 1) requestAnimationFrame(step);
  }

  requestAnimationFrame(step);
}

/** Push current positions to undo stack, animate to new positions, show toast. */
export function applyLayoutWithUndo(newPositions, showToastFn) {
  layoutUndoStack.push(structuredClone(State.getPositions()));
  animateLayout(State.getPositions(), newPositions);

  if (showToastFn) {
    showToastFn('Layout applied', {
      action: 'Undo',
      onAction: () => {
        const prev = layoutUndoStack.pop();
        if (prev) animateLayout(State.getPositions(), prev);
      },
      timeout: 5000,
    });
  }
}

// ---- Easing ----

function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

// ---- Dependency graph helpers ----

function buildDependencyColumns(tables, connections) {
  const tableSet = new Set(tables.map((t) => t.name));
  const children = {};
  const inDegree = {};

  tableSet.forEach((name) => {
    children[name] = [];
    inDegree[name] = 0;
  });

  connections.forEach((conn) => {
    const src = conn.source.table;
    const tgt = conn.target.table;
    if (!tableSet.has(src) || !tableSet.has(tgt)) return;
    if (src === tgt) return;
    children[tgt].push(src);
    inDegree[src]++;
  });

  const depth = {};
  const queue = [];

  tableSet.forEach((name) => {
    if (inDegree[name] === 0) {
      queue.push(name);
      depth[name] = 0;
    }
  });

  let maxDepth = 0;

  while (queue.length > 0) {
    const current = queue.shift();
    for (const child of children[current]) {
      const newDepth = depth[current] + 1;
      if (depth[child] === undefined || newDepth > depth[child]) {
        depth[child] = newDepth;
        maxDepth = Math.max(maxDepth, newDepth);
      }
      inDegree[child]--;
      if (inDegree[child] <= 0) queue.push(child);
    }
  }

  // Assign remaining (cyclic) tables to last column
  tableSet.forEach((name) => {
    if (depth[name] === undefined) depth[name] = maxDepth + 1;
  });

  const columns = {};
  Object.entries(depth).forEach(([name, d]) => {
    if (!columns[d]) columns[d] = [];
    columns[d].push(name);
  });

  return { columns, maxDepth };
}

// ---- Left-to-Right placement ----

function placeColumnsLR(columns, maxDepth, tables, positions) {
  const tableMap = Object.fromEntries(tables.map((t) => [t.name, t]));
  const result = {};
  const colKeys = Object.keys(columns).map(Number).sort((a, b) => a - b);

  let xOffset = 40;

  for (const colKey of colKeys) {
    const tablesInCol = columns[colKey];
    let maxWidth = 0;
    let yOffset = 40;

    for (const name of tablesInCol) {
      const table = tableMap[name];
      const width = getBlockWidth(table, positions, name);
      const height = calculateBlockHeight(table, false);
      result[name] = { x: xOffset, y: yOffset };
      maxWidth = Math.max(maxWidth, width);
      yOffset += height + 40;
    }

    xOffset += maxWidth + 300;
  }

  return result;
}

// ---- Top-to-Bottom placement ----

function placeColumnsTB(columns, tables, positions) {
  const tableMap = Object.fromEntries(tables.map((t) => [t.name, t]));
  const result = {};
  const rowKeys = Object.keys(columns).map(Number).sort((a, b) => a - b);

  let yOffset = 40;

  for (const rowKey of rowKeys) {
    const tablesInRow = columns[rowKey];
    let maxHeight = 0;
    let xOffset = 40;

    for (const name of tablesInRow) {
      const table = tableMap[name];
      const width = getBlockWidth(table, positions, name);
      const height = calculateBlockHeight(table, false);
      result[name] = { x: xOffset, y: yOffset };
      maxHeight = Math.max(maxHeight, height);
      xOffset += width + 40;
    }

    yOffset += maxHeight + 300;
  }

  return result;
}

// ---- Force-Directed layout ----

function runForceSimulation(tables, connections, positions) {
  const REPULSION = 5000;
  const SPRING_LENGTH = 250;
  const SPRING_STRENGTH = 0.02;
  const DAMPING = 0.9;
  const ITERATIONS = 100;

  const nodes = {};
  tables.forEach((t) => {
    const p = positions[t.name] || { x: Math.random() * 600, y: Math.random() * 600 };
    nodes[t.name] = { x: p.x, y: p.y, vx: 0, vy: 0 };
  });

  const names = Object.keys(nodes);

  for (let iter = 0; iter < ITERATIONS; iter++) {
    applyRepulsion(names, nodes, REPULSION);
    applySprings(connections, nodes, SPRING_LENGTH, SPRING_STRENGTH);
    applyVelocity(names, nodes, DAMPING);
  }

  const result = {};
  names.forEach((name) => {
    result[name] = { x: nodes[name].x, y: nodes[name].y };
  });
  return result;
}

function applyRepulsion(names, nodes, repulsion) {
  for (let i = 0; i < names.length; i++) {
    for (let j = i + 1; j < names.length; j++) {
      const a = nodes[names[i]];
      const b = nodes[names[j]];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(Math.hypot(dx, dy), 1);
      const force = repulsion / (dist * dist);
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx -= fx;
      a.vy -= fy;
      b.vx += fx;
      b.vy += fy;
    }
  }
}

function applySprings(connections, nodes, springLength, strength) {
  for (const conn of connections) {
    const a = nodes[conn.source.table];
    const b = nodes[conn.target.table];
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.max(Math.hypot(dx, dy), 1);
    const displacement = dist - springLength;
    const force = displacement * strength;
    const fx = (dx / dist) * force;
    const fy = (dy / dist) * force;
    a.vx += fx;
    a.vy += fy;
    b.vx -= fx;
    b.vy -= fy;
  }
}

function applyVelocity(names, nodes, damping) {
  for (const name of names) {
    const node = nodes[name];
    node.x += node.vx;
    node.y += node.vy;
    node.vx *= damping;
    node.vy *= damping;
  }
}

// ---- Grid layout ----

function placeGrid(tables, positions) {
  const sorted = [...tables].sort((a, b) => a.name.localeCompare(b.name));
  const result = {};

  sorted.forEach((table, i) => {
    const col = i % 4;
    const row = Math.floor(i / 4);
    result[table.name] = {
      x: 40 + col * 320,
      y: 40 + row * 400,
    };
  });

  return result;
}

// ---- Block dimension helpers ----

function getBlockWidth(table, positions, name) {
  if (positions[name] && positions[name].width) return positions[name].width;
  return calculateBlockWidth(table);
}

