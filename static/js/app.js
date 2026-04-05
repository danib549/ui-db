/**
 * app.js — Main orchestrator for the DB Diagram Visualizer.
 * Wires canvas interactions, toolbar, keyboard shortcuts, and event-driven rendering.
 */

import { EventBus } from './events.js';
import * as State from './state.js';
import { initCanvas, screenToCanvas, drawBackground, clear, getCanvasElement } from './canvas.js';
import { redrawAll as redrawConnections, isPointNearConnection, startTraceAnimation, stopTraceAnimation } from './connections.js';
import { redrawAll as redrawBlocks, getBlockAtPoint } from './blocks.js';
import { initUpload } from './csv-import.js';
import * as Layout from './layout.js';
import { initSearch } from './search.js';
import { initTrace } from './trace.js';
import { initFilters } from './filters.js';
import { initExport } from './export.js';
import { initTableViewer } from './table-viewer.js';
import { initTheme } from './theme.js';
import { initAdvisor } from './advisor.js';
import { initRebuilder } from './rebuilder.js';

// ---- Interaction state (not application state) ----

let isDragging = false;
let isPanning = false;
let dragTarget = null;
let dragOffsets = {};
let panStart = null;
let panViewportStart = null;
let zoomIndicatorTimer = null;

// ---- Layout algorithm cycle ----

const LAYOUT_ALGORITHMS = [
  { name: 'Left to Right', fn: Layout.leftToRightLayout },
  { name: 'Top to Bottom', fn: Layout.topToBottomLayout },
  { name: 'Force Directed', fn: Layout.forceDirectedLayout },
  { name: 'Grid', fn: Layout.gridLayout },
];
let currentLayoutIndex = 0;

// ---- Render pipeline ----

function render() {
  clear();
  drawBackground();
  redrawConnections();
  redrawBlocks();
}

// ---- Toast utility ----

function showToast(message, options = {}) {
  const toast = document.getElementById('toast');
  const msgEl = document.getElementById('toast-message');
  if (!toast || !msgEl) return;

  msgEl.textContent = message;
  toast.hidden = false;

  const timeout = options.timeout || 3000;
  setTimeout(() => { toast.hidden = true; }, timeout);
}

// ---- Zoom helpers ----

function updateZoomLabel() {
  const viewport = State.getViewport();
  const label = document.getElementById('zoom-label');
  if (label) label.textContent = `${Math.round(viewport.zoom * 100)}%`;
}

function showZoomIndicator() {
  const indicator = document.getElementById('zoom-indicator');
  const valueEl = document.getElementById('zoom-indicator-value');
  if (!indicator || !valueEl) return;

  const viewport = State.getViewport();
  valueEl.textContent = `${Math.round(viewport.zoom * 100)}%`;
  indicator.hidden = false;

  clearTimeout(zoomIndicatorTimer);
  zoomIndicatorTimer = setTimeout(() => { indicator.hidden = true; }, 800);
}

function clampZoom(zoom) {
  return Math.max(0.25, Math.min(2.0, zoom));
}

// ---- Canvas mouse interactions ----

function wireCanvasEvents() {
  const canvas = getCanvasElement();
  if (!canvas) return;

  canvas.addEventListener('mousedown', handleMouseDown);
  canvas.addEventListener('mousemove', handleMouseMove);
  canvas.addEventListener('mouseup', handleMouseUp);
  canvas.addEventListener('mouseleave', handleMouseUp);
  canvas.addEventListener('dblclick', handleDoubleClick);
  canvas.addEventListener('wheel', handleWheel, { passive: false });
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
}

function handleMouseDown(e) {
  const canvas = getCanvasElement();
  const rect = canvas.getBoundingClientRect();
  const screenX = e.clientX - rect.left;
  const screenY = e.clientY - rect.top;
  const canvasPos = screenToCanvas(screenX, screenY);

  if (e.button === 1) {
    startPan(e);
    return;
  }

  if (e.button !== 0) return;

  const hit = getBlockAtPoint(canvasPos.x, canvasPos.y);

  if (hit && hit.columnIndex === -1) {
    startDrag(hit.tableName, canvasPos, e.shiftKey);
  } else if (hit && hit.columnIndex >= 0) {
    handleColumnClick(hit.tableName, hit.columnIndex, e.shiftKey);
  } else if (hit) {
    handleBlockClick(hit.tableName, e.shiftKey);
  } else {
    startPan(e);
  }
}

function startDrag(tableName, canvasPos, shiftKey) {
  isDragging = true;
  dragTarget = tableName;

  const selected = State.getStateRef().selectedTables;
  const isSelected = selected.includes(tableName);

  if (!isSelected && !shiftKey) {
    State.setSelectedTables([tableName]);
  } else if (!isSelected && shiftKey) {
    State.setSelectedTables([...selected, tableName]);
  }

  const draggedTables = State.getStateRef().selectedTables.includes(tableName)
    ? State.getStateRef().selectedTables
    : [tableName];

  const positions = State.getPositions();
  dragOffsets = {};
  for (const name of draggedTables) {
    const pos = positions[name];
    if (!pos) continue;
    dragOffsets[name] = { x: canvasPos.x - pos.x, y: canvasPos.y - pos.y };
  }
}

function startPan(e) {
  isPanning = true;
  panStart = { x: e.clientX, y: e.clientY };
  panViewportStart = State.getViewport();
}

function handleMouseMove(e) {
  const canvas = getCanvasElement();
  const rect = canvas.getBoundingClientRect();
  const screenX = e.clientX - rect.left;
  const screenY = e.clientY - rect.top;

  if (isDragging) {
    handleDragMove(screenX, screenY);
    return;
  }

  if (isPanning) {
    handlePanMove(e);
    return;
  }

  handleHoverMove(screenX, screenY);
}

function handleDragMove(screenX, screenY) {
  const canvasPos = screenToCanvas(screenX, screenY);
  for (const [name, offset] of Object.entries(dragOffsets)) {
    State.moveBlock(name, { x: canvasPos.x - offset.x, y: canvasPos.y - offset.y });
  }
}

function handlePanMove(e) {
  const dx = e.clientX - panStart.x;
  const dy = e.clientY - panStart.y;
  State.setViewport({
    panX: panViewportStart.panX + dx,
    panY: panViewportStart.panY + dy,
  });
}

function handleHoverMove(screenX, screenY) {
  const canvasPos = screenToCanvas(screenX, screenY);
  const hit = getBlockAtPoint(canvasPos.x, canvasPos.y);

  if (hit) {
    const tables = State.getTables();
    const table = tables.find((t) => t.name === hit.tableName);
    State.setHoveredTable(hit.tableName);

    if (hit.columnIndex >= 0 && table && table.columns[hit.columnIndex]) {
      State.setHoveredColumn({ table: hit.tableName, column: table.columns[hit.columnIndex].name });
    } else {
      State.setHoveredColumn(null);
    }
    State.setHoveredConnection(null);
    return;
  }

  const nearConn = isPointNearConnection(canvasPos.x, canvasPos.y);
  if (nearConn) {
    State.setHoveredConnection(nearConn);
    State.setHoveredTable(null);
    State.setHoveredColumn(null);
    return;
  }

  clearAllHover();
}

function clearAllHover() {
  State.setHoveredTable(null);
  State.setHoveredColumn(null);
  State.setHoveredConnection(null);
}

function handleMouseUp() {
  if (isDragging) {
    isDragging = false;
    dragTarget = null;
    dragOffsets = {};
  }
  if (isPanning) {
    isPanning = false;
    panStart = null;
    panViewportStart = null;
  }
}

function handleColumnClick(tableName, columnIndex, shiftKey) {
  const tables = State.getTables();
  const table = tables.find((t) => t.name === tableName);
  if (!table || !table.columns[columnIndex]) return;

  const col = table.columns[columnIndex];

  // Lock selection on this column — only ESC clears it
  State.setSelectedColumn({ table: tableName, column: col.name });

  if (!shiftKey) {
    State.setSelectedTables([tableName]);
  }
}

function handleBlockClick(tableName, shiftKey) {
  const selected = State.getStateRef().selectedTables;
  if (shiftKey) {
    const updated = selected.includes(tableName)
      ? selected.filter((n) => n !== tableName)
      : [...selected, tableName];
    State.setSelectedTables(updated);
  } else {
    State.setSelectedTables([tableName]);
  }
}

function handleDoubleClick(e) {
  const canvas = getCanvasElement();
  const rect = canvas.getBoundingClientRect();
  const screenX = e.clientX - rect.left;
  const screenY = e.clientY - rect.top;
  const canvasPos = screenToCanvas(screenX, screenY);
  const hit = getBlockAtPoint(canvasPos.x, canvasPos.y);

  if (hit && hit.columnIndex === -1) {
    State.toggleCollapse(hit.tableName);
  }
}

function handleWheel(e) {
  if (!e.ctrlKey && !e.metaKey) return;
  e.preventDefault();

  const canvas = getCanvasElement();
  const rect = canvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left;
  const mouseY = e.clientY - rect.top;

  const viewport = State.getViewport();
  const zoomDelta = e.deltaY > 0 ? -0.05 : 0.05;
  const newZoom = clampZoom(viewport.zoom * (1 + zoomDelta));
  const ratio = newZoom / viewport.zoom;

  State.setViewport({
    zoom: newZoom,
    panX: mouseX - (mouseX - viewport.panX) * ratio,
    panY: mouseY - (mouseY - viewport.panY) * ratio,
  });

  updateZoomLabel();
  showZoomIndicator();
}

// ---- Toolbar wiring ----

function wireToolbar() {
  wireLayoutButton();
  wireFitButton();
  wireZoomButtons();
}

function wireLayoutButton() {
  const btn = document.getElementById('btn-layout');
  if (!btn) return;

  btn.addEventListener('click', () => {
    const algo = LAYOUT_ALGORITHMS[currentLayoutIndex];
    const newPositions = algo.fn();
    if (Object.keys(newPositions).length === 0) return;

    Layout.applyLayoutWithUndo(newPositions, showToast);
    showToast(`Layout: ${algo.name}`);

    currentLayoutIndex = (currentLayoutIndex + 1) % LAYOUT_ALGORITHMS.length;
  });
}

function wireFitButton() {
  const btn = document.getElementById('btn-fit');
  if (!btn) return;
  btn.addEventListener('click', fitToView);
}

function wireZoomButtons() {
  const btnIn = document.getElementById('btn-zoom-in');
  const btnOut = document.getElementById('btn-zoom-out');

  if (btnIn) btnIn.addEventListener('click', () => zoomByFactor(1.1));
  if (btnOut) btnOut.addEventListener('click', () => zoomByFactor(0.9));
}

function zoomByFactor(factor) {
  const canvas = getCanvasElement();
  const viewport = State.getViewport();
  const newZoom = clampZoom(viewport.zoom * factor);
  const ratio = newZoom / viewport.zoom;
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;

  State.setViewport({
    zoom: newZoom,
    panX: cx - (cx - viewport.panX) * ratio,
    panY: cy - (cy - viewport.panY) * ratio,
  });

  updateZoomLabel();
  showZoomIndicator();
}

function fitToView() {
  const positions = State.getPositions();
  const tables = State.getTables();
  if (tables.length === 0) return;

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

  for (const t of tables) {
    const p = positions[t.name];
    if (!p) continue;
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x + (p.width || 200));
    maxY = Math.max(maxY, p.y + (p.height || 200));
  }

  if (!isFinite(minX)) return;

  const canvas = getCanvasElement();
  const padding = 40;
  const contentW = maxX - minX + padding * 2;
  const contentH = maxY - minY + padding * 2;
  const zoom = clampZoom(Math.min(canvas.width / contentW, canvas.height / contentH));

  State.setViewport({
    zoom,
    panX: (canvas.width - contentW * zoom) / 2 - minX * zoom + padding * zoom,
    panY: (canvas.height - contentH * zoom) / 2 - minY * zoom + padding * zoom,
  });

  updateZoomLabel();
}

// ---- Keyboard shortcuts ----

function wireKeyboard() {
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
      e.preventDefault();
      State.setSelectedTables(State.getTableNames());
      return;
    }

    if (e.key === 'Escape') {
      State.setSelectedColumn(null);
      State.setSelectedTables([]);
      return;
    }

    if (e.key === 'Delete' || e.key === 'Backspace') {
      removeSelectedTables();
      return;
    }
  });
}

function removeSelectedTables() {
  const selected = [...State.getStateRef().selectedTables];
  if (selected.length === 0) return;

  selected.forEach((name) => State.removeTable(name));
  showToast(`Removed ${selected.length} table(s)`);
}

// ---- Pan-to-table (from sidebar click) ----

function handlePanToTable(tableName) {
  const positions = State.getPositions();
  const pos = positions[tableName];
  if (!pos) return;

  const canvas = getCanvasElement();
  const width = pos.width || 200;
  const height = pos.height || 200;
  const viewport = State.getViewport();

  const targetPanX = canvas.width / 2 - (pos.x + width / 2) * viewport.zoom;
  const targetPanY = canvas.height / 2 - (pos.y + height / 2) * viewport.zoom;

  State.setViewport({ panX: targetPanX, panY: targetPanY });
  State.setSelectedTables([tableName]);
}

// ---- Event subscriptions ----

let renderScheduled = false;

function scheduleRender() {
  if (renderScheduled) return;
  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    render();
  });
}

function wireEventSubscriptions() {
  // Single render trigger via rAF batching — prevents multiple renders per synchronous event burst
  EventBus.on('stateChanged', scheduleRender);
  EventBus.on('viewportChanged', scheduleRender);
  EventBus.on('layoutChanged', scheduleRender);
  EventBus.on('tableAdded', scheduleRender);
  EventBus.on('tableRemoved', scheduleRender);
  EventBus.on('filterChanged', scheduleRender);
  EventBus.on('stateReset', scheduleRender);
  EventBus.on('blockCollapsed', scheduleRender);
  EventBus.on('blockExpanded', scheduleRender);
  EventBus.on('connectionAdded', scheduleRender);
  EventBus.on('connectionRemoved', scheduleRender);
  EventBus.on('themeChanged', scheduleRender);
  EventBus.on('panToTable', handlePanToTable);

  // Trace animation: only redraws connection layer (not full render) for performance
  EventBus.on('traceResultsReady', (trace) => {
    if (trace && trace.edges && trace.edges.length > 0) {
      startTraceAnimation(render);
    } else {
      stopTraceAnimation();
      scheduleRender();
    }
  });
  EventBus.on('searchCleared', () => {
    stopTraceAnimation();
    scheduleRender();
  });
}

// ---- Initialization ----

function init() {
  const canvasEl = document.getElementById('diagram-canvas');
  if (!canvasEl) return;

  initTheme();
  initCanvas(canvasEl);
  initUpload();
  initSearch();
  initTrace();
  initFilters();
  initExport();
  initTableViewer();
  initAdvisor();
  initRebuilder();
  wireEventSubscriptions();
  wireCanvasEvents();
  wireToolbar();
  wireKeyboard();
  wireSidebarCollapseToggles();
  wireLegend();
  wireClearSelection();
  render();
  updateZoomLabel();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

// ---- Sidebar section collapse/expand ----

function wireClearSelection() {
  const btn = document.getElementById('btn-clear-selection');
  if (!btn) return;

  btn.addEventListener('click', () => {
    State.setSelectedColumn(null);
    State.setSelectedTables([]);
  });

  // Show/hide button based on selectedColumn state
  EventBus.on('stateChanged', ({ key }) => {
    if (key === 'selectedColumn') {
      const col = State.getSelectedColumn();
      btn.hidden = !col;
    }
  });
}

function wireLegend() {
  const legend = document.getElementById('legend');
  const closeBtn = document.getElementById('legend-close');
  if (!legend || !closeBtn) return;

  closeBtn.addEventListener('click', () => {
    legend.classList.add('legend--hidden');
  });
}

function wireSidebarCollapseToggles() {
  document.querySelectorAll('.sidebar__section-title--toggle').forEach((title) => {
    title.addEventListener('click', () => {
      const section = title.closest('.sidebar__section');
      if (section) section.classList.toggle('sidebar__section--collapsed');
    });
  });
}
