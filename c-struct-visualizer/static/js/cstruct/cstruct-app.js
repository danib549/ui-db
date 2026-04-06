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
  getHoveredField,
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
      // Re-upload with new target (handled by upload module)
      EventBus.emit('cstructArchChanged', { arch: archSelect.value });
    });
  }

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

  // Draw connections first (under blocks)
  drawAllConnections(colors);

  // Draw blocks
  const hovered = getHoveredEntity();
  const selected = getSelectedEntity();

  for (const entity of entities) {
    const pos = getPosition(entity.name);
    if (!pos) continue;
    drawBlock(
      ctx, entity, pos,
      entity.name === hovered,
      entity.name === selected,
      isCollapsed(entity.name),
    );
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

function drawAllConnections(colors) {
  const connections = getConnections();
  const hovered = getHoveredEntity();

  for (const conn of connections) {
    const srcPos = getPosition(conn.source);
    const tgtPos = getPosition(conn.target);
    if (!srcPos || !tgtPos) continue;

    const srcEntity = getEntity(conn.source);
    const tgtEntity = getEntity(conn.target);
    if (!srcEntity) continue;

    const isHighlighted = hovered === conn.source || hovered === conn.target;
    const color = isHighlighted ? colors.connectionLine : colors.connectionLineDim;
    const lineWidth = isHighlighted ? LINE.strokeWidthHover : LINE.strokeWidth;

    // Find the field that references the target to get its Y position
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

    ctx.globalAlpha = isHighlighted ? 1.0 : (hovered ? 0.2 : 0.6);
    drawBezierConnection(ctx, srcAnchor, tgtAnchor, color, lineWidth);
    drawArrow(ctx, tgtAnchor, color);
    ctx.globalAlpha = 1.0;
  }
}

// ---- Layout ----

function onDataLoaded() {
  computeLayout();
  autoFit();
  scheduleRender();
}

function computeLayout() {
  const entities = getAllEntities();
  if (entities.length === 0) return;

  const connections = getConnections();
  const nameSet = new Set(entities.map(e => e.name));

  // Build dependency graph for topological layout
  const children = {};
  const inDegree = {};
  for (const name of nameSet) {
    children[name] = [];
    inDegree[name] = 0;
  }

  for (const conn of connections) {
    if (conn.source === conn.target) continue;
    if (!nameSet.has(conn.source) || !nameSet.has(conn.target)) continue;
    children[conn.source].push(conn.target);
    inDegree[conn.target]++;
  }

  // BFS depth assignment
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

  // Orphans at end
  for (const name of nameSet) {
    if (depth[name] === undefined) depth[name] = maxDepth + 1;
  }

  // Group by depth
  const rows = {};
  for (const [name, d] of Object.entries(depth)) {
    if (!rows[d]) rows[d] = [];
    rows[d].push(name);
  }

  const entityMap = Object.fromEntries(entities.map(e => [e.name, e]));
  const positions = {};
  let y = 0;

  const rowKeys = Object.keys(rows).map(Number).sort((a, b) => a - b);
  for (const key of rowKeys) {
    const row = rows[key];
    let x = 0;
    let maxH = 0;

    for (const name of row) {
      const entity = entityMap[name];
      const height = calculateBlockHeight(entity, false);
      const width = BLOCK.minWidth;
      positions[name] = { x, y, width, height };
      maxH = Math.max(maxH, height);
      x += width + BLOCK.gapX;
    }

    y += maxH + BLOCK.gapY;
  }

  setPositions(positions);
}

function autoFit() {
  const positions = getPositions();
  const keys = Object.keys(positions);
  if (keys.length === 0) return;

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const k of keys) {
    const p = positions[k];
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x + p.width);
    maxY = Math.max(maxY, p.y + p.height);
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
    setPosition(dragTarget, {
      ...getPosition(dragTarget),
      x: x - dragOffset.x,
      y: y - dragOffset.y,
    });
    return;
  }

  if (isPanning) {
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

function onMouseUp() {
  isDragging = false;
  isPanning = false;
  dragTarget = null;
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
    // Double-click header area to collapse/expand
    const blockPos = getPosition(hit);
    if (blockPos && y < blockPos.y + BLOCK.headerHeight) {
      toggleCollapsed(hit);
    } else {
      setSelectedEntity(hit);
    }
  }
}

// ---- Sidebar helpers ----

function renderStructList() {
  const list = document.getElementById('struct-list');
  if (!list) return;

  const entities = getAllEntities();
  const enums = getState().enums || [];

  if (entities.length === 0 && enums.length === 0) {
    list.innerHTML = '<div class="sidebar__empty">Upload C files to see structs</div>';
    return;
  }

  let html = '';
  for (const entity of entities) {
    const icon = entity.isUnion ? 'U' : 'S';
    const iconClass = entity.isUnion ? 'sidebar__badge--union' : 'sidebar__badge--struct';
    html += `<div class="sidebar__struct-item" data-entity="${entity.name}">
      <span class="sidebar__badge ${iconClass}">${icon}</span>
      <span class="sidebar__struct-name">${entity.name.startsWith('__anon_') ? '(anonymous)' : entity.name}</span>
      <span class="sidebar__struct-size">${entity.totalSize}B</span>
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

// ---- Bootstrap ----
document.addEventListener('DOMContentLoaded', init);
