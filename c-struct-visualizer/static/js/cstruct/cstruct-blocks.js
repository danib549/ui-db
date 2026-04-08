/**
 * cstruct-blocks.js — Renders struct and union blocks on the canvas.
 * Stateless drawing functions called by cstruct-app.js render pipeline.
 */

import {
  BLOCK, CATEGORY_COLORS, CATEGORY_COLORS_DARK,
  CANVAS_COLORS, CANVAS_COLORS_DARK, BADGE_SHAPES,
} from './cstruct-constants.js';

function getColors() {
  return document.body.classList.contains('dark') ? CANVAS_COLORS_DARK : CANVAS_COLORS;
}

function getCategoryColors() {
  return document.body.classList.contains('dark') ? CATEGORY_COLORS_DARK : CATEGORY_COLORS;
}

/** Calculate block height based on fields (or collapsed state). */
export function calculateBlockHeight(entity, collapsed) {
  if (collapsed) {
    return BLOCK.headerHeight;
  }
  const fieldCount = entity.fields ? entity.fields.length : 0;
  return BLOCK.headerHeight + fieldCount * BLOCK.fieldRowHeight + BLOCK.padding;
}

/** Draw a struct or union block at the given position. */
export function drawBlock(ctx, entity, pos, isHovered, isSelected, collapsed, refStats) {
  const colors = getColors();
  const catColors = getCategoryColors();
  const { x, y, width } = pos;
  const height = calculateBlockHeight(entity, collapsed);
  const r = BLOCK.cornerRadius;

  // Shadow
  ctx.save();
  ctx.shadowColor = isHovered || isSelected ? colors.shadowHover : colors.shadow;
  ctx.shadowBlur = isHovered || isSelected ? 10 : 4;
  ctx.shadowOffsetY = 2;
  roundRect(ctx, x, y, width, height, r);
  ctx.fillStyle = colors.boxBg;
  ctx.fill();
  ctx.restore();

  // Border
  roundRect(ctx, x, y, width, height, r);
  ctx.strokeStyle = isSelected ? colors.boxBorderSelected
    : isHovered ? colors.boxBorderHover : colors.boxBorder;
  ctx.lineWidth = isSelected ? 2 : isHovered ? 1.5 : 1;
  ctx.stroke();

  // Header background
  drawHeader(ctx, entity, x, y, width, r, colors, collapsed, refStats);

  // Fields (only if not collapsed)
  if (!collapsed && entity.fields) {
    drawFields(ctx, entity.fields, x, y, width, colors, catColors);
  }
}

function drawHeader(ctx, entity, x, y, width, r, colors, collapsed, refStats) {
  const hh = BLOCK.headerHeight;

  // Header fill
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.arcTo(x + width, y, x + width, y + r, r);
  ctx.lineTo(x + width, y + hh);
  ctx.lineTo(x, y + hh);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();

  if (entity.isFunction) {
    ctx.fillStyle = colors.functionHeader;
  } else if (entity.isUnion) {
    ctx.fillStyle = colors.unionHeader;
  } else {
    ctx.fillStyle = colors.headerBg;
  }
  ctx.fill();
  ctx.restore();

  // Header divider
  ctx.beginPath();
  ctx.moveTo(x, y + hh);
  ctx.lineTo(x + width, y + hh);
  ctx.strokeStyle = colors.boxBorder;
  ctx.lineWidth = 1;
  ctx.stroke();

  // Entity name
  const textColor = entity.isFunction ? colors.functionHeaderText
    : entity.isUnion ? colors.unionHeaderText : colors.headerText;
  ctx.fillStyle = textColor;
  ctx.font = 'bold 12px system-ui, sans-serif';
  ctx.textBaseline = 'middle';

  let label = entity.displayName || entity.name;
  if (label.startsWith('__anon_') || label === '(anonymous)') {
    label = '(anonymous)';
    ctx.font = 'italic bold 12px system-ui, sans-serif';
  }
  if (entity.isFunction) {
    label += '()';
  }
  const maxNameWidth = width * 0.45;
  label = truncateText(ctx, label, maxNameWidth);
  ctx.fillText(label, x + 24, y + hh / 2);

  // Reference stat badges (inline after name)
  if (refStats) {
    const nameW = ctx.measureText(label).width;
    drawRefStatsBadges(ctx, x + 24 + nameW + 6, y + hh / 2, refStats, textColor, colors);
  }

  // Meta info
  ctx.font = '10px system-ui, sans-serif';
  ctx.fillStyle = entity.isFunction ? colors.functionHeaderText
    : entity.isUnion ? colors.unionHeaderText : colors.headerMeta;
  ctx.textAlign = 'right';

  if (entity.isFunction) {
    const retStr = entity.returnType || 'void';
    const paramCount = entity.params ? entity.params.length : 0;
    const parts = [`\u2192 ${retStr}`, `${paramCount}p`];
    ctx.fillText(parts.join('  '), x + width - 10, y + hh / 2);
  } else {
    const sizeStr = entity.totalSize >= 0 ? `${entity.totalSize}B` : '?B';
    const alignStr = entity.alignment > 0 ? `${entity.alignment}-al` : '';
    const typeLabel = entity.isUnion ? 'union' : '';
    const parts = [typeLabel, sizeStr, alignStr].filter(Boolean);
    ctx.fillText(parts.join('  '), x + width - 10, y + hh / 2);
  }
  ctx.textAlign = 'start';

  // Collapse triangle
  drawCollapseButton(ctx, x + 8, y + hh / 2, collapsed, textColor);

  // Packed badge (structs only)
  if (entity.packed && !entity.isFunction) {
    drawPackedBadge(ctx, x + width - 10, y + 4, colors);
  }

}

function drawSmallBadge(ctx, leftX, centerY, text, fillColor, textColor) {
  ctx.font = 'bold 8px system-ui, sans-serif';
  const tw = ctx.measureText(text).width;
  const px = 4;
  const bw = tw + px * 2;
  const bh = 13;
  const br = 3;
  const by = centerY - bh / 2;

  ctx.globalAlpha = 0.18;
  ctx.fillStyle = fillColor;
  roundRect(ctx, leftX, by, bw, bh, br);
  ctx.fill();
  ctx.globalAlpha = 1.0;

  ctx.fillStyle = textColor;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, leftX + bw / 2, centerY);
  ctx.textAlign = 'start';
  return bw;
}

function drawRefStatsBadges(ctx, startX, centerY, stats, textColor, colors) {
  let curX = startX;
  const gap = 3;

  if (stats.calledBy > 0) {
    const w = drawSmallBadge(ctx, curX, centerY, `\u2190${stats.calledBy}`, colors.connectionCall || textColor, textColor);
    curX += w + gap;
  }
  if (stats.calls > 0) {
    const w = drawSmallBadge(ctx, curX, centerY, `\u2192${stats.calls}`, colors.connectionReturn || textColor, textColor);
    curX += w + gap;
  }
  if (stats.calledBy > 0 && (stats.byFunc > 0 || stats.byStruct > 0)) {
    const parts = [];
    if (stats.byFunc > 0) parts.push(`f:${stats.byFunc}`);
    if (stats.byStruct > 0) parts.push(`s:${stats.byStruct}`);
    drawSmallBadge(ctx, curX, centerY, parts.join(' '), colors.connectionUses || textColor, textColor);
  }
}

function drawPackedBadge(ctx, rightX, topY, colors) {
  ctx.font = 'bold 8px system-ui, sans-serif';
  const text = 'PACKED';
  const tw = ctx.measureText(text).width;
  const px = 4;
  const bw = tw + px * 2;
  const bh = 14;
  const bx = rightX - bw;

  ctx.fillStyle = colors.packedBadgeBg;
  roundRect(ctx, bx, topY, bw, bh, 3);
  ctx.fill();

  ctx.fillStyle = colors.packedBadgeText;
  ctx.textBaseline = 'middle';
  ctx.fillText(text, bx + px, topY + bh / 2);
}

function drawFields(ctx, fields, blockX, blockY, blockWidth, colors, catColors) {
  const startY = blockY + BLOCK.headerHeight;

  for (let i = 0; i < fields.length; i++) {
    const field = fields[i];
    const fy = startY + i * BLOCK.fieldRowHeight;
    const rowH = BLOCK.fieldRowHeight;

    // Padding row background
    if (field.category === 'padding') {
      drawPaddingBackground(ctx, blockX, fy, blockWidth, rowH, colors);
    }

    // Category badge
    const badgeColor = catColors[field.category] || catColors.integer;
    const badgeShape = BADGE_SHAPES[field.category] || 'circle';
    drawBadge(ctx, blockX + BLOCK.badgeMarginLeft, fy + rowH / 2, BLOCK.badgeSize, badgeColor, badgeShape);

    // Field name
    ctx.font = field.category === 'padding'
      ? 'italic 11px system-ui, sans-serif'
      : '11px system-ui, sans-serif';
    ctx.fillStyle = field.category === 'padding' ? colors.fieldTextSecondary : colors.fieldText;
    ctx.textBaseline = 'middle';

    let nameLabel = field.name;
    if (field.bitSize) {
      nameLabel += `:${field.bitSize}`;
    }
    ctx.fillText(truncateText(ctx, nameLabel, BLOCK.typeColX - BLOCK.nameColX - 8),
      blockX + BLOCK.nameColX, fy + rowH / 2);

    // Type
    ctx.font = '11px monospace';
    ctx.fillStyle = colors.fieldTextSecondary;
    ctx.fillText(truncateText(ctx, field.type, BLOCK.offsetColX - BLOCK.typeColX - 8),
      blockX + BLOCK.typeColX, fy + rowH / 2);

    // Offset
    ctx.font = '10px monospace';
    const offsetStr = field.offset !== undefined ? `+${field.offset}` : '';
    ctx.fillText(offsetStr, blockX + BLOCK.offsetColX, fy + rowH / 2);

    // Size
    const sizeStr = field.bitSize
      ? `${field.bitSize}b`
      : field.size > 0 ? `${field.size}B` : '';
    ctx.textAlign = 'right';
    ctx.fillText(sizeStr, blockX + blockWidth - 10, fy + rowH / 2);
    ctx.textAlign = 'start';
  }
}

function drawPaddingBackground(ctx, x, y, w, h, colors) {
  // Subtle striped background for padding rows
  ctx.fillStyle = colors.paddingBg;
  ctx.fillRect(x + 1, y, w - 2, h);

  // Diagonal stripes
  ctx.save();
  ctx.beginPath();
  ctx.rect(x + 1, y, w - 2, h);
  ctx.clip();
  ctx.strokeStyle = colors.paddingStripe;
  ctx.lineWidth = 1;
  const step = 6;
  for (let sx = x - h; sx < x + w; sx += step) {
    ctx.beginPath();
    ctx.moveTo(sx, y + h);
    ctx.lineTo(sx + h, y);
    ctx.stroke();
  }
  ctx.restore();
}

function drawBadge(ctx, cx, cy, size, color, shape) {
  const half = size / 2;
  ctx.fillStyle = color;

  if (shape === 'circle') {
    ctx.beginPath();
    ctx.arc(cx, cy, half, 0, Math.PI * 2);
    ctx.fill();
  } else if (shape === 'square') {
    ctx.fillRect(cx - half, cy - half, size, size);
  } else if (shape === 'diamond') {
    ctx.beginPath();
    ctx.moveTo(cx, cy - half);
    ctx.lineTo(cx + half, cy);
    ctx.lineTo(cx, cy + half);
    ctx.lineTo(cx - half, cy);
    ctx.closePath();
    ctx.fill();
  } else if (shape === 'stripe') {
    ctx.fillRect(cx - half, cy - 1.5, size, 3);
  } else if (shape === 'triangle') {
    ctx.beginPath();
    ctx.moveTo(cx - half, cy - half);
    ctx.lineTo(cx + half, cy);
    ctx.lineTo(cx - half, cy + half);
    ctx.closePath();
    ctx.fill();
  }
}

function truncateText(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(t + '\u2026').width > maxWidth) {
    t = t.slice(0, -1);
  }
  return t + '\u2026';
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

function drawCollapseButton(ctx, cx, cy, collapsed, color) {
  const size = 5;
  ctx.save();
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.7;
  ctx.beginPath();
  if (collapsed) {
    // Right-pointing triangle
    ctx.moveTo(cx - 2, cy - size);
    ctx.lineTo(cx + size, cy);
    ctx.lineTo(cx - 2, cy + size);
  } else {
    // Down-pointing triangle
    ctx.moveTo(cx - size, cy - 2);
    ctx.lineTo(cx + size, cy - 2);
    ctx.lineTo(cx, cy + size);
  }
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

/** Draw a file container box (for by-file layout). */
export function drawFileContainer(ctx, filename, x, y, width, height) {
  const colors = getColors();
  const r = 8;
  const titleH = 28;

  // Container background
  ctx.save();
  ctx.globalAlpha = 0.35;
  ctx.fillStyle = colors.fileContainerBg || (document.body.classList.contains('dark') ? '#1e1f2b' : '#f1f5f9');
  roundRect(ctx, x, y, width, height, r);
  ctx.fill();
  ctx.restore();

  // Dashed border
  ctx.save();
  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = colors.fileContainerBorder || (document.body.classList.contains('dark') ? '#374151' : '#cbd5e1');
  ctx.lineWidth = 1.5;
  roundRect(ctx, x, y, width, height, r);
  ctx.stroke();
  ctx.restore();

  // Title bar
  ctx.fillStyle = colors.fileContainerTitle || (document.body.classList.contains('dark') ? '#9CA3AF' : '#64748b');
  ctx.font = 'bold 11px system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.fillText(filename, x + 12, y + titleH / 2);
}

/** Hit-test: check if canvas coordinates are within the collapse button zone. */
export function hitTestCollapseButton(pos, cx, cy) {
  const hh = BLOCK.headerHeight;
  return cx >= pos.x && cx <= pos.x + 20 && cy >= pos.y && cy <= pos.y + hh;
}

/** Hit-test: return field index at canvas coordinates within a block, or -1. */
export function hitTestField(entity, pos, cx, cy, collapsed) {
  if (collapsed) return -1;
  const startY = pos.y + BLOCK.headerHeight;
  if (cy < startY) return -1;
  const idx = Math.floor((cy - startY) / BLOCK.fieldRowHeight);
  if (idx >= 0 && idx < (entity.fields ? entity.fields.length : 0)) {
    return idx;
  }
  return -1;
}

/** Hit-test: return tooltip string if mouse is over a ref-stats badge, or null. */
export function hitTestBadge(ctx, entity, pos, refStats, cx, cy) {
  if (!refStats) return null;
  const hh = BLOCK.headerHeight;
  const centerY = pos.y + hh / 2;
  const bh = 13;
  if (cy < centerY - bh / 2 || cy > centerY + bh / 2) return null;

  // Recompute label to find badge start X
  ctx.font = 'bold 12px system-ui, sans-serif';
  let label = entity.displayName || entity.name;
  if (label.startsWith('__anon_') || label === '(anonymous)') label = '(anonymous)';
  if (entity.isFunction) label += '()';
  label = truncateText(ctx, label, pos.width * 0.45);
  const nameW = ctx.measureText(label).width;
  let curX = pos.x + 24 + nameW + 6;
  const gap = 3;
  const px = 4;

  ctx.font = 'bold 8px system-ui, sans-serif';

  // Badge 1: calledBy
  if (refStats.calledBy > 0) {
    const tw = ctx.measureText(`\u2190${refStats.calledBy}`).width;
    const bw = tw + px * 2;
    if (cx >= curX && cx <= curX + bw) return `Referenced by ${refStats.calledBy} other entities`;
    curX += bw + gap;
  }
  // Badge 2: calls
  if (refStats.calls > 0) {
    const tw = ctx.measureText(`\u2192${refStats.calls}`).width;
    const bw = tw + px * 2;
    if (cx >= curX && cx <= curX + bw) return `Calls/references ${refStats.calls} other entities`;
    curX += bw + gap;
  }
  // Badge 3: byFunc/byStruct breakdown
  if (refStats.calledBy > 0 && (refStats.byFunc > 0 || refStats.byStruct > 0)) {
    const parts = [];
    if (refStats.byFunc > 0) parts.push(`f:${refStats.byFunc}`);
    if (refStats.byStruct > 0) parts.push(`s:${refStats.byStruct}`);
    const tw = ctx.measureText(parts.join(' ')).width;
    const bw = tw + px * 2;
    if (cx >= curX && cx <= curX + bw) {
      const tips = [];
      if (refStats.byFunc > 0) tips.push(`${refStats.byFunc} from functions`);
      if (refStats.byStruct > 0) tips.push(`${refStats.byStruct} from structs/unions`);
      return `Referenced by: ${tips.join(', ')}`;
    }
  }
  return null;
}
