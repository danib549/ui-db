/**
 * builder-connections.js — Pure canvas drawing helpers for FK connection lines.
 * Stateless functions used by builder-map.js. No DOM, no state imports.
 */

import { MAP_LINE } from './builder-constants.js';

/** Choose which sides to connect from based on box positions. */
export function chooseSides(srcBox, tgtBox) {
  const srcCx = srcBox.x + srcBox.width / 2;
  const tgtCx = tgtBox.x + tgtBox.width / 2;
  if (srcCx <= tgtCx) {
    return { srcSide: 'right', tgtSide: 'left' };
  }
  return { srcSide: 'left', tgtSide: 'right' };
}

/** Calculate anchor point on a box edge at a given y-offset from box top. */
export function calculateAnchor(box, side, yOffset) {
  const x = side === 'left' ? box.x : box.x + box.width;
  const y = box.y + yOffset;
  return { x, y, side };
}

/** Draw a cubic bezier connection between two anchor points. */
export function drawBezierConnection(ctx, src, tgt, color, lineWidth) {
  const offset = MAP_LINE.controlPointOffset;
  const dirSrc = src.side === 'right' ? 1 : -1;
  const dirTgt = tgt.side === 'right' ? 1 : -1;

  ctx.beginPath();
  ctx.moveTo(src.x, src.y);
  ctx.bezierCurveTo(
    src.x + offset * dirSrc, src.y,
    tgt.x + offset * dirTgt, tgt.y,
    tgt.x, tgt.y
  );
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth || MAP_LINE.strokeWidth;
  ctx.stroke();
}

/** Draw a self-referencing loop on the right side of a box. */
export function drawSelfRefConnection(ctx, box, srcY, tgtY, color, lineWidth) {
  const x = box.x + box.width;
  const loopX = x + MAP_LINE.selfRefLoopOffset;

  ctx.beginPath();
  ctx.moveTo(x, srcY);
  ctx.bezierCurveTo(loopX, srcY, loopX, tgtY, x, tgtY);
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth || MAP_LINE.strokeWidth;
  ctx.stroke();

  return {
    srcAnchor: { x, y: srcY, side: 'right' },
    tgtAnchor: { x, y: tgtY, side: 'right' },
  };
}

/** Draw a "one" tick mark at an anchor point. */
export function drawTick(ctx, anchor, color) {
  const tick = MAP_LINE.tickLength;
  const offset = anchor.side === 'left' ? -6 : 6;
  const x = anchor.x + offset;

  ctx.beginPath();
  ctx.moveTo(x, anchor.y - tick / 2);
  ctx.lineTo(x, anchor.y + tick / 2);
  ctx.strokeStyle = color;
  ctx.lineWidth = MAP_LINE.strokeWidth;
  ctx.lineCap = 'round';
  ctx.stroke();
}

/** Draw a "many" crow's foot at an anchor point. */
export function drawCrowFoot(ctx, anchor, color) {
  const spread = MAP_LINE.crowFootSpread;
  const dir = anchor.side === 'left' ? -1 : 1;
  const baseX = anchor.x + 6 * dir;

  ctx.beginPath();
  ctx.moveTo(anchor.x, anchor.y);
  ctx.lineTo(baseX, anchor.y - spread);
  ctx.moveTo(anchor.x, anchor.y);
  ctx.lineTo(baseX, anchor.y + spread);
  ctx.strokeStyle = color;
  ctx.lineWidth = MAP_LINE.strokeWidth;
  ctx.lineCap = 'round';
  ctx.stroke();
}
