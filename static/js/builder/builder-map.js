/**
 * builder-map.js — Canvas-based relationship map for the builder output panel.
 * Renders simplified table boxes with FK connection lines.
 * Read-only overview — no editing, just visualization.
 */

import { getTargetSchema } from './builder-state.js';
import { MAP_BOX, MAP_COLORS, MAP_COLORS_DARK, MAP_LINE } from './builder-constants.js';
import {
  chooseSides, calculateAnchor, drawBezierConnection,
  drawSelfRefConnection, drawTick, drawCrowFoot,
} from './builder-connections.js';

let canvas = null;
let ctx = null;
let mapPositions = {};
let viewport = { zoom: 1, panX: 40, panY: 40 };
let hoveredTable = null;
let isPanning = false;
let panStart = { x: 0, y: 0 };
let lastSchemaKey = null;
let panRafId = null;

function getColors() {
  return document.body.classList.contains('dark') ? MAP_COLORS_DARK : MAP_COLORS;
}

// ---- Public API ----

export function initMap() {
  canvas = document.getElementById('builder-map-canvas');
  if (!canvas) return;
  ctx = canvas.getContext('2d');
  if (!ctx) return;

  canvas.addEventListener('mousedown', onMouseDown);
  canvas.addEventListener('mousemove', onMouseMove);
  canvas.addEventListener('mouseup', onMouseUp);
  canvas.addEventListener('mouseleave', onMouseUp);
  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('click', onClick);

  let resizeTimer = null;
  const observer = new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      sizeCanvas();
      renderMap();
    }, 50);
  });
  if (canvas.parentElement) {
    observer.observe(canvas.parentElement);
  }
}

export function renderMap() {
  if (!canvas || !ctx) return;

  const tabContent = document.getElementById('tab-map');
  if (!tabContent || !tabContent.classList.contains('builder-output__content--active')) return;

  sizeCanvas();

  const schema = getTargetSchema();
  const colors = getColors();

  // Recompute layout when tables, columns, or FK relationships change
  const schemaKey = schema.tables.map(t => {
    const fks = t.constraints.filter(c => c.type === 'fk').map(c => c.refTable).sort().join(',');
    return t.name + '#' + t.columns.length + (fks ? ':' + fks : '');
  }).join('\0');
  if (schemaKey !== lastSchemaKey) {
    mapPositions = computeLayout(schema);
    lastSchemaKey = schemaKey;
    autoFit();
  }

  // Clear
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = colors.bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  drawGrid(colors, dpr);

  // Apply viewport
  ctx.setTransform(
    viewport.zoom * dpr, 0, 0, viewport.zoom * dpr,
    viewport.panX * dpr, viewport.panY * dpr
  );

  if (schema.tables.length === 0) {
    drawEmptyMessage(dpr);
    return;
  }

  drawAllConnections(schema, colors);

  for (const table of schema.tables) {
    const pos = mapPositions[table.name];
    if (!pos) continue;
    drawTableBox(table, pos, colors, table.name === hoveredTable);
  }
}

// ---- Layout ----

function computeLayout(schema) {
  const tables = schema.tables;
  if (tables.length === 0) return {};

  const tableMap = Object.fromEntries(tables.map(t => [t.name, t]));
  const tableNames = new Set(tables.map(t => t.name));

  // BFS depth assignment: referenced (parent) tables get lower depth
  const children = {};
  const inDegree = {};
  for (const name of tableNames) {
    children[name] = [];
    inDegree[name] = 0;
  }

  for (const t of tables) {
    for (const c of t.constraints) {
      if (c.type !== 'fk' || c.refTable === t.name || !tableNames.has(c.refTable)) continue;
      // refTable is parent → t.name is child
      children[c.refTable].push(t.name);
      inDegree[t.name]++;
    }
  }

  // BFS to assign depth levels
  const depth = {};
  const queue = [];
  for (const name of tableNames) {
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

  // Cyclic tables go to last row
  for (const name of tableNames) {
    if (depth[name] === undefined) depth[name] = maxDepth + 1;
  }

  // Group by depth into rows
  const rows = {};
  for (const [name, d] of Object.entries(depth)) {
    if (!rows[d]) rows[d] = [];
    rows[d].push(name);
  }

  // Place boxes: each depth row centered horizontally
  const rowKeys = Object.keys(rows).map(Number).sort((a, b) => a - b);
  const positions = {};
  let y = 0;

  for (const key of rowKeys) {
    const row = rows[key];
    const rowWidth = row.length * MAP_BOX.width + (row.length - 1) * MAP_BOX.gapX;
    let x = -rowWidth / 2;
    let maxH = 0;

    for (const name of row) {
      const table = tableMap[name];
      const height = boxHeight(table);
      positions[name] = { x, y, width: MAP_BOX.width, height };
      maxH = Math.max(maxH, height);
      x += MAP_BOX.width + MAP_BOX.gapX;
    }

    y += maxH + MAP_BOX.gapY;
  }

  return positions;
}

function boxHeight(table) {
  return MAP_BOX.headerHeight + MAP_BOX.bodyPadding * 2 +
    table.columns.length * MAP_BOX.lineHeight;
}

function autoFit() {
  const keys = Object.keys(mapPositions);
  if (keys.length === 0) return;

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const k of keys) {
    const p = mapPositions[k];
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x + p.width);
    maxY = Math.max(maxY, p.y + p.height);
  }

  const contentW = maxX - minX;
  const contentH = maxY - minY;
  const pad = 40;
  const w = canvas.width / (window.devicePixelRatio || 1);
  const h = canvas.height / (window.devicePixelRatio || 1);
  const availW = w - pad * 2;
  const availH = h - pad * 2;

  if (contentW === 0 || contentH === 0) {
    viewport = { zoom: 1, panX: pad, panY: pad };
    return;
  }

  const zoom = Math.min(1.5, Math.min(availW / contentW, availH / contentH));
  viewport.zoom = zoom;
  viewport.panX = pad + (availW - contentW * zoom) / 2 - minX * zoom;
  viewport.panY = pad + (availH - contentH * zoom) / 2 - minY * zoom;
}

// ---- Drawing ----

function drawGrid(colors, dpr) {
  const spacing = 20;
  const dotR = 1;

  ctx.setTransform(
    viewport.zoom * dpr, 0, 0, viewport.zoom * dpr,
    viewport.panX * dpr, viewport.panY * dpr
  );

  const left = -viewport.panX / viewport.zoom;
  const top = -viewport.panY / viewport.zoom;
  const w = canvas.width / dpr;
  const h = canvas.height / dpr;
  const right = (w - viewport.panX) / viewport.zoom;
  const bottom = (h - viewport.panY) / viewport.zoom;

  const startX = Math.floor(left / spacing) * spacing;
  const startY = Math.floor(top / spacing) * spacing;

  ctx.fillStyle = colors.dot;
  for (let x = startX; x <= right; x += spacing) {
    for (let y = startY; y <= bottom; y += spacing) {
      ctx.fillRect(x - dotR, y - dotR, dotR * 2, dotR * 2);
    }
  }
}

function drawTableBox(table, pos, colors, isHovered) {
  const { x, y, width, height } = pos;
  const r = MAP_BOX.cornerRadius;

  ctx.save();
  ctx.shadowColor = isHovered ? colors.shadowHover : colors.shadow;
  ctx.shadowBlur = isHovered ? 8 : 3;
  ctx.shadowOffsetY = isHovered ? 2 : 1;

  roundRect(ctx, x, y, width, height, r);
  ctx.fillStyle = colors.boxBg;
  ctx.fill();
  ctx.restore();

  roundRect(ctx, x, y, width, height, r);
  ctx.strokeStyle = isHovered ? colors.boxBorderHover : colors.boxBorder;
  ctx.lineWidth = isHovered ? 2 : 1;
  ctx.stroke();

  // Header bg
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.arcTo(x + width, y, x + width, y + r, r);
  ctx.lineTo(x + width, y + MAP_BOX.headerHeight);
  ctx.lineTo(x, y + MAP_BOX.headerHeight);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
  ctx.fillStyle = colors.boxHeader;
  ctx.fill();
  ctx.restore();

  // Header divider
  ctx.beginPath();
  ctx.moveTo(x, y + MAP_BOX.headerHeight);
  ctx.lineTo(x + width, y + MAP_BOX.headerHeight);
  ctx.strokeStyle = colors.boxBorder;
  ctx.lineWidth = 1;
  ctx.stroke();

  // Table name
  ctx.fillStyle = colors.boxText;
  ctx.font = 'bold 11px sans-serif';
  ctx.textBaseline = 'middle';
  const nameText = table.name.length > 18 ? table.name.slice(0, 17) + '\u2026' : table.name;
  ctx.fillText(nameText, x + 8, y + MAP_BOX.headerHeight / 2);

  // Column summary
  ctx.font = '10px sans-serif';
  ctx.fillStyle = colors.boxSubtext;
  const cols = table.columns;
  let cy = y + MAP_BOX.headerHeight + MAP_BOX.bodyPadding;

  for (const col of cols) {
    const hasPk = col.isPrimaryKey;
    const hasFk = table.constraints.some(c => c.type === 'fk' && c.columns.includes(col.name));

    if (hasPk) {
      ctx.fillStyle = colors.pkDot;
      ctx.fillRect(x + 6, cy + 4, 4, 4);
    } else if (hasFk) {
      ctx.fillStyle = colors.lineFk;
      ctx.fillRect(x + 6, cy + 4, 4, 4);
    }

    ctx.fillStyle = colors.boxSubtext;
    const colText = col.name.length > 16 ? col.name.slice(0, 15) + '\u2026' : col.name;
    ctx.fillText(colText, x + 14, cy + MAP_BOX.lineHeight / 2 + 1);
    cy += MAP_BOX.lineHeight;
  }
}

/** Get the Y offset from box top to the center of a column row. */
function columnYOffset(table, columnName) {
  const idx = table.columns.findIndex(c => c.name === columnName);
  if (idx < 0) {
    return MAP_BOX.headerHeight + MAP_BOX.bodyPadding + table.columns.length * MAP_BOX.lineHeight - MAP_BOX.lineHeight / 2;
  }
  return MAP_BOX.headerHeight + MAP_BOX.bodyPadding + idx * MAP_BOX.lineHeight + MAP_BOX.lineHeight / 2;
}

function drawAllConnections(schema, colors) {
  const tableMap = Object.fromEntries(schema.tables.map(t => [t.name, t]));

  for (const table of schema.tables) {
    for (const constraint of table.constraints) {
      if (constraint.type !== 'fk') continue;

      const srcPos = mapPositions[table.name];
      const tgtPos = mapPositions[constraint.refTable];
      if (!srcPos || !tgtPos) continue;

      const tgtTable = tableMap[constraint.refTable];
      if (!tgtTable) continue;

      const isSelf = table.name === constraint.refTable;
      const isHighlighted = hoveredTable === table.name || hoveredTable === constraint.refTable;

      const hasUnique = table.constraints.some(c =>
        (c.type === 'unique' || c.type === 'pk') &&
        c.columns.length === constraint.columns.length &&
        constraint.columns.every(col => c.columns.includes(col))
      );
      const cardinality = hasUnique ? 'one-to-one' : 'one-to-many';

      const color = isSelf ? colors.lineSelf : colors.lineFk;
      const lineWidth = isHighlighted ? MAP_LINE.strokeWidthHover : MAP_LINE.strokeWidth;
      ctx.globalAlpha = isHighlighted ? 1.0 : (hoveredTable ? 0.2 : 0.7);

      // Anchor Y at the specific FK / referenced column row
      const srcColY = columnYOffset(table, constraint.columns[0]);
      const tgtColY = columnYOffset(tgtTable, constraint.refColumns[0]);

      if (isSelf) {
        const srcY = srcPos.y + srcColY;
        const tgtY = srcPos.y + tgtColY;
        const anchors = drawSelfRefConnection(ctx, srcPos, srcY, tgtY, color, lineWidth);
        drawCrowFoot(ctx, anchors.srcAnchor, color);
        drawTick(ctx, anchors.tgtAnchor, color);
      } else {
        const { srcSide, tgtSide } = chooseSides(srcPos, tgtPos);
        const srcAnchor = calculateAnchor(srcPos, srcSide, srcColY);
        const tgtAnchor = calculateAnchor(tgtPos, tgtSide, tgtColY);

        drawBezierConnection(ctx, srcAnchor, tgtAnchor, color, lineWidth);
        drawTick(ctx, tgtAnchor, color);
        if (cardinality === 'one-to-many') {
          drawCrowFoot(ctx, srcAnchor, color);
        } else {
          drawTick(ctx, srcAnchor, color);
        }
      }

      ctx.globalAlpha = 1.0;
    }
  }
}

function drawEmptyMessage(dpr) {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const colors = getColors();
  const w = canvas.width / dpr;
  const h = canvas.height / dpr;
  ctx.fillStyle = colors.boxSubtext;
  ctx.font = '13px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Add tables to see the relationship map', w / 2, h / 2);
  ctx.textAlign = 'start';
}

// ---- Interaction ----

function screenToCanvas(sx, sy) {
  return {
    x: (sx - viewport.panX) / viewport.zoom,
    y: (sy - viewport.panY) / viewport.zoom,
  };
}

function getMousePos(e) {
  const rect = canvas.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

function hitTestBox(cx, cy) {
  for (const [name, pos] of Object.entries(mapPositions)) {
    if (cx >= pos.x && cx <= pos.x + pos.width && cy >= pos.y && cy <= pos.y + pos.height) {
      return name;
    }
  }
  return null;
}

function onMouseDown(e) {
  if (e.button !== 0) return;
  isPanning = true;
  panStart = getMousePos(e);
  canvas.style.cursor = 'grabbing';
}

function onMouseMove(e) {
  const pos = getMousePos(e);

  if (isPanning) {
    viewport.panX += pos.x - panStart.x;
    viewport.panY += pos.y - panStart.y;
    panStart = pos;
    if (!panRafId) {
      panRafId = requestAnimationFrame(() => {
        panRafId = null;
        renderMap();
      });
    }
    return;
  }

  const { x, y } = screenToCanvas(pos.x, pos.y);
  const hit = hitTestBox(x, y);

  if (hit !== hoveredTable) {
    hoveredTable = hit;
    canvas.style.cursor = hit ? 'pointer' : 'grab';
    renderMap();
  }
}

function onMouseUp() {
  isPanning = false;
  canvas.style.cursor = hoveredTable ? 'pointer' : 'grab';
}

function onWheel(e) {
  e.preventDefault();
  const pos = getMousePos(e);
  const { x: cx, y: cy } = screenToCanvas(pos.x, pos.y);

  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  const newZoom = Math.max(0.2, Math.min(4, viewport.zoom * factor));

  viewport.panX = pos.x - cx * newZoom;
  viewport.panY = pos.y - cy * newZoom;
  viewport.zoom = newZoom;

  renderMap();
}

function onClick(e) {
  if (isPanning) return;
  const pos = getMousePos(e);
  const { x, y } = screenToCanvas(pos.x, pos.y);
  const hit = hitTestBox(x, y);

  if (hit) {
    const card = document.querySelector(`.builder-table-card[data-table="${CSS.escape(hit)}"]`);
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      card.classList.add('builder-table-card--fk-highlight');
      setTimeout(() => card.classList.remove('builder-table-card--fk-highlight'), 1500);
    }
  }
}

// ---- Utilities ----

function sizeCanvas() {
  if (!canvas) return;
  const parent = canvas.parentElement;
  if (!parent) return;
  const dpr = window.devicePixelRatio || 1;
  const w = parent.clientWidth;
  const h = parent.clientHeight;
  const targetW = Math.round(w * dpr);
  const targetH = Math.round(h * dpr);
  if (canvas.width !== targetW || canvas.height !== targetH) {
    canvas.width = targetW;
    canvas.height = targetH;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
  }
}

function roundRect(ctx, x, y, w, h, r) {
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
