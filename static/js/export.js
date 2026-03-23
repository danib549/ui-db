/**
 * export.js — Diagram export (PNG, JSON).
 */

import * as State from './state.js';
import { getCanvasElement } from './canvas.js';

export function initExport() {
  const btn = document.getElementById('btn-export');
  if (!btn) return;

  btn.addEventListener('click', toggleExportMenu);
}

function toggleExportMenu() {
  let menu = document.getElementById('export-menu');
  if (menu) {
    menu.remove();
    return;
  }

  menu = document.createElement('div');
  menu.id = 'export-menu';
  menu.className = 'toolbar__dropdown-menu';
  menu.innerHTML = `
    <button class="toolbar__dropdown-item" data-export="png">Export PNG</button>
    <button class="toolbar__dropdown-item" data-export="json">Export JSON</button>
  `;

  const btn = document.getElementById('btn-export');
  btn.parentElement.appendChild(menu);

  menu.querySelector('[data-export="png"]').addEventListener('click', () => {
    exportPNG();
    menu.remove();
  });
  menu.querySelector('[data-export="json"]').addEventListener('click', () => {
    exportJSON();
    menu.remove();
  });

  setTimeout(() => {
    const close = (e) => {
      if (!menu.contains(e.target) && e.target !== btn) {
        menu.remove();
        document.removeEventListener('click', close);
      }
    };
    document.addEventListener('click', close);
  }, 0);
}

function exportPNG() {
  const canvas = getCanvasElement();
  if (!canvas) return;

  const scale = 2;
  const exportCanvas = document.createElement('canvas');
  exportCanvas.width = canvas.width * scale;
  exportCanvas.height = canvas.height * scale;
  const ctx = exportCanvas.getContext('2d');
  ctx.scale(scale, scale);
  ctx.drawImage(canvas, 0, 0);

  exportCanvas.toBlob((blob) => {
    if (!blob) return;
    downloadBlob(blob, 'diagram.png');
  }, 'image/png');
}

function exportJSON() {
  const data = State.exportState();
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  downloadBlob(blob, 'diagram.json');
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
