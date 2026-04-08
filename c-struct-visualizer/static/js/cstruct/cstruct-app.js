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
  getShowStdlib, setShowStdlib,
  getActiveLayout, setActiveLayout, getFileContainers, setFileContainers,
  toggleEntityVisibility, isEntityHidden,
  getShowCallConnections, setShowCallConnections,
  getShowDepConnections, setShowDepConnections,
  getFunctions,
  getGlobals, getMacros, getIncludes,
  getCallGraphRoot, getCallGraphDepth, setCallGraphRoot, setCallGraphDepth,
  setMemoryMapEntity,
} from './cstruct-state.js';
import {
  BLOCK, CANVAS_COLORS, CANVAS_COLORS_DARK, LINE,
} from './cstruct-constants.js';
import { drawBlock, calculateBlockHeight, hitTestField, hitTestBadge, hitTestCollapseButton, drawFileContainer } from './cstruct-blocks.js';
import { chooseSides, calculateAnchor, drawBezierConnection, drawArrow } from './cstruct-connections.js';
import { initUpload } from './cstruct-upload.js';
import { openSourceModal } from './cstruct-modal.js';
import { getVisibleEntities, getFocusedSubgraph } from './cstruct-search.js';
import { escapeHtml } from '../utils.js';

let canvas = null;
let ctx = null;
let rafId = null;

// Drag state
let isDragging = false;
let isPanning = false;
let dragMoved = false;
let dragTarget = null;       // entity name or null
let dragContainer = null;    // filename of dragged file container or null
let dragOffset = { x: 0, y: 0 };
let panStart = { x: 0, y: 0 };
let lastRefStats = new Map();  // cached from last render for badge tooltips

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

  // Stdlib filter checkbox (sidebar) — syncs with toolbar chip
  const stdlibCheckbox = document.getElementById('show-stdlib-checkbox');
  if (stdlibCheckbox) {
    stdlibCheckbox.checked = getShowStdlib();
    stdlibCheckbox.addEventListener('change', () => {
      setShowStdlib(stdlibCheckbox.checked);
      renderStructList();
      scheduleRender();
    });
    // Keep sidebar checkbox in sync with state changes from toolbar chip
    EventBus.on('cstructStateChanged', ({ key }) => {
      if (key === 'showStdlib' || key === 'all' || key === 'filters') {
        stdlibCheckbox.checked = getShowStdlib();
        renderStructList();
      }
    });
  }

  // Dependency connections checkbox
  const depCheckbox = document.getElementById('show-deps-checkbox');
  if (depCheckbox) {
    depCheckbox.checked = getShowDepConnections();
    depCheckbox.addEventListener('change', () => {
      setShowDepConnections(depCheckbox.checked);
    });
    EventBus.on('cstructStateChanged', ({ key }) => {
      if (key === 'showDepConnections' || key === 'all') {
        depCheckbox.checked = getShowDepConnections();
      }
    });
  }

  // Function call connections checkbox
  const callCheckbox = document.getElementById('show-calls-checkbox');
  if (callCheckbox) {
    callCheckbox.checked = getShowCallConnections();
    callCheckbox.addEventListener('change', () => {
      setShowCallConnections(callCheckbox.checked);
    });
    EventBus.on('cstructStateChanged', ({ key }) => {
      if (key === 'showCallConnections' || key === 'all') {
        callCheckbox.checked = getShowCallConnections();
      }
    });
  }

  // Listen for data to populate struct list
  EventBus.on('cstructDataLoaded', renderStructList);
  EventBus.on('cstructDataLoaded', renderGlobalsPanel);
  EventBus.on('cstructDataLoaded', renderDefinesPanel);
  EventBus.on('cstructDataLoaded', populateSizeofPanel);
  EventBus.on('cstructEntitySelected', highlightStructListItem);
  EventBus.on('cstructEntitySelected', ({ name }) => {
    if (name) panToEntity(name);
    renderUsagePanel(name);
    renderCallGraphPanel(name);
  });

  // sizeof field selector
  const sizeofStruct = document.getElementById('sizeof-struct');
  if (sizeofStruct) {
    sizeofStruct.addEventListener('change', () => updateSizeofResult());
  }
  const sizeofField = document.getElementById('sizeof-field');
  if (sizeofField) {
    sizeofField.addEventListener('change', () => updateSizeofResult());
  }

  // Call graph depth slider
  const depthSlider = document.getElementById('call-graph-depth');
  if (depthSlider) {
    depthSlider.addEventListener('input', () => {
      const val = parseInt(depthSlider.value, 10);
      document.getElementById('call-graph-depth-label').textContent = val;
      setCallGraphDepth(val);
      const selected = getSelectedEntity();
      if (selected) renderCallGraphPanel(selected);
    });
  }
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

  // Includes layout: special render mode
  if (getActiveLayout() === 'includes') {
    drawIncludesGraph(colors);
    return;
  }

  const entities = getAllEntities();
  if (entities.length === 0) {
    drawEmptyMessage(dpr);
    return;
  }

  // Filter: hard filters (type/file/hidden/stdlib)
  const visibleSet = getVisibleEntities();
  // Soft filter: focused entity subgraph (dims non-members)
  const focusSet = getFocusedSubgraph();

  // Compute trace subgraph if something is selected
  const selected = getSelectedEntity();
  const traceGraph = selected ? getConnectedSubgraph(selected) : null;

  // Draw file containers (for by-file layout) — only if they have visible entities
  if (getActiveLayout() === 'by-file') {
    const containers = getFileContainers();
    for (const [filename, box] of Object.entries(containers)) {
      // Skip container if all its entities are filtered out
      if (visibleSet) {
        const hasVisible = entities.some(e => e.sourceFile === filename && visibleSet.has(e.name));
        if (!hasVisible) continue;
      }
      drawFileContainer(ctx, filename, box.x, box.y, box.width, box.height);
    }
  }

  // Draw connections first (under blocks)
  drawAllConnections(colors, traceGraph, visibleSet, focusSet);

  // Compute reference stats (how many connections target/originate from each entity)
  const refStats = buildRefStats();
  lastRefStats = refStats;

  // Draw blocks
  const hovered = getHoveredEntity();

  for (const entity of entities) {
    const pos = getPosition(entity.name);
    if (!pos) continue;

    // Hard-filter: type/file/hidden/stdlib filters fully hide
    if (visibleSet && !visibleSet.has(entity.name)) continue;

    // Soft-dim: trace subgraph or focused entity dims non-members
    if (traceGraph && !traceGraph.entities.has(entity.name)) {
      ctx.globalAlpha = 0.08;
    } else if (focusSet && !focusSet.has(entity.name)) {
      ctx.globalAlpha = 0.08;
    }

    drawBlock(
      ctx, entity, pos,
      entity.name === hovered,
      entity.name === selected,
      isCollapsed(entity.name),
      refStats.get(entity.name) || null,
    );

    ctx.globalAlpha = 1.0;
  }

  // Draw legend in screen space (fixed position)
  drawLegend(dpr, colors);
}

// ---- Legend ----

function drawLegend(dpr, colors) {
  const connections = getConnections();
  if (connections.length === 0) return;

  // Determine which connection types are visible
  const showCalls = getShowCallConnections();
  const showDeps = getShowDepConnections();
  const types = new Set();
  for (const c of connections) {
    const isCallType = c.type === 'call' || c.type === 'indirect_call';
    if (isCallType && !showCalls) continue;
    if (!isCallType && !showDeps) continue;
    types.add(c.type);
  }
  if (types.size === 0) return;

  // Legend entries in display order
  const allEntries = [
    { type: 'nested', label: 'Nested struct', color: colors.connectionLine, dash: [] },
    { type: 'param', label: 'Parameter', color: colors.connectionParam, dash: [6, 3] },
    { type: 'return', label: 'Return type', color: colors.connectionReturn, dash: [] },
    { type: 'uses', label: 'Local usage', color: colors.connectionUses, dash: [4, 4] },
    { type: 'call', label: 'Function call', color: colors.connectionCall, dash: [8, 3, 2, 3] },
    { type: 'global', label: 'Global var', color: colors.connectionGlobal, dash: [3, 3] },
    { type: 'funcptr', label: 'FP assignment', color: colors.connectionFuncptr, dash: [4, 2] },
    { type: 'indirect_call', label: 'Indirect call', color: colors.connectionIndirectCall, dash: [6, 2, 2, 2] },
  ];
  const entries = allEntries.filter(e => types.has(e.type));
  if (entries.length === 0) return;

  // Switch to screen coordinates
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const lineW = 30;
  const rowH = 18;
  const padX = 12;
  const padY = 8;
  const fontSize = 11;
  ctx.font = `${fontSize}px -apple-system, BlinkMacSystemFont, sans-serif`;

  // Measure text widths
  let maxTextW = 0;
  for (const e of entries) {
    const w = ctx.measureText(e.label).width;
    if (w > maxTextW) maxTextW = w;
  }

  const boxW = padX + lineW + 8 + maxTextW + padX;
  const boxH = padY + entries.length * rowH + padY;
  const canvasW = canvas.width / dpr;
  const canvasH = canvas.height / dpr;
  const x = canvasW - boxW - 12;
  const y = canvasH - boxH - 12;

  // Background
  const r = 6;
  ctx.fillStyle = colors.bg;
  ctx.globalAlpha = 0.85;
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + boxW - r, y);
  ctx.arcTo(x + boxW, y, x + boxW, y + r, r);
  ctx.lineTo(x + boxW, y + boxH - r);
  ctx.arcTo(x + boxW, y + boxH, x + boxW - r, y + boxH, r);
  ctx.lineTo(x + r, y + boxH);
  ctx.arcTo(x, y + boxH, x, y + boxH - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
  ctx.fill();
  ctx.globalAlpha = 1.0;
  ctx.strokeStyle = colors.boxBorder;
  ctx.lineWidth = 1;
  ctx.stroke();

  // Entries
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    const rowY = y + padY + i * rowH + rowH / 2;

    // Line sample
    ctx.beginPath();
    ctx.setLineDash(e.dash);
    ctx.strokeStyle = e.color;
    ctx.lineWidth = 2;
    ctx.moveTo(x + padX, rowY);
    ctx.lineTo(x + padX + lineW, rowY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Arrow head
    const ax = x + padX + lineW;
    ctx.beginPath();
    ctx.moveTo(ax, rowY);
    ctx.lineTo(ax - 5, rowY - 3);
    ctx.lineTo(ax - 5, rowY + 3);
    ctx.closePath();
    ctx.fillStyle = e.color;
    ctx.fill();

    // Label
    ctx.fillStyle = colors.fieldText;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(e.label, x + padX + lineW + 8, rowY);
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

// ---- Reference counts ----

function buildRefStats() {
  const connections = getConnections();
  const showCalls = getShowCallConnections();
  const showDeps = getShowDepConnections();
  const funcNames = new Set(getFunctions().map(f => f.name));
  const stats = new Map();
  const ensure = (name) => {
    if (!stats.has(name)) stats.set(name, { calledBy: 0, calls: 0, byFunc: 0, byStruct: 0 });
    return stats.get(name);
  };
  for (const c of connections) {
    if (c.type === 'call' && !showCalls) continue;
    if (c.type !== 'call' && !showDeps) continue;
    const tgt = ensure(c.target);
    tgt.calledBy++;
    if (funcNames.has(c.source)) tgt.byFunc++;
    else tgt.byStruct++;
    ensure(c.source).calls++;
  }
  return stats;
}

// ---- Connections ----

function drawAllConnections(colors, traceGraph, visibleSet, focusSet) {
  const connections = getConnections();
  const hovered = getHoveredEntity();

  for (let i = 0; i < connections.length; i++) {
    const conn = connections[i];

    // Skip connections based on toggles
    const isCallType = conn.type === 'call' || conn.type === 'indirect_call';
    if (isCallType && !getShowCallConnections()) continue;
    if (!isCallType && !getShowDepConnections()) continue;

    // Hard-filter: skip connections where either endpoint is hidden by hard filters
    if (visibleSet && (!visibleSet.has(conn.source) || !visibleSet.has(conn.target))) continue;

    // Soft-filter: check if connection is outside focus subgraph
    const isOutsideFocus = focusSet
      && (!focusSet.has(conn.source) || !focusSet.has(conn.target));

    let srcPos = getPosition(conn.source);
    const tgtPos = getPosition(conn.target);

    // For funcptr connections from globals (no canvas block), use the struct type as source
    let srcEntity = getEntity(conn.source);
    if (!srcPos && conn.type === 'funcptr') {
      const globals = getGlobals();
      const g = globals.find(gl => gl.name === conn.source);
      if (g && g.structRef) {
        srcPos = getPosition(g.structRef);
        srcEntity = getEntity(g.structRef);
      }
    }

    if (!srcPos || !tgtPos) continue;
    if (!srcEntity) continue;

    const isHighlighted = hovered === conn.source || hovered === conn.target;
    const isInTrace = traceGraph ? traceGraph.connections.has(i) : true;

    // Choose color based on connection type
    let color;
    if (conn.type === 'return') {
      color = colors.connectionReturn;
    } else if (conn.type === 'uses') {
      color = colors.connectionUses;
    } else if (conn.type === 'call') {
      color = colors.connectionCall;
    } else if (conn.type === 'param') {
      color = colors.connectionParam;
    } else if (conn.type === 'global') {
      color = colors.connectionGlobal;
    } else if (conn.type === 'funcptr') {
      color = colors.connectionFuncptr;
    } else if (conn.type === 'indirect_call') {
      color = colors.connectionIndirectCall;
    } else {
      color = colors.connectionLine;  // 'nested'
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

    // Dimming: focus, trace, or hover
    if (isOutsideFocus) {
      ctx.globalAlpha = 0.04;
    } else if (traceGraph && !isInTrace) {
      ctx.globalAlpha = 0.05;
    } else {
      ctx.globalAlpha = isHighlighted ? 1.0 : (hovered ? 0.2 : 0.6);
    }

    // Dashed lines for 'param', 'uses', and 'call' connections
    if (conn.type === 'param') {
      ctx.setLineDash([6, 3]);
    } else if (conn.type === 'uses') {
      ctx.setLineDash([4, 4]);
    } else if (conn.type === 'call') {
      ctx.setLineDash([8, 3, 2, 3]);
    } else if (conn.type === 'global') {
      ctx.setLineDash([3, 3]);
    } else if (conn.type === 'funcptr') {
      ctx.setLineDash([4, 2]);
    } else if (conn.type === 'indirect_call') {
      ctx.setLineDash([6, 2, 2, 2]);
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
  setActiveLayout(mode);
  const entities = getAllEntities();
  if (entities.length === 0) return;

  const entityMap = Object.fromEntries(entities.map(e => [e.name, e]));
  const connections = getConnections();
  const nameSet = new Set(entities.map(e => e.name));

  let newPositions;
  if (mode === 'left-right') {
    newPositions = layoutLeftRight(entities, entityMap, connections, nameSet);
    setFileContainers({});
  } else if (mode === 'force') {
    newPositions = layoutForceDirected(entities, entityMap, connections, nameSet);
    setFileContainers({});
  } else if (mode === 'grid') {
    newPositions = layoutGrid(entities, entityMap);
    setFileContainers({});
  } else if (mode === 'by-file') {
    const result = layoutByFile(entities, entityMap);
    newPositions = result.positions;
    setFileContainers(result.containers);
  } else if (mode === 'includes') {
    newPositions = layoutIncludes();
    setFileContainers({});
  } else {
    newPositions = layoutTopDown(entities, entityMap, connections, nameSet);
    setFileContainers({});
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

// ---- By-file layout (Phase 6) ----

function layoutByFile(entities, entityMap) {
  // Group entities by sourceFile
  const fileGroups = {};
  for (const entity of entities) {
    const file = entity.sourceFile || '(unknown)';
    if (!fileGroups[file]) fileGroups[file] = [];
    fileGroups[file].push(entity);
  }

  const containerPad = 20;
  const containerTitleH = 32;
  const innerGapX = 20;
  const innerGapY = 16;
  const containerGapX = 60;
  const containerGapY = 50;

  const positions = {};
  const containers = {};

  // Sort files alphabetically
  const sortedFiles = Object.keys(fileGroups).sort();

  // Arrange containers in a grid
  const containerCols = Math.max(1, Math.ceil(Math.sqrt(sortedFiles.length)));
  let containerX = 0, containerY = 0, col = 0, rowMaxH = 0;

  for (const file of sortedFiles) {
    const group = fileGroups[file];

    // Layout entities inside this container as a grid
    const innerCols = Math.max(1, Math.ceil(Math.sqrt(group.length)));
    let ix = containerPad, iy = containerTitleH + containerPad;
    let icol = 0, innerRowMaxH = 0;
    let maxRowWidth = 0;

    for (const entity of group) {
      const h = calculateBlockHeight(entity, false);
      positions[entity.name] = {
        x: containerX + ix,
        y: containerY + iy,
        width: BLOCK.minWidth,
        height: h,
      };
      innerRowMaxH = Math.max(innerRowMaxH, h);
      icol++;

      if (icol >= innerCols) {
        maxRowWidth = Math.max(maxRowWidth, ix + BLOCK.minWidth + containerPad);
        icol = 0;
        ix = containerPad;
        iy += innerRowMaxH + innerGapY;
        innerRowMaxH = 0;
      } else {
        ix += BLOCK.minWidth + innerGapX;
      }
    }

    // Compute container dimensions
    if (icol > 0) {
      maxRowWidth = Math.max(maxRowWidth, ix + BLOCK.minWidth + containerPad);
      iy += innerRowMaxH + containerPad;
    } else {
      iy += containerPad;
    }

    const containerW = Math.max(maxRowWidth, BLOCK.minWidth + containerPad * 2);
    const containerH = iy;

    containers[file] = {
      x: containerX,
      y: containerY,
      width: containerW,
      height: containerH,
    };

    rowMaxH = Math.max(rowMaxH, containerH);
    col++;

    if (col >= containerCols) {
      col = 0;
      containerX = 0;
      containerY += rowMaxH + containerGapY;
      rowMaxH = 0;
    } else {
      containerX += containerW + containerGapX;
    }
  }

  return { positions, containers };
}

// ---- Includes graph rendering ----

function drawIncludesGraph(colors) {
  const includes = getIncludes();
  const positions = getPositions();

  if (includes.length === 0) {
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = colors.headerMeta || '#999';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No include relationships found', canvas.width / (2 * dpr), canvas.height / (2 * dpr));
    return;
  }

  // Draw connections between file nodes
  for (const inc of includes) {
    const srcPos = positions[`__include_${inc.source}`];
    const tgtPos = positions[`__include_${inc.target}`];
    if (!srcPos || !tgtPos) continue;

    const sx = srcPos.x + srcPos.width / 2;
    const sy = srcPos.y + srcPos.height;
    const tx = tgtPos.x + tgtPos.width / 2;
    const ty = tgtPos.y;
    const cp = Math.abs(ty - sy) * 0.4;

    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.bezierCurveTo(sx, sy + cp, tx, ty - cp, tx, ty);
    ctx.strokeStyle = colors.connectionLine || '#C4841D';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Arrow (pointing down)
    const arrowSize = 6;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - arrowSize / 2, ty - arrowSize);
    ctx.lineTo(tx + arrowSize / 2, ty - arrowSize);
    ctx.closePath();
    ctx.fillStyle = colors.connectionLine || '#C4841D';
    ctx.fill();
  }

  // Draw file nodes
  for (const [key, pos] of Object.entries(positions)) {
    if (!key.startsWith('__include_')) continue;
    const filename = key.slice('__include_'.length);

    ctx.fillStyle = colors.headerBg || '#F0E8D8';
    ctx.strokeStyle = colors.boxBorder || '#D4C4AA';
    ctx.lineWidth = 1;

    const r = 6;
    ctx.beginPath();
    ctx.roundRect(pos.x, pos.y, pos.width, pos.height, r);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = colors.headerText || '#2C1E0E';
    ctx.font = 'bold 12px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(filename, pos.x + pos.width / 2, pos.y + pos.height / 2);
  }
}

// ---- Includes layout ----

function layoutIncludes() {
  const includes = getIncludes();
  const positions = {};
  if (includes.length === 0) return positions;

  // Collect unique file names
  const files = new Set();
  for (const inc of includes) {
    files.add(inc.source);
    files.add(inc.target);
  }

  // Build depth map via BFS (files with no includers are roots at depth 0)
  const targets = new Set(includes.map(i => i.target));
  const roots = [...files].filter(f => !targets.has(f));
  if (roots.length === 0) roots.push([...files][0]);

  const depthMap = {};
  const queue = roots.map(r => ({ name: r, depth: 0 }));
  const visited = new Set();
  for (const r of roots) { depthMap[r] = 0; visited.add(r); }

  while (queue.length > 0) {
    const { name, depth } = queue.shift();
    for (const inc of includes) {
      if (inc.source === name && !visited.has(inc.target)) {
        visited.add(inc.target);
        depthMap[inc.target] = depth + 1;
        queue.push({ name: inc.target, depth: depth + 1 });
      }
    }
  }

  // Any unvisited files get their own depth
  for (const f of files) {
    if (depthMap[f] == null) depthMap[f] = 0;
  }

  // Group by depth
  const byDepth = {};
  for (const [f, d] of Object.entries(depthMap)) {
    if (!byDepth[d]) byDepth[d] = [];
    byDepth[d].push(f);
  }

  const nodeW = 180;
  const nodeH = 36;
  const gapX = 60;
  const gapY = 80;

  for (const [depth, filesAtDepth] of Object.entries(byDepth)) {
    const d = parseInt(depth, 10);
    const totalW = filesAtDepth.length * (nodeW + gapX) - gapX;
    const startX = -totalW / 2;
    filesAtDepth.forEach((f, i) => {
      positions[`__include_${f}`] = {
        x: startX + i * (nodeW + gapX),
        y: d * (nodeH + gapY),
        width: nodeW,
        height: nodeH,
      };
    });
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

function hitTestContainer(cx, cy) {
  const containers = getFileContainers();
  for (const [filename, box] of Object.entries(containers)) {
    if (cx >= box.x && cx <= box.x + box.width && cy >= box.y && cy <= box.y + box.height) {
      return filename;
    }
  }
  return null;
}

function moveContainer(filename, newX, newY) {
  const containers = getFileContainers();
  const box = containers[filename];
  if (!box) return;

  const dx = newX - box.x;
  const dy = newY - box.y;

  // Move the container itself
  const updated = { ...containers, [filename]: { ...box, x: newX, y: newY } };
  setFileContainers(updated);

  // Move all entities belonging to this file
  const entities = getAllEntities();
  for (const entity of entities) {
    if (entity.sourceFile !== filename) continue;
    const pos = getPosition(entity.name);
    if (!pos) continue;
    setPosition(entity.name, { ...pos, x: pos.x + dx, y: pos.y + dy });
  }
}

function onMouseDown(e) {
  if (e.button !== 0) return;
  const pos = getMousePos(e);
  const { x, y } = screenToCanvas(pos.x, pos.y);
  const hit = hitTestBlock(x, y);

  dragMoved = false;
  dragContainer = null;

  if (hit) {
    isDragging = true;
    dragTarget = hit;
    const blockPos = getPosition(hit);
    dragOffset = { x: x - blockPos.x, y: y - blockPos.y };
    canvas.style.cursor = 'grabbing';
  } else if (getActiveLayout() === 'by-file') {
    const containerHit = hitTestContainer(x, y);
    if (containerHit) {
      isDragging = true;
      dragContainer = containerHit;
      const containers = getFileContainers();
      const box = containers[containerHit];
      dragOffset = { x: x - box.x, y: y - box.y };
      canvas.style.cursor = 'grabbing';
    } else {
      isPanning = true;
      panStart = pos;
      canvas.style.cursor = 'grabbing';
    }
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

  if (isDragging && dragContainer) {
    dragMoved = true;
    moveContainer(dragContainer, x - dragOffset.x, y - dragOffset.y);
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
      const tip = hitTestBadge(ctx, entity, blockPos, lastRefStats.get(hit) || null, x, y);
      canvas.title = tip || '';
    }
    canvas.style.cursor = 'pointer';
  } else {
    setHoveredField(null, -1);
    canvas.style.cursor = 'grab';
    canvas.title = '';
  }

  // Update field detail in sidebar
  updateFieldDetail(hit, x, y);
}

function onMouseUp(e) {
  const wasDrag = dragMoved;
  isDragging = false;
  isPanning = false;
  dragTarget = null;
  dragContainer = null;

  // Click-to-select: if mouse didn't move, treat as a click
  if (!wasDrag && e) {
    const pos = getMousePos(e);
    const { x, y } = screenToCanvas(pos.x, pos.y);
    const hit = hitTestBlock(x, y);
    if (hit) {
      // Check if click is on the collapse button (left 20px of header)
      const blockPos = getPosition(hit);
      if (blockPos && hitTestCollapseButton(blockPos, x, y)) {
        toggleCollapsed(hit);
      } else {
        setSelectedEntity(hit);
      }
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
    openSourceModal(hit);
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
    const displayName = entity.displayName || entity.name;
    const checked = isEntityHidden(entity.name) ? '' : 'checked';
    html += `<div class="sidebar__struct-item" data-entity="${entity.name}">
      <input type="checkbox" class="sidebar__checkbox" data-toggle="${entity.name}" ${checked} title="Show/hide on canvas">
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

  // Checkbox to toggle visibility on canvas
  list.querySelectorAll('.sidebar__checkbox').forEach(cb => {
    cb.addEventListener('change', (e) => {
      e.stopPropagation();
      toggleEntityVisibility(cb.dataset.toggle);
      scheduleRender();
    });
    // Prevent click from bubbling to the parent item (which does pan)
    cb.addEventListener('click', (e) => e.stopPropagation());
  });

  // Click on item (not checkbox) to pan to block
  list.querySelectorAll('.sidebar__struct-item').forEach(el => {
    el.addEventListener('click', () => {
      const name = el.dataset.entity;
      setSelectedEntity(name);
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
      detail.innerHTML = `<div class="field-detail__header">${entity.displayName || entity.name}()</div>
        <div class="field-detail__meta">Returns: <code>${retStr}</code></div>
        <div class="field-detail__meta">${entity.params?.length || 0} parameter(s)</div>
        ${entity.bodyStructRefs?.length ? `<div class="field-detail__meta">Uses: ${entity.bodyStructRefs.join(', ')}</div>` : ''}`;
      return;
    }
    const param = entity.params[fIdx];
    detail.innerHTML = `
      <div class="field-detail__header">${entity.displayName || entity.name}(${param.name})</div>
      <div class="field-detail__row"><span>Type:</span> <code>${param.type}</code></div>
      <div class="field-detail__row"><span>Direction:</span> parameter${param.isPointer ? ' (pointer)' : ' (by value)'}</div>
      ${param.refStruct ? `<div class="field-detail__row"><span>Struct ref:</span> ${param.refStruct}</div>` : ''}
    `;
    return;
  }

  // Struct/union entity
  if (fIdx < 0 || !entity.fields || fIdx >= entity.fields.length) {
    detail.innerHTML = `<div class="field-detail__header">${entity.displayName || entity.name}</div>
      <div class="field-detail__meta">${entity.totalSize}B | ${entity.alignment}-byte aligned${entity.packed ? ' | PACKED' : ''}</div>
      <button class="field-detail__memmap-btn" data-entity="${entityName}">Memory Map</button>`;
    detail.querySelector('.field-detail__memmap-btn')?.addEventListener('click', () => {
      setMemoryMapEntity(entityName);
    });
    return;
  }

  const field = entity.fields[fIdx];
  detail.innerHTML = `
    <div class="field-detail__header">${entity.displayName || entity.name}.${field.name}</div>
    <div class="field-detail__row"><span>Type:</span> <code>${field.type}</code></div>
    <div class="field-detail__row"><span>Offset:</span> +${field.offset} bytes${field.bitOffset != null ? ` (bit ${field.bitOffset})` : ''}</div>
    <div class="field-detail__row"><span>Size:</span> ${field.bitSize ? field.bitSize + ' bits' : field.size + ' bytes'}</div>
    <div class="field-detail__row"><span>Category:</span> ${field.category}</div>
    ${field.funcptrSig ? `<div class="field-detail__row"><span>Signature:</span> <code>${field.funcptrSig}</code></div>` : ''}
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

// ---- Globals Panel ----

function renderGlobalsPanel() {
  const panel = document.getElementById('globals-panel');
  const list = document.getElementById('globals-list');
  if (!panel || !list) return;

  const globals = getGlobals();
  if (globals.length === 0) { panel.hidden = true; return; }

  panel.hidden = false;
  list.innerHTML = globals.map(g => {
    const badge = g.storage === 'static' ? 'S' : g.storage === 'extern' ? 'E' : 'G';
    const badgeClass = g.storage === 'static' ? 'sidebar__badge--static'
      : g.storage === 'extern' ? 'sidebar__badge--extern' : 'sidebar__badge--global';
    const ref = g.structRef ? `data-entity="${escapeHtml(g.structRef)}"` : '';
    return `<div class="sidebar__global-item" ${ref}>
      <span class="sidebar__badge ${badgeClass}">${badge}</span>
      <span class="sidebar__global-name">${escapeHtml(g.name)}</span>
      <span class="sidebar__global-type">${escapeHtml(g.type)}</span>
    </div>`;
  }).join('');

  list.querySelectorAll('.sidebar__global-item[data-entity]').forEach(el => {
    el.style.cursor = 'pointer';
    el.addEventListener('click', () => {
      setSelectedEntity(el.dataset.entity);
    });
  });
}

// ---- Defines Panel ----

function renderDefinesPanel() {
  const panel = document.getElementById('defines-panel');
  const list = document.getElementById('defines-list');
  if (!panel || !list) return;

  const macros = getMacros();
  if (macros.length === 0) { panel.hidden = true; return; }

  panel.hidden = false;
  // Group by source file
  const byFile = {};
  for (const m of macros) {
    const file = m.sourceFile || '(unknown)';
    if (!byFile[file]) byFile[file] = [];
    byFile[file].push(m);
  }

  let html = '';
  for (const [file, items] of Object.entries(byFile)) {
    html += `<div class="sidebar__defines-file">${escapeHtml(file)}</div>`;
    for (const m of items) {
      html += `<div class="sidebar__define-item">
        <span class="sidebar__define-name">${escapeHtml(m.name)}</span>
        <span class="sidebar__define-value">${escapeHtml(m.value)}</span>
      </div>`;
    }
  }
  list.innerHTML = html;
}

// ---- Usage Panel (Used By / Uses) ----

function renderUsagePanel(entityName) {
  const panel = document.getElementById('usage-panel');
  const list = document.getElementById('usage-list');
  const title = document.getElementById('usage-panel-title');
  if (!panel || !list) return;

  if (!entityName) { panel.hidden = true; return; }

  const entity = getEntity(entityName);
  if (!entity) { panel.hidden = true; return; }

  const connections = getConnections();
  const isFunc = entity.isFunction;

  if (isFunc) {
    // Function selected: show which structs it uses
    renderFunctionUsage(entityName, connections, panel, list, title);
  } else {
    // Struct/union selected: show which functions use it
    renderStructUsage(entityName, connections, panel, list, title);
  }
}

function renderStructUsage(entityName, connections, panel, list, title) {
  const usedBy = connections.filter(c =>
    c.target === entityName && ['param', 'return', 'uses', 'global'].includes(c.type)
  );
  if (usedBy.length === 0) { panel.hidden = true; return; }

  panel.hidden = false;
  title.textContent = 'Used By';

  const byType = { param: [], return: [], uses: [], global: [] };
  for (const c of usedBy) {
    if (byType[c.type]) byType[c.type].push(c.source);
  }

  let html = '';
  const labels = { param: 'As parameter', return: 'As return', uses: 'Local variable', global: 'Global variable' };
  for (const [type, funcs] of Object.entries(byType)) {
    if (funcs.length === 0) continue;
    html += `<div class="sidebar__usage-group">${labels[type]}</div>`;
    for (const fn of funcs) {
      html += `<div class="sidebar__usage-item" data-entity="${escapeHtml(fn)}">${escapeHtml(fn)}()</div>`;
    }
  }
  list.innerHTML = html;
  bindUsageClicks(list);
}

function renderFunctionUsage(entityName, connections, panel, list, title) {
  const uses = connections.filter(c =>
    c.source === entityName && ['param', 'return', 'uses'].includes(c.type)
  );
  if (uses.length === 0) { panel.hidden = true; return; }

  panel.hidden = false;
  title.textContent = 'Uses Structs';

  const byType = { param: [], return: [], uses: [] };
  for (const c of uses) {
    if (byType[c.type]) byType[c.type].push(c.target);
  }

  let html = '';
  const labels = { param: 'Parameters', return: 'Return type', uses: 'Local variables' };
  for (const [type, structs] of Object.entries(byType)) {
    if (structs.length === 0) continue;
    html += `<div class="sidebar__usage-group">${labels[type]}</div>`;
    for (const s of structs) {
      html += `<div class="sidebar__usage-item" data-entity="${escapeHtml(s)}">${escapeHtml(s)}</div>`;
    }
  }
  list.innerHTML = html;
  bindUsageClicks(list);
}

function bindUsageClicks(list) {
  list.querySelectorAll('.sidebar__usage-item').forEach(el => {
    el.addEventListener('click', () => {
      setSelectedEntity(el.dataset.entity);
    });
  });
}

// ---- sizeof / offsetof Calculator ----

function populateSizeofPanel() {
  const panel = document.getElementById('sizeof-panel');
  const select = document.getElementById('sizeof-struct');
  if (!panel || !select) return;

  const state = getState();
  const structs = [...state.structs, ...state.unions];
  if (structs.length === 0) { panel.hidden = true; return; }

  panel.hidden = false;
  let html = '<option value="">Select struct...</option>';
  for (const s of structs) {
    const name = s.displayName || s.name;
    html += `<option value="${escapeHtml(s.name)}">${escapeHtml(name)}</option>`;
  }
  select.innerHTML = html;
  document.getElementById('sizeof-field').hidden = true;
  document.getElementById('sizeof-result').innerHTML = '';
}

function updateSizeofResult() {
  const structSelect = document.getElementById('sizeof-struct');
  const fieldSelect = document.getElementById('sizeof-field');
  const resultDiv = document.getElementById('sizeof-result');
  if (!structSelect || !fieldSelect || !resultDiv) return;

  const entityName = structSelect.value;
  if (!entityName) {
    fieldSelect.hidden = true;
    resultDiv.innerHTML = '';
    return;
  }

  const entity = getEntity(entityName);
  if (!entity) return;

  // Populate field dropdown
  const fields = (entity.fields || []).filter(f => f.category !== 'padding');
  let fhtml = '<option value="">-- whole struct --</option>';
  for (const f of fields) {
    fhtml += `<option value="${escapeHtml(f.name)}">${escapeHtml(f.name)}</option>`;
  }
  fieldSelect.innerHTML = fhtml;
  fieldSelect.hidden = false;

  // Build result
  const displayName = entity.displayName || entity.name;
  const fieldName = fieldSelect.value;
  let html = `<div class="sizeof-row"><b>sizeof</b>(${escapeHtml(displayName)}) = <b>${entity.totalSize}</b> bytes</div>`;
  html += `<div class="sizeof-row">Alignment: <b>${entity.alignment}</b></div>`;

  if (fieldName) {
    const field = fields.find(f => f.name === fieldName);
    if (field) {
      html += `<div class="sizeof-row"><b>offsetof</b>(${escapeHtml(displayName)}, ${escapeHtml(fieldName)}) = <b>${field.offset}</b></div>`;
      html += `<div class="sizeof-row">Field size: <b>${field.size}</b> bytes</div>`;
      html += `<div class="sizeof-row">Type: ${escapeHtml(field.type)}</div>`;
    }
  }

  if (entity.packed) html += `<div class="sizeof-row sizeof-row--packed">Packed (no padding)</div>`;
  resultDiv.innerHTML = html;
}

// ---- Call Graph Panel ----

function renderCallGraphPanel(entityName) {
  const panel = document.getElementById('call-graph-panel');
  const tree = document.getElementById('call-graph-tree');
  if (!panel || !tree) return;

  if (!entityName) { panel.hidden = true; return; }
  const entity = getEntity(entityName);
  if (!entity || !entity.isFunction) { panel.hidden = true; return; }

  panel.hidden = false;
  const connections = getConnections();
  const depth = getCallGraphDepth();
  setCallGraphRoot(entityName);

  // Build caller/callee adjacency (direct + indirect calls)
  const callers = {};     // target -> [sources]
  const callees = {};     // source -> [targets]
  const indirectEdges = new Set(); // "source->target" for indirect calls
  const callTypes = new Set(['call', 'indirect_call']);
  for (const c of connections) {
    if (!callTypes.has(c.type)) continue;
    if (!callees[c.source]) callees[c.source] = [];
    callees[c.source].push(c.target);
    if (!callers[c.target]) callers[c.target] = [];
    callers[c.target].push(c.source);
    if (c.type === 'indirect_call') {
      indirectEdges.add(`${c.source}->${c.target}`);
    }
  }

  let html = '';

  // Callers (who calls this function)
  const callerTree = buildCallTree(entityName, callers, depth);
  if (callerTree.length > 0) {
    html += `<div class="call-tree__label">&#8592; called by:</div>`;
    html += renderCallTree(callerTree, 0, indirectEdges, 'caller');
  }

  // Callees (what this function calls)
  const calleeTree = buildCallTree(entityName, callees, depth);
  if (calleeTree.length > 0) {
    html += `<div class="call-tree__label">&#8594; calls:</div>`;
    html += renderCallTree(calleeTree, 0, indirectEdges, 'callee', entityName);
  }

  if (!html) {
    html = '<div class="sidebar__empty">No call connections</div>';
  }

  // Hint about indirect call tracking
  if (indirectEdges.size > 0) {
    html += `<div class="call-tree__hint">Dashed = indirect call via function pointer (proved by assignment in code)</div>`;
  }

  tree.innerHTML = html;

  // Bind clicks
  tree.querySelectorAll('.call-tree__node').forEach(el => {
    el.addEventListener('click', () => {
      setSelectedEntity(el.dataset.entity);
    });
  });
}

function buildCallTree(root, adjacency, maxDepth) {
  const result = [];
  const visited = new Set([root]);

  function walk(name, depth) {
    if (depth >= maxDepth) return [];
    const neighbors = adjacency[name] || [];
    const children = [];
    for (const n of neighbors) {
      if (visited.has(n)) continue;
      visited.add(n);
      children.push({ name: n, children: walk(n, depth + 1) });
    }
    return children;
  }

  return walk(root, 0);
}

function renderCallTree(nodes, indent, indirectEdges = new Set(), direction = 'callee', parentName = '') {
  let html = '';
  for (const node of nodes) {
    const pad = indent * 16;
    // Check if this edge is indirect
    const edgeKey = direction === 'callee'
      ? `${parentName}->${node.name}`
      : `${node.name}->${parentName}`;
    const isIndirect = indirectEdges.has(edgeKey);
    const cls = isIndirect ? 'call-tree__node call-tree__node--indirect' : 'call-tree__node';
    const tag = isIndirect ? ' <span class="call-tree__tag">via fp</span>' : '';
    html += `<div class="${cls}" data-entity="${escapeHtml(node.name)}" style="padding-left:${pad}px">
      ${escapeHtml(node.name)}()${tag}
    </div>`;
    if (node.children.length > 0) {
      html += renderCallTree(node.children, indent + 1, indirectEdges, direction, node.name);
    }
  }
  return html;
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
