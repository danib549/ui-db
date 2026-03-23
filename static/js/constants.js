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
export const DIMMED_COLOR = '#D1D5DB';

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
