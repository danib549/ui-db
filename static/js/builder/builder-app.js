/**
 * builder-app.js — Orchestrator for the PostgreSQL Schema Builder page.
 * Initializes modules, wires events, owns the render cycle.
 */

import { EventBus } from '../events.js';
import { getTargetSchema } from './builder-state.js';
import { initPanels, renderSourcePanel, renderTargetPanel } from './builder-panels.js';
import { initEditors } from './builder-editors.js';
import { initPickers } from './builder-pickers.js';
import { initOutput, refreshOutput } from './builder-output.js';
import { initRelationships } from './builder-relationships.js';
import { initMap, renderMap } from './builder-map.js';

let renderScheduled = false;

function scheduleRender() {
  if (renderScheduled) return;
  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    render();
  });
}

function render() {
  renderTargetPanel();
  refreshOutput();
  renderMap();
}

function initTheme() {
  const THEME_KEY = 'db-diagram-theme';
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === 'dark') {
    document.body.classList.add('dark');
  }

  const btn = document.getElementById('btn-theme');
  if (btn) {
    btn.addEventListener('click', () => {
      document.body.classList.toggle('dark');
      localStorage.setItem(THEME_KEY, document.body.classList.contains('dark') ? 'dark' : 'light');
    });
  }
}

function initKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Ctrl+S — Export .sql
    if (e.ctrlKey && !e.shiftKey && e.key === 's') {
      e.preventDefault();
      const btn = document.getElementById('export-sql');
      if (btn) btn.click();
    }

    // Ctrl+Shift+C — Copy DDL
    if (e.ctrlKey && e.shiftKey && e.key === 'C') {
      e.preventDefault();
      const btn = document.getElementById('copy-ddl');
      if (btn) btn.click();
    }

    // Escape — Close active editor/picker
    if (e.key === 'Escape') {
      const editor = document.getElementById('column-editor');
      const picker = document.getElementById('constraint-picker');
      const confirm = document.getElementById('confirm-dialog');
      if (confirm && !confirm.hidden) {
        confirm.hidden = true;
      } else if (editor && !editor.hidden) {
        editor.hidden = true;
      } else if (picker && !picker.hidden) {
        picker.hidden = true;
      }
    }
  });
}

function initOutputResize() {
  const handle = document.getElementById('output-resize-handle');
  const panel = document.getElementById('output-panel');
  if (!handle || !panel) return;

  let startX = 0;
  let startW = 0;

  const onMove = (e) => {
    const delta = startX - e.clientX;
    const newW = Math.max(260, Math.min(window.innerWidth * 0.7, startW + delta));
    panel.style.width = newW + 'px';
  };

  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    handle.classList.remove('builder-resize-handle--active');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  };

  handle.addEventListener('mousedown', (e) => {
    e.preventDefault();
    startX = e.clientX;
    startW = panel.offsetWidth;
    handle.classList.add('builder-resize-handle--active');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

function initTooltips() {
  const tooltip = document.getElementById('builder-tooltip');
  const tooltipText = document.getElementById('builder-tooltip-text');
  const tooltipArrow = document.getElementById('builder-tooltip-arrow');
  if (!tooltip || !tooltipText || !tooltipArrow) return;

  let hideTimer = null;

  const show = (target) => {
    clearTimeout(hideTimer);
    const raw = target.getAttribute('data-tooltip');
    if (!raw) return;

    // Render newlines as line breaks, escape HTML otherwise
    const safe = raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                     .replace(/\\n/g, '<br>');
    tooltipText.innerHTML = safe;
    tooltip.classList.add('builder-tooltip--visible');

    // Measure and position
    const rect = target.getBoundingClientRect();
    const ttRect = tooltip.getBoundingClientRect();
    const pad = 12;

    let top, left, arrowTop, arrowLeft;

    // Try above first
    top = rect.top - ttRect.height - 10;
    let placeBelow = false;

    if (top < pad) {
      // Place below instead
      top = rect.bottom + 10;
      placeBelow = true;
    }

    // Clamp bottom
    if (top + ttRect.height > window.innerHeight - pad) {
      top = window.innerHeight - ttRect.height - pad;
    }

    // Horizontal: center on target, clamp to viewport
    left = rect.left + rect.width / 2 - ttRect.width / 2;
    left = Math.max(pad, Math.min(left, window.innerWidth - ttRect.width - pad));

    tooltip.style.top = top + 'px';
    tooltip.style.left = left + 'px';

    // Arrow
    const arrowX = rect.left + rect.width / 2 - left - 4;
    tooltipArrow.style.left = Math.max(8, Math.min(arrowX, ttRect.width - 16)) + 'px';

    if (placeBelow) {
      tooltipArrow.style.top = '-4px';
      tooltipArrow.style.bottom = '';
    } else {
      tooltipArrow.style.bottom = '-4px';
      tooltipArrow.style.top = '';
    }
  };

  const hide = () => {
    hideTimer = setTimeout(() => {
      tooltip.classList.remove('builder-tooltip--visible');
    }, 80);
  };

  // Event delegation — works for dynamically created .builder-info elements too
  document.addEventListener('mouseenter', (e) => {
    const info = e.target.closest('.builder-info');
    if (info) show(info);
  }, true);

  document.addEventListener('mouseleave', (e) => {
    const info = e.target.closest('.builder-info');
    if (info) hide();
  }, true);
}

function init() {
  initTheme();
  initKeyboardShortcuts();
  initTooltips();
  initOutputResize();
  initPanels();
  initEditors();
  initPickers();
  initOutput();
  initRelationships();
  initMap();

  // Central render orchestration
  EventBus.on('builderStateChanged', scheduleRender);

  // Load source tables from backend
  renderSourcePanel();
}

// Boot when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
