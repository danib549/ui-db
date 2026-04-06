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
export function drawBlock(ctx, entity, pos, isHovered, isSelected, collapsed) {
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
  drawHeader(ctx, entity, x, y, width, r, colors);

  // Fields (only if not collapsed)
  if (!collapsed && entity.fields) {
    drawFields(ctx, entity.fields, x, y, width, colors, catColors);
  }
}

function drawHeader(ctx, entity, x, y, width, r, colors) {
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
  ctx.fillText(label, x + 10, y + hh / 2);

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

  // Packed badge (structs only)
  if (entity.packed && !entity.isFunction) {
    drawPackedBadge(ctx, x + width - 10, y + 4, colors);
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
