/**
 * cstruct-connections.js — Pure stateless drawing helpers for nesting connections.
 * No DOM, no state imports. Used by cstruct-app.js.
 */

import { LINE } from './cstruct-constants.js';

/** Choose which sides to connect from based on box positions. */
export function chooseSides(srcBox, tgtBox) {
  const srcCx = srcBox.x + srcBox.width / 2;
  const tgtCx = tgtBox.x + tgtBox.width / 2;
  return srcCx <= tgtCx
    ? { srcSide: 'right', tgtSide: 'left' }
    : { srcSide: 'left', tgtSide: 'right' };
}

/** Calculate anchor point on a box edge at a given y-offset from box top. */
export function calculateAnchor(box, side, yOffset) {
  const x = side === 'left' ? box.x : box.x + box.width;
  const y = box.y + yOffset;
  return { x, y, side };
}

/** Draw a cubic bezier connection between two anchor points. */
export function drawBezierConnection(ctx, src, tgt, color, lineWidth) {
  const offset = LINE.controlPointOffset;
  const dirSrc = src.side === 'right' ? 1 : -1;
  const dirTgt = tgt.side === 'right' ? 1 : -1;

  ctx.beginPath();
  ctx.moveTo(src.x, src.y);
  ctx.bezierCurveTo(
    src.x + offset * dirSrc, src.y,
    tgt.x + offset * dirTgt, tgt.y,
    tgt.x, tgt.y,
  );
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth || LINE.strokeWidth;
  ctx.stroke();
}

/** Draw a small filled arrow at an anchor point. */
export function drawArrow(ctx, anchor, color) {
  const size = LINE.arrowSize;
  const dir = anchor.side === 'left' ? -1 : 1;

  ctx.beginPath();
  ctx.moveTo(anchor.x, anchor.y);
  ctx.lineTo(anchor.x + size * dir, anchor.y - size / 2);
  ctx.lineTo(anchor.x + size * dir, anchor.y + size / 2);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
}
