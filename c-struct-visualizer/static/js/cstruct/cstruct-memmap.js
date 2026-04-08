/**
 * cstruct-memmap.js — Byte-level memory map visualization.
 * Shows a hex-grid view of a struct's memory layout with each byte
 * colored by its owning field.
 */

import { EventBus } from '../events.js';
import { getEntity, getMemoryMapEntity, setMemoryMapEntity } from './cstruct-state.js';
import { CATEGORY_COLORS, CATEGORY_COLORS_DARK } from './cstruct-constants.js';
import { escapeHtml } from '../utils.js';

const COLS = 16; // bytes per row

export function initMemoryMap() {
  EventBus.on('cstructStateChanged', ({ key }) => {
    if (key === 'memoryMapEntity') {
      const name = getMemoryMapEntity();
      if (name) openMemoryMap(name);
      else closeMemoryMap();
    }
  });

  const closeBtn = document.getElementById('memmap-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => setMemoryMapEntity(null));
  }

  const overlay = document.getElementById('memmap-overlay');
  if (overlay) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) setMemoryMapEntity(null);
    });
  }
}

function openMemoryMap(entityName) {
  const overlay = document.getElementById('memmap-overlay');
  const titleEl = document.getElementById('memmap-title');
  const body = document.getElementById('memmap-body');
  if (!overlay || !body) return;

  const entity = getEntity(entityName);
  if (!entity || !entity.fields) return;

  const displayName = entity.displayName || entity.name;
  titleEl.textContent = `Memory Map: ${displayName} (${entity.totalSize} bytes)`;

  const byteMap = buildByteMap(entity);
  body.innerHTML = renderGrid(byteMap, entity.totalSize);
  overlay.hidden = false;

  // Hover tooltips
  body.querySelectorAll('.memmap-cell[data-field]').forEach(cell => {
    cell.addEventListener('mouseenter', () => {
      const tip = cell.querySelector('.memmap-tooltip');
      if (tip) tip.hidden = false;
    });
    cell.addEventListener('mouseleave', () => {
      const tip = cell.querySelector('.memmap-tooltip');
      if (tip) tip.hidden = true;
    });
  });
}

function closeMemoryMap() {
  const overlay = document.getElementById('memmap-overlay');
  if (overlay) overlay.hidden = true;
}

function buildByteMap(entity) {
  const totalSize = entity.totalSize || 0;
  const map = new Array(totalSize).fill(null);

  for (const field of entity.fields) {
    if (field.offset == null || field.size == null) continue;
    const start = field.offset;
    const end = start + field.size;
    for (let i = start; i < end && i < totalSize; i++) {
      map[i] = {
        fieldName: field.name,
        type: field.type,
        category: field.category || 'integer',
        offset: field.offset,
        size: field.size,
        isPadding: field.category === 'padding',
        bitSize: field.bitSize || null,
      };
    }
  }

  return map;
}

function renderGrid(byteMap, totalSize) {
  const isDark = document.body.classList.contains('dark');
  const colors = isDark ? CATEGORY_COLORS_DARK : CATEGORY_COLORS;

  // Column headers
  let html = '<div class="memmap-grid">';
  html += '<div class="memmap-row memmap-row--header">';
  html += '<div class="memmap-cell memmap-cell--offset"></div>';
  for (let c = 0; c < COLS; c++) {
    html += `<div class="memmap-cell memmap-cell--colheader">+${c.toString(16).toUpperCase()}</div>`;
  }
  html += '</div>';

  // Data rows
  const rows = Math.ceil(totalSize / COLS);
  for (let r = 0; r < rows; r++) {
    html += '<div class="memmap-row">';
    const rowOffset = r * COLS;
    html += `<div class="memmap-cell memmap-cell--offset">0x${rowOffset.toString(16).toUpperCase().padStart(4, '0')}</div>`;
    for (let c = 0; c < COLS; c++) {
      const byteIdx = rowOffset + c;
      if (byteIdx >= totalSize) {
        html += '<div class="memmap-cell memmap-cell--empty"></div>';
        continue;
      }
      const info = byteMap[byteIdx];
      if (!info) {
        html += '<div class="memmap-cell memmap-cell--unused"></div>';
        continue;
      }
      const color = colors[info.category] || colors.integer;
      const opacity = info.isPadding ? '0.3' : '0.6';
      const stripes = info.isPadding ? ' memmap-cell--padding' : '';
      const tooltip = info.isPadding
        ? `Padding (byte ${byteIdx})`
        : `${info.fieldName}: ${info.type}\nOffset: ${info.offset}, Size: ${info.size}${info.bitSize ? ` (${info.bitSize} bits)` : ''}`;
      html += `<div class="memmap-cell${stripes}" data-field="${escapeHtml(info.fieldName)}"
        style="background-color: ${color}; opacity: ${opacity}">
        <span class="memmap-cell__label">${byteIdx.toString(16).toUpperCase().padStart(2, '0')}</span>
        <div class="memmap-tooltip" hidden>${escapeHtml(tooltip)}</div>
      </div>`;
    }
    html += '</div>';
  }

  html += '</div>';

  // Legend
  html += '<div class="memmap-legend">';
  const seen = new Set();
  for (const info of byteMap) {
    if (!info || info.isPadding || seen.has(info.fieldName)) continue;
    seen.add(info.fieldName);
    const color = colors[info.category] || colors.integer;
    html += `<div class="memmap-legend__item">
      <span class="memmap-legend__swatch" style="background:${color}"></span>
      <span>${escapeHtml(info.fieldName)} (${escapeHtml(info.type)})</span>
    </div>`;
  }
  // Add padding to legend if present
  if (byteMap.some(b => b?.isPadding)) {
    const pColor = colors.padding || '#999';
    html += `<div class="memmap-legend__item">
      <span class="memmap-legend__swatch memmap-legend__swatch--padding" style="background:${pColor}"></span>
      <span>Padding</span>
    </div>`;
  }
  html += '</div>';

  return html;
}
