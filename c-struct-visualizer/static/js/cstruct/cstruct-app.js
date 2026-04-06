/**
 * cstruct-app.js — Main orchestrator for the C struct visualizer.
 * Owns the canvas, viewport, render pipeline, mouse events, and layout.
 */

import { EventBus } from '../events.js';
import {
  getState, getAllEntities, getEntity, getConnections, getPositions,
  getPosition, getViewport, isCollapsed, getHoveredEntity, getSelectedEntity,
  setPositions, setPosition, setViewport, toggleCollapsed,
  setHoveredEntity, setHoveredField, setSelectedEntity,
} from './cstruct-state.js';
import {
  BLOCK, CANVAS_COLORS, CANVAS_COLORS_DARK, LINE,
} from './cstruct-constants.js';
import { drawBlock, calculateBlockHeight, hitTestField } from './cstruct-blocks.js';
import { chooseSides, calculateAnchor, drawBezierConnection, drawArrow } from './cstruct-connections.js';
import { initUpload } from './cstruct-upload.js';

let canvas = null;
let ctx = null;
let rafId = null;

// Drag state
let isDragging = false;
let isPanning = false;
let dragMoved = false;
let dragTarget = null;
let dragOffset = { x: 0, y: 0 };
let panStart = { x: 0, y: 0 };

// ---- Initialization ----

export function init() {
  canvas = document.getElementById('cstruct-canvas');
  if (!canvas) return;
  ctx = canvas.getContext('2d');

  sizeCanvas();
  bindEvents();
  initUpload();
  initSidebar();

  // Listen to state changes
  EventBus.on('cstructStateChanged', scheduleRender);
  EventBus.on('cstructDataLoaded', onDataLoaded);

  scheduleRender();
}

function bindEvents() {
  canvas.addEventListener('mousedown', onMouseDown);
  canvas.addEventListener('mousemove', onMouseMove);
  canvas.addEventListener('mouseup', onMouseUp);
  canvas.addEventListener('mouseleave', onMouseLeave);
  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('dblclick', onDblClick);

  const observer = new ResizeObserver(() => {
    sizeCanvas();
    scheduleRender();
  });
  if (canvas.parentElement) {
    observer.observe(canvas.parentElement);
  }
}

function initSidebar() {
  // Target arch selector
  const archSelect = document.getElementById('arch-select');
  if (archSelect) {
    archSelect.addEventListener('change', () => {
      EventBus.emit('cstructArchChanged', { arch: archSelect.value });
    });
  }

  // Layout buttons
  const layoutBtns = document.querySelectorAll('.layout-btn');
  layoutBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      layoutBtns.forEach(b => b.classList.remove('layout-btn--active'));
      btn.classList.add('layout-btn--active');
      applyLayout(btn.dataset.layout);
    });
  });

  // Listen for data to populate struct list
  EventBus.on('cstructDataLoaded', renderStructList);
  EventBus.on('cstructEntitySelected', highlightStructListItem);
}

// ---- Render pipeline ----

function scheduleRender() {
  if (rafId) return;
  rafId = requestAnimationFrame(render);
}

function render() {
  rafId = null;
  if (!canvas || !ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const colors = getColors();
  const viewport = getViewport();

  // Clear
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = colors.bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Grid
  drawGrid(colors, viewport, dpr);

  // Apply viewport transform
  ctx.setTransform(
    viewport.zoom * dpr, 0, 0, viewport.zoom * dpr,
    viewport.panX * dpr, viewport.panY * dpr,
  );

  const entities = getAllEntities();
  if (entities.length === 0) {
    drawEmptyMessage(dpr);
    return;
  }

  // Compute trace subgraph if something is selected
  const selected = getSelectedEntity();
  const traceGraph = selected ? getConnectedSubgraph(selected) : null;

  // Draw connections first (under blocks)
  drawAllConnections(colors, traceGraph);

  // Draw blocks
  const hovered = getHoveredEntity();

  for (const entity of entities) {
    const pos = getPosition(entity.name);
    if (!pos) continue;

    // Dim blocks not in trace subgraph
    if (traceGraph && !traceGraph.entities.has(entity.name)) {
      ctx.globalAlpha = 0.15;
    }

    drawBlock(
      ctx, entity, pos,
      entity.name === hovered,
      entity.name === selected,
      isCollapsed(entity.name),
    );

    ctx.globalAlpha = 1.0;
  }
}

// ---- Grid ----

function drawGrid(colors, viewport, dpr) {
  const spacing = 20;
  const dotR = 1;

  ctx.setTransform(
    viewport.zoom * dpr, 0, 0, viewport.zoom * dpr,
    viewport.panX * dpr, viewport.panY * dpr,
  );

  const w = canvas.width / dpr;
  const h = canvas.height / dpr;
  const left = -viewport.panX / viewport.zoom;
  const top = -viewport.panY / viewport.zoom;
  const right = (w - viewport.panX) / viewport.zoom;
  const bottom = (h - viewport.panY) / viewport.zoom;

  const effectiveSpacing = spacing * Math.ceil(1 / Math.max(viewport.zoom, 0.25));
  const startX = Math.floor(left / effectiveSpacing) * effectiveSpacing;
  const startY = Math.floor(top / effectiveSpacing) * effectiveSpacing;

  ctx.fillStyle = colors.dot;
  for (let x = startX; x <= right; x += effectiveSpacing) {
    for (let y = startY; y <= bottom; y += effectiveSpacing) {
      ctx.fillRect(x - dotR, y - dotR, dotR * 2, dotR * 2);
    }
  }
}

// ---- Connections ----

function drawAllConnections(colors, traceGraph) {
  const connections = getConnections();
  const hovered = getHoveredEntity();

  for (let i = 0; i < connections.length; i++) {
    const conn = connections[i];
    const srcPos = getPosition(conn.source);
    const tgtPos = getPosition(conn.target);
    if (!srcPos || !tgtPos) continue;

    const srcEntity = getEntity(conn.source);
    if (!srcEntity) continue;

    const isHighlighted = hovered === conn.source || hovered === conn.target;
    const isInTrace = traceGraph ? traceGraph.connections.has(i) : true;

    // Choose color based on connection type
    let color;
    if (conn.type === 'return') {
      color = colors.connectionReturn;
    } else if (conn.type === 'uses') {
      color = colors.connectionUses;
    } else {
      color = colors.connectionLine;  // 'nested' and 'param'
    }
    const lineWidth = isHighlighted ? LINE.strokeWidthHover : LINE.strokeWidth;

    // Find the field row for source anchor Y position
    const fieldIdx = srcEntity.fields
      ? srcEntity.fields.findIndex(f => f.name === conn.field)
      : -1;
    const srcYOffset = fieldIdx >= 0
      ? BLOCK.headerHeight + fieldIdx * BLOCK.fieldRowHeight + BLOCK.fieldRowHeight / 2
      : BLOCK.headerHeight / 2;
    const tgtYOffset = BLOCK.headerHeight / 2;

    const { srcSide, tgtSide } = chooseSides(srcPos, tgtPos);
    const srcAnchor = calculateAnchor(srcPos, srcSide, srcYOffset);
    const tgtAnchor = calculateAnchor(tgtPos, tgtSide, tgtYOffset);

    // Dimming: trace mode dims non-trace connections, hover dims non-hovered
    if (traceGraph && !isInTrace) {
      ctx.globalAlpha = 0.05;
    } else {
      ctx.globalAlpha = isHighlighted ? 1.0 : (hovered ? 0.2 : 0.6);
    }

    // Dashed lines for 'uses' connections
    if (conn.type === 'uses') {
      ctx.setLineDash([4, 4]);
    }

    drawBezierConnection(ctx, srcAnchor, tgtAnchor, color, lineWidth);
    drawArrow(ctx, tgtAnchor, color);

    ctx.setLineDash([]);
    ctx.globalAlpha = 1.0;
  }
}

/** BFS through connections to find all entities connected to the selected one. */
function getConnectedSubgraph(entityName) {
  const connections = getConnections();
  const connected = new Set([entityName]);
  const connectedConns = new Set();

  const queue = [entityName];
  while (queue.length > 0) {
    const current = queue.shift();
    for (let i = 0; i < connections.length; i++) {
      const conn = connections[i];
      if (conn.source === current && !connected.has(conn.target)) {
        connected.add(conn.target);
        connectedConns.add(i);
        queue.push(conn.target);
      } else if (conn.target === current && !connected.has(conn.source)) {
        connected.add(conn.source);
        connectedConns.add(i);
        queue.push(conn.source);
      } else if (conn.source === current || conn.target === current) {
        connectedConns.add(i);
      }
    }
  }

  return { entities: connected, connections: connectedConns };
}

// ---- Layout ----

let currentLayoutMode = 'top-down';
let animationId = null;

function onDataLoaded() {
  applyLayout(currentLayoutMode, false);
  autoFit();
  scheduleRender();
}

/** Apply a named layout with optional animation. */
function applyLayout(mode, animate = true) {
  currentLayoutMode = mode;
  const entities = getAllEntities();
  if (entities.length === 0) return;

  const entityMap = Object.fromEntries(entities.map(e => [e.name, e]));
  const connections = getConnections();
  const nameSet = new Set(entities.map(e => e.name));

  let newPositions;
  if (mode === 'left-right') {
    newPositions = layoutLeftRight(entities, entityMap, connections, nameSet);
  } else if (mode === 'force') {
    newPositions = layoutForceDirected(entities, entityMap, connections, nameSet);
  } else if (mode === 'grid') {
    newPositions = layoutGrid(entities, entityMap);
  } else {
    newPositions = layoutTopDown(entities, entityMap, connections, nameSet);
  }

  if (animate && Object.keys(getPositions()).length > 0) {
    animateToPositions(newPositions);
  } else {
    setPositions(newPositions);
  }
  autoFit();
}

// ---- Dependency graph (shared by top-down and left-right) ----

function buildDepthMap(connections, nameSet) {
  const children = {};
  const inDegree = {};
  for (const name of nameSet) {
    children[name] = [];
    inDegree[name] = 0;
  }

  for (const conn of connections) {
    if (conn.source === conn.target) continue;
    if (!nameSet.has(conn.source) || !nameSet.has(conn.target)) continue;
    if (children[conn.source].includes(conn.target)) continue;
    children[conn.source].push(conn.target);
    inDegree[conn.target]++;
  }

  const depth = {};
  const queue = [];
  for (const name of nameSet) {
    if (inDegree[name] === 0) {
      queue.push(name);
      depth[name] = 0;
    }
  }

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

  for (const name of nameSet) {
    if (depth[name] === undefined) depth[name] = maxDepth + 1;
  }

  // Group by depth level
  const groups = {};
  for (const [name, d] of Object.entries(depth)) {
    if (!groups[d]) groups[d] = [];
    groups[d].push(name);
  }

  return { groups, maxDepth };
}

// ---- Top-Down (default) ----

function layoutTopDown(entities, entityMap, connections, nameSet) {
  const { groups } = buildDepthMap(connections, nameSet);
  const positions = {};
  const groupKeys = Object.keys(groups).map(Number).sort((a, b) => a - b);

  let y = 0;
  for (const key of groupKeys) {
    const row = groups[key];
    const rowWidth = row.reduce((sum, name) => {
      return sum + BLOCK.minWidth;
    }, 0) + (row.length - 1) * BLOCK.gapX;

    // Center the row
    let x = -rowWidth / 2;
    let maxH = 0;

    for (const name of row) {
      const entity = entityMap[name];
      const height = calculateBlockHeight(entity, false);
      positions[name] = { x, y, width: BLOCK.minWidth, height };
      maxH = Math.max(maxH, height);
      x += BLOCK.minWidth + BLOCK.gapX;
    }

    y += maxH + BLOCK.gapY;
  }

  return positions;
}

// ---- Left-Right ----

function layoutLeftRight(entities, entityMap, connections, nameSet) {
  const { groups } = buildDepthMap(connections, nameSet);
  const positions = {};
  const groupKeys = Object.keys(groups).map(Number).sort((a, b) => a - b);

  let x = 0;
  for (const key of groupKeys) {
    const col = groups[key];
    let y = 0;
    let maxW = 0;

    for (const name of col) {
      const entity = entityMap[name];
      const height = calculateBlockHeight(entity, false);
      positions[name] = { x, y, width: BLOCK.minWidth, height };
      maxW = Math.max(maxW, BLOCK.minWidth);
      y += height + 40;
    }

    x += maxW + 200;
  }

  return positions;
}

// ---- Force-Directed ----

function layoutForceDirected(entities, entityMap, connections, nameSet) {
  const REPULSION = 8000;
  const SPRING_LENGTH = 300;
  const SPRING_STRENGTH = 0.015;
  const DAMPING = 0.85;
  const ITERATIONS = 120;

  // Initialize nodes from current positions or random
  const currentPos = getPositions();
  const nodes = {};
  entities.forEach((e, i) => {
    const p = currentPos[e.name];
    nodes[e.name] = {
      x: p ? p.x : (i % 5) * 400 + Math.random() * 50,
      y: p ? p.y : Math.floor(i / 5) * 300 + Math.random() * 50,
      vx: 0, vy: 0,
    };
  });

  const names = Object.keys(nodes);

  // Build unique edges
  const edges = [];
  const edgeSet = new Set();
  for (const conn of connections) {
    if (!nameSet.has(conn.source) || !nameSet.has(conn.target)) continue;
    if (conn.source === conn.target) continue;
    const key = [conn.source, conn.target].sort().join('|');
    if (edgeSet.has(key)) continue;
    edgeSet.add(key);
    edges.push({ a: conn.source, b: conn.target });
  }

  for (let iter = 0; iter < ITERATIONS; iter++) {
    // Repulsion between all pairs
    for (let i = 0; i < names.length; i++) {
      for (let j = i + 1; j < names.length; j++) {
        const a = nodes[names[i]];
        const b = nodes[names[j]];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.max(Math.hypot(dx, dy), 1);
        const force = REPULSION / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx -= fx; a.vy -= fy;
        b.vx += fx; b.vy += fy;
      }
    }

    // Spring forces along connections
    for (const edge of edges) {
      const a = nodes[edge.a];
      const b = nodes[edge.b];
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(Math.hypot(dx, dy), 1);
      const displacement = dist - SPRING_LENGTH;
      const force = displacement * SPRING_STRENGTH;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }

    // Apply velocity with damping
    for (const name of names) {
      const node = nodes[name];
      node.x += node.vx;
      node.y += node.vy;
      node.vx *= DAMPING;
      node.vy *= DAMPING;
    }
  }

  const positions = {};
  for (const name of names) {
    const entity = entityMap[name];
    const height = calculateBlockHeight(entity, false);
    positions[name] = {
      x: nodes[name].x,
      y: nodes[name].y,
      width: BLOCK.minWidth,
      height,
    };
  }
  return positions;
}

// ---- Grid ----

function layoutGrid(entities, entityMap) {
  const sorted = [...entities].sort((a, b) => {
    // Structs first, then unions, then functions
    const order = (e) => e.isFunction ? 2 : e.isUnion ? 1 : 0;
    const diff = order(a) - order(b);
    return diff !== 0 ? diff : a.name.localeCompare(b.name);
  });

  const cols = Math.max(2, Math.ceil(Math.sqrt(sorted.length)));
  const positions = {};
  let x = 0, y = 0, col = 0, rowMaxH = 0;

  for (const entity of sorted) {
    const height = calculateBlockHeight(entity, false);
    positions[entity.name] = { x, y, width: BLOCK.minWidth, height };
    rowMaxH = Math.max(rowMaxH, height);
    col++;

    if (col >= cols) {
      col = 0;
      x = 0;
      y += rowMaxH + BLOCK.gapY;
      rowMaxH = 0;
    } else {
      x += BLOCK.minWidth + BLOCK.gapX;
    }
  }

  return positions;
}

// ---- Animated transition ----

function animateToPositions(targetPositions, duration = 350) {
  if (animationId) cancelAnimationFrame(animationId);

  const startPositions = {};
  const current = getPositions();
  for (const name of Object.keys(targetPositions)) {
    startPositions[name] = current[name]
      ? { ...current[name] }
      : { ...targetPositions[name] };
  }

  const startTime = performance.now();

  function step(now) {
    const t = Math.min((now - startTime) / duration, 1);
    const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

    const interpolated = {};
    for (const name of Object.keys(targetPositions)) {
      const from = startPositions[name];
      const to = targetPositions[name];
      interpolated[name] = {
        x: from.x + (to.x - from.x) * eased,
        y: from.y + (to.y - from.y) * eased,
        width: to.width,
        height: to.height,
      };
    }

    setPositions(interpolated);

    if (t < 1) {
      animationId = requestAnimationFrame(step);
    } else {
      animationId = null;
    }
  }

  animationId = requestAnimationFrame(step);
}

// ---- Auto-fit viewport ----

function autoFit() {
  const positions = getPositions();
  const keys = Object.keys(positions);
  if (keys.length === 0) return;

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const k of keys) {
    const p = positions[k];
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x + (p.width || BLOCK.minWidth));
    maxY = Math.max(maxY, p.y + (p.height || 100));
  }

  const pad = 60;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.width / dpr;
  const h = canvas.height / dpr;
  const contentW = maxX - minX;
  const contentH = maxY - minY;

  if (contentW === 0 || contentH === 0) {
    setViewport({ zoom: 1, panX: pad, panY: pad });
    return;
  }

  const zoom = Math.min(1.5, Math.min((w - pad * 2) / contentW, (h - pad * 2) / contentH));
  setViewport({
    zoom,
    panX: pad + ((w - pad * 2) - contentW * zoom) / 2 - minX * zoom,
    panY: pad + ((h - pad * 2) - contentH * zoom) / 2 - minY * zoom,
  });
}

// ---- Mouse interaction ----

function screenToCanvas(sx, sy) {
  const vp = getViewport();
  return {
    x: (sx - vp.panX) / vp.zoom,
    y: (sy - vp.panY) / vp.zoom,
  };
}

function getMousePos(e) {
  const rect = canvas.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

function hitTestBlock(cx, cy) {
  const entities = getAllEntities();
  for (const entity of entities) {
    const pos = getPosition(entity.name);
    if (!pos) continue;
    const h = calculateBlockHeight(entity, isCollapsed(entity.name));
    if (cx >= pos.x && cx <= pos.x + pos.width && cy >= pos.y && cy <= pos.y + h) {
      return entity.name;
    }
  }
  return null;
}

function onMouseDown(e) {
  if (e.button !== 0) return;
  const pos = getMousePos(e);
  const { x, y } = screenToCanvas(pos.x, pos.y);
  const hit = hitTestBlock(x, y);

  dragMoved = false;

  if (hit) {
    isDragging = true;
    dragTarget = hit;
    const blockPos = getPosition(hit);
    dragOffset = { x: x - blockPos.x, y: y - blockPos.y };
    canvas.style.cursor = 'grabbing';
  } else {
    isPanning = true;
    panStart = pos;
    canvas.style.cursor = 'grabbing';
  }
}

function onMouseMove(e) {
  const pos = getMousePos(e);
  const { x, y } = screenToCanvas(pos.x, pos.y);

  if (isDragging && dragTarget) {
    dragMoved = true;
    setPosition(dragTarget, {
      ...getPosition(dragTarget),
      x: x - dragOffset.x,
      y: y - dragOffset.y,
    });
    return;
  }

  if (isPanning) {
    dragMoved = true;
    const vp = getViewport();
    setViewport({
      panX: vp.panX + (pos.x - panStart.x),
      panY: vp.panY + (pos.y - panStart.y),
    });
    panStart = pos;
    return;
  }

  // Hover detection
  const hit = hitTestBlock(x, y);
  setHoveredEntity(hit);

  if (hit) {
    const entity = getEntity(hit);
    const blockPos = getPosition(hit);
    if (entity && blockPos) {
      const fIdx = hitTestField(entity, blockPos, x, y, isCollapsed(hit));
      setHoveredField(fIdx >= 0 ? hit : null, fIdx);
    }
    canvas.style.cursor = 'pointer';
  } else {
    setHoveredField(null, -1);
    canvas.style.cursor = 'grab';
  }

  // Update field detail in sidebar
  updateFieldDetail(hit, x, y);
}

function onMouseUp(e) {
  const wasDrag = dragMoved;
  isDragging = false;
  isPanning = false;
  dragTarget = null;

  // Click-to-select: if mouse didn't move, treat as a click
  if (!wasDrag && e) {
    const pos = getMousePos(e);
    const { x, y } = screenToCanvas(pos.x, pos.y);
    const hit = hitTestBlock(x, y);
    if (hit) {
      setSelectedEntity(hit);
    } else if (getSelectedEntity()) {
      // Click empty space to deselect
      setSelectedEntity(getSelectedEntity());
    }
  }

  canvas.style.cursor = getHoveredEntity() ? 'pointer' : 'grab';
}

function onMouseLeave() {
  onMouseUp();
  setHoveredEntity(null);
  setHoveredField(null, -1);
}

function onWheel(e) {
  e.preventDefault();
  const pos = getMousePos(e);
  const { x: cx, y: cy } = screenToCanvas(pos.x, pos.y);
  const vp = getViewport();

  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  const newZoom = Math.max(0.15, Math.min(5, vp.zoom * factor));

  setViewport({
    zoom: newZoom,
    panX: pos.x - cx * newZoom,
    panY: pos.y - cy * newZoom,
  });
}

function onDblClick(e) {
  const pos = getMousePos(e);
  const { x, y } = screenToCanvas(pos.x, pos.y);
  const hit = hitTestBlock(x, y);

  if (hit) {
    toggleCollapsed(hit);
  }
}

// ---- Sidebar helpers ----

function renderStructList() {
  const list = document.getElementById('struct-list');
  if (!list) return;

  const entities = getAllEntities();
  const enums = getState().enums || [];

  if (entities.length === 0 && enums.length === 0) {
    list.innerHTML = '<div class="sidebar__empty">Upload C files to see types</div>';
    return;
  }

  let html = '';
  for (const entity of entities) {
    let icon, iconClass, meta;
    if (entity.isFunction) {
      icon = 'F';
      iconClass = 'sidebar__badge--function';
      meta = `${entity.params ? entity.params.length : 0}p`;
    } else if (entity.isUnion) {
      icon = 'U';
      iconClass = 'sidebar__badge--union';
      meta = `${entity.totalSize}B`;
    } else {
      icon = 'S';
      iconClass = 'sidebar__badge--struct';
      meta = `${entity.totalSize}B`;
    }
    const displayName = entity.name.startsWith('__anon_') ? '(anonymous)' : entity.name;
    html += `<div class="sidebar__struct-item" data-entity="${entity.name}">
      <span class="sidebar__badge ${iconClass}">${icon}</span>
      <span class="sidebar__struct-name">${displayName}</span>
      <span class="sidebar__struct-size">${meta}</span>
    </div>`;
  }

  for (const en of enums) {
    html += `<div class="sidebar__struct-item" data-entity="${en.name}">
      <span class="sidebar__badge sidebar__badge--enum">E</span>
      <span class="sidebar__struct-name">${en.name}</span>
      <span class="sidebar__struct-size">${en.values.length}v</span>
    </div>`;
  }

  list.innerHTML = html;

  // Click to pan to block
  list.querySelectorAll('.sidebar__struct-item').forEach(el => {
    el.addEventListener('click', () => {
      const name = el.dataset.entity;
      setSelectedEntity(name);
      panToEntity(name);
    });
  });

  // Update warnings
  renderWarnings();
}

function highlightStructListItem({ name }) {
  const items = document.querySelectorAll('.sidebar__struct-item');
  items.forEach(el => {
    el.classList.toggle('sidebar__struct-item--selected', el.dataset.entity === name);
  });
}

function panToEntity(name) {
  const pos = getPosition(name);
  if (!pos) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.width / dpr;
  const h = canvas.height / dpr;
  const vp = getViewport();

  setViewport({
    panX: w / 2 - (pos.x + pos.width / 2) * vp.zoom,
    panY: h / 2 - (pos.y + pos.height / 2) * vp.zoom,
  });
}

function updateFieldDetail(entityName, cx, cy) {
  const detail = document.getElementById('field-detail');
  if (!detail) return;

  if (!entityName) {
    detail.innerHTML = '<div class="sidebar__empty">Hover over a field to see details</div>';
    return;
  }

  const entity = getEntity(entityName);
  const pos = getPosition(entityName);
  if (!entity || !pos) return;

  const fIdx = hitTestField(entity, pos, cx, cy, isCollapsed(entityName));

  // Function entity — show return type and param info
  if (entity.isFunction) {
    if (fIdx < 0 || !entity.params || fIdx >= entity.params.length) {
      const retStr = entity.returnType || 'void';
      detail.innerHTML = `<div class="field-detail__header">${entity.name}()</div>
        <div class="field-detail__meta">Returns: <code>${retStr}</code></div>
        <div class="field-detail__meta">${entity.params?.length || 0} parameter(s)</div>
        ${entity.bodyStructRefs?.length ? `<div class="field-detail__meta">Uses: ${entity.bodyStructRefs.join(', ')}</div>` : ''}`;
      return;
    }
    const param = entity.params[fIdx];
    detail.innerHTML = `
      <div class="field-detail__header">${entity.name}(${param.name})</div>
      <div class="field-detail__row"><span>Type:</span> <code>${param.type}</code></div>
      <div class="field-detail__row"><span>Direction:</span> parameter${param.isPointer ? ' (pointer)' : ' (by value)'}</div>
      ${param.refStruct ? `<div class="field-detail__row"><span>Struct ref:</span> ${param.refStruct}</div>` : ''}
    `;
    return;
  }

  // Struct/union entity
  if (fIdx < 0 || !entity.fields || fIdx >= entity.fields.length) {
    detail.innerHTML = `<div class="field-detail__header">${entity.name}</div>
      <div class="field-detail__meta">${entity.totalSize}B | ${entity.alignment}-byte aligned${entity.packed ? ' | PACKED' : ''}</div>`;
    return;
  }

  const field = entity.fields[fIdx];
  detail.innerHTML = `
    <div class="field-detail__header">${entity.name}.${field.name}</div>
    <div class="field-detail__row"><span>Type:</span> <code>${field.type}</code></div>
    <div class="field-detail__row"><span>Offset:</span> +${field.offset} bytes${field.bitOffset != null ? ` (bit ${field.bitOffset})` : ''}</div>
    <div class="field-detail__row"><span>Size:</span> ${field.bitSize ? field.bitSize + ' bits' : field.size + ' bytes'}</div>
    <div class="field-detail__row"><span>Category:</span> ${field.category}</div>
    ${field.refStruct ? `<div class="field-detail__row"><span>References:</span> ${field.refStruct}</div>` : ''}
  `;
}

function renderWarnings() {
  const container = document.getElementById('warnings');
  if (!container) return;

  const warnings = getState().warnings || [];
  if (warnings.length === 0) {
    container.hidden = true;
    return;
  }

  container.hidden = false;
  container.innerHTML = warnings.map(w =>
    `<div class="warning-item">${w}</div>`
  ).join('');
}

// ---- Utility ----

function getColors() {
  return document.body.classList.contains('dark') ? CANVAS_COLORS_DARK : CANVAS_COLORS;
}

function sizeCanvas() {
  if (!canvas) return;
  const parent = canvas.parentElement;
  if (!parent) return;
  const dpr = window.devicePixelRatio || 1;
  const w = parent.clientWidth;
  const h = parent.clientHeight;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
}

function drawEmptyMessage(dpr) {
  const colors = getColors();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const w = canvas.width / dpr;
  const h = canvas.height / dpr;

  ctx.fillStyle = colors.headerMeta;
  ctx.font = '14px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('Upload .c or .h files to visualize struct memory layouts', w / 2, h / 2);
  ctx.textAlign = 'start';
}

// init() is called from the HTML module script after all imports resolve.
