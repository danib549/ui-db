/**
 * constants.js — Shared constants for the DB Diagram Visualizer.
 * Single source of truth for layout dimensions, colors, and theme values.
 */

// ---- Block layout dimensions ----
export const ROW_HEIGHT = 28;
export const HEADER_HEIGHT = 36;
export const BLOCK_MIN_WIDTH = 200;
export const BLOCK_MAX_WIDTH = 360;
export const BLOCK_DEFAULT_WIDTH = 200;
export const BLOCK_DEFAULT_HEIGHT = 200;
export const PADDING_H = 12;
export const CORNER_RADIUS = 8;

// ---- Grid layout defaults ----
export const GRID_COLUMNS = 4;
export const GRID_COL_WIDTH = 320;
export const GRID_ROW_HEIGHT = 400;
export const GRID_GAP = 40;

// ---- Key type colors ----
export const KEY_COLORS = {
  PK: '#F59E0B',
  FK: '#3B82F6',
  UQ: '#8B5CF6',
  IDX: '#14B8A6',
};

// ---- Connection line colors ----
export const CONNECTION_COLORS = {
  'one-to-one':   '#3B82F6',
  'one-to-many':  '#22C55E',
  'many-to-many': '#F97316',
  'self':         '#A78BFA',
};
export let DIMMED_COLOR = '#D1D5DB';

// ---- Block visual colors ----
export const BLOCK_COLORS = {
  background: '#FFFFFF',
  header: '#F9FAFB',
  headerSelected: '#EFF6FF',
  rowHover: '#F3F4F6',
  divider: '#E5E7EB',
  border: '#D1D5DB',
  borderHover: '#3B82F6',
  borderSelected: '#2563EB',
  textPrimary: '#111827',
  textSecondary: '#6B7280',
  columnName: '#374151',
};

// ---- Light / Dark theme palettes for canvas ----

const LIGHT_THEME = {
  KEY_COLORS: { PK: '#F59E0B', FK: '#3B82F6', UQ: '#8B5CF6', IDX: '#14B8A6' },
  CONNECTION_COLORS: { 'one-to-one': '#3B82F6', 'one-to-many': '#22C55E', 'many-to-many': '#F97316', 'self': '#A78BFA' },
  DIMMED_COLOR: '#D1D5DB',
  BLOCK_COLORS: {
    background: '#FFFFFF', header: '#F9FAFB', headerSelected: '#EFF6FF',
    rowHover: '#F3F4F6', divider: '#E5E7EB', border: '#D1D5DB',
    borderHover: '#3B82F6', borderSelected: '#2563EB',
    textPrimary: '#111827', textSecondary: '#6B7280', columnName: '#374151',
  },
  GRID: { bg: '#F9FAFB', dot: '#E5E7EB' },
};

const DARK_THEME = {
  KEY_COLORS: { PK: '#FBBF24', FK: '#60A5FA', UQ: '#A78BFA', IDX: '#2DD4BF' },
  CONNECTION_COLORS: { 'one-to-one': '#60A5FA', 'one-to-many': '#34D399', 'many-to-many': '#FB923C', 'self': '#C4B5FD' },
  DIMMED_COLOR: '#4B5563',
  BLOCK_COLORS: {
    background: '#1F2028', header: '#252630', headerSelected: 'rgba(59,130,246,0.2)',
    rowHover: '#2d2e3a', divider: '#374151', border: '#374151',
    borderHover: '#60A5FA', borderSelected: '#3B82F6',
    textPrimary: '#E5E7EB', textSecondary: '#9CA3AF', columnName: '#D1D5DB',
  },
  GRID: { bg: '#1a1b23', dot: '#2d2e3a' },
};

/** Canvas grid colors (read by canvas.js) */
export const GRID_COLORS = { bg: '#F9FAFB', dot: '#E5E7EB' };

/** Apply a theme palette to the mutable color objects. */
export function applyTheme(isDark) {
  const theme = isDark ? DARK_THEME : LIGHT_THEME;
  Object.assign(KEY_COLORS, theme.KEY_COLORS);
  Object.assign(CONNECTION_COLORS, theme.CONNECTION_COLORS);
  Object.assign(BLOCK_COLORS, theme.BLOCK_COLORS);
  Object.assign(GRID_COLORS, theme.GRID);
  DIMMED_COLOR = theme.DIMMED_COLOR;
}

// ---- Connection drawing constants ----
export const TICK_LENGTH = 8;
export const CIRCLE_RADIUS = 4;
export const CROW_FOOT_SPREAD = 8;
export const CROW_FOOT_LENGTH = 12;
export const LINE_HIT_THRESHOLD = 6;

// ---- Utility: calculate block height ----
export function calculateBlockHeight(table, collapsed) {
  if (collapsed) return HEADER_HEIGHT;
  return HEADER_HEIGHT + table.columns.length * ROW_HEIGHT;
}
