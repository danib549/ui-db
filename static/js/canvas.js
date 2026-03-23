/**
 * canvas.js — Canvas Rendering Engine
 * Manages the HTML5 canvas element, viewport transforms, coordinate conversion,
 * background grid drawing, and visibility culling.
 */

import { EventBus } from './events.js';
import { getViewport } from './state.js';

// ---- Module state (not application state) ----
let canvasEl = null;
let ctx = null;

// ---- Background grid constants ----
const BG_COLOR = '#F9FAFB';
const DOT_COLOR = '#E5E7EB';
const DOT_RADIUS = 1;
const GRID_SPACING = 20;

// ---- Public API ----

/**
 * Initialize the canvas: store reference, get context, size to container, bind resize.
 * @param {HTMLCanvasElement} canvasElement
 */
export function initCanvas(canvasElement) {
  canvasEl = canvasElement;
  ctx = canvasEl.getContext('2d');
  resizeToContainer();
  window.addEventListener('resize', handleResize);
}

/** Return the 2D rendering context. */
export function getContext() {
  return ctx;
}

/** Return the canvas DOM element. */
export function getCanvasElement() {
  return canvasEl;
}

/**
 * Apply pan/zoom viewport transform to a context.
 * @param {CanvasRenderingContext2D} context
 * @param {{ zoom: number, panX: number, panY: number }} viewport
 */
export function applyViewportTransform(context, viewport) {
  context.setTransform(viewport.zoom, 0, 0, viewport.zoom, viewport.panX, viewport.panY);
}

/**
 * Reset a context to the identity transform.
 * @param {CanvasRenderingContext2D} context
 */
export function resetTransform(context) {
  context.setTransform(1, 0, 0, 1, 0, 0);
}

/**
 * Convert screen (pixel) coordinates to canvas (world) coordinates.
 * @param {number} screenX
 * @param {number} screenY
 * @returns {{ x: number, y: number }}
 */
export function screenToCanvas(screenX, screenY) {
  const viewport = getViewport();
  return {
    x: (screenX - viewport.panX) / viewport.zoom,
    y: (screenY - viewport.panY) / viewport.zoom,
  };
}

/**
 * Convert canvas (world) coordinates to screen (pixel) coordinates.
 * @param {number} canvasX
 * @param {number} canvasY
 * @returns {{ x: number, y: number }}
 */
export function canvasToScreen(canvasX, canvasY) {
  const viewport = getViewport();
  return {
    x: canvasX * viewport.zoom + viewport.panX,
    y: canvasY * viewport.zoom + viewport.panY,
  };
}

/**
 * Get the visible rectangle in canvas (world) coordinates — used for frustum culling.
 * @returns {{ left: number, top: number, right: number, bottom: number }}
 */
export function getVisibleRect() {
  const viewport = getViewport();
  return {
    left: -viewport.panX / viewport.zoom,
    top: -viewport.panY / viewport.zoom,
    right: (canvasEl.width - viewport.panX) / viewport.zoom,
    bottom: (canvasEl.height - viewport.panY) / viewport.zoom,
  };
}

/**
 * Check if a block intersects the visible area.
 * @param {{ x: number, y: number, width: number, height: number }} block
 * @returns {boolean}
 */
export function isBlockVisible(block) {
  const rect = getVisibleRect();
  if (block.x + block.width < rect.left) return false;
  if (block.x > rect.right) return false;
  if (block.y + block.height < rect.top) return false;
  if (block.y > rect.bottom) return false;
  return true;
}

/** Draw the dot-grid background in canvas coordinates. */
export function drawBackground() {
  const viewport = getViewport();

  // Fill entire canvas with background color in screen space
  resetTransform(ctx);
  ctx.fillStyle = BG_COLOR;
  ctx.fillRect(0, 0, canvasEl.width, canvasEl.height);

  // Adaptive spacing: increase grid step at low zoom to avoid drawing tens of thousands of dots
  const effectiveSpacing = GRID_SPACING * Math.ceil(1 / Math.max(viewport.zoom, 0.25));

  // Compute visible range in canvas coords
  const rect = getVisibleRect();
  const startX = Math.floor(rect.left / effectiveSpacing) * effectiveSpacing;
  const startY = Math.floor(rect.top / effectiveSpacing) * effectiveSpacing;
  const endX = Math.ceil(rect.right / effectiveSpacing) * effectiveSpacing;
  const endY = Math.ceil(rect.bottom / effectiveSpacing) * effectiveSpacing;

  // Draw dots in world space using fillRect (faster than arc for small dots)
  applyViewportTransform(ctx, viewport);
  ctx.fillStyle = DOT_COLOR;
  const dotSize = DOT_RADIUS * 2;

  for (let x = startX; x <= endX; x += effectiveSpacing) {
    for (let y = startY; y <= endY; y += effectiveSpacing) {
      ctx.fillRect(x - DOT_RADIUS, y - DOT_RADIUS, dotSize, dotSize);
    }
  }
}

/** Clear the entire canvas (screen space). */
export function clear() {
  resetTransform(ctx);
  ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
}

// ---- Internal helpers ----

function resizeToContainer() {
  if (!canvasEl) return;
  const parent = canvasEl.parentElement;
  if (!parent) return;
  canvasEl.width = parent.clientWidth;
  canvasEl.height = parent.clientHeight;
}

function handleResize() {
  resizeToContainer();
  EventBus.emit('viewportChanged', getViewport());
}
