/**
 * cstruct-constants.js — Colors, dimensions, and type category definitions
 * for the C struct visualizer canvas.
 */

// ---- Block dimensions ----
export const BLOCK = {
  minWidth: 340,
  headerHeight: 36,
  fieldRowHeight: 24,
  padding: 8,
  cornerRadius: 6,
  gapX: 100,
  gapY: 60,
  badgeSize: 8,
  badgeMarginLeft: 10,
  nameColX: 28,
  typeColX: 150,
  offsetColX: 260,
  sizeColX: 310,
};

// ---- Field category colors (light mode) ----
export const CATEGORY_COLORS = {
  integer:  '#22C55E',
  float:    '#F97316',
  pointer:  '#A78BFA',
  array:    '#14B8A6',
  struct:   '#3B82F6',
  bitfield: '#EAB308',
  padding:  '#9CA3AF',
  enum:     '#EC4899',
};

// ---- Field category colors (dark mode) ----
export const CATEGORY_COLORS_DARK = {
  integer:  '#4ADE80',
  float:    '#FB923C',
  pointer:  '#C4B5FD',
  array:    '#2DD4BF',
  struct:   '#60A5FA',
  bitfield: '#FACC15',
  padding:  '#6B7280',
  enum:     '#F472B6',
};

// ---- Canvas colors (light mode) ----
export const CANVAS_COLORS = {
  bg: '#F9FAFB',
  dot: '#E5E7EB',
  boxBg: '#FFFFFF',
  boxBorder: '#D1D5DB',
  boxBorderHover: '#3B82F6',
  boxBorderSelected: '#2563EB',
  headerBg: '#F3F4F6',
  headerText: '#111827',
  headerMeta: '#6B7280',
  fieldText: '#374151',
  fieldTextSecondary: '#6B7280',
  paddingBg: 'rgba(156, 163, 175, 0.08)',
  paddingStripe: 'rgba(156, 163, 175, 0.15)',
  shadow: 'rgba(0,0,0,0.08)',
  shadowHover: 'rgba(59,130,246,0.2)',
  connectionLine: '#3B82F6',
  connectionLineDim: 'rgba(59,130,246,0.3)',
  unionHeader: '#7C3AED',
  unionHeaderText: '#FFFFFF',
  packedBadgeBg: '#FEF3C7',
  packedBadgeText: '#92400E',
};

// ---- Canvas colors (dark mode) ----
export const CANVAS_COLORS_DARK = {
  bg: '#1a1b23',
  dot: '#2d2e3a',
  boxBg: '#1F2028',
  boxBorder: '#374151',
  boxBorderHover: '#60A5FA',
  boxBorderSelected: '#93C5FD',
  headerBg: '#252630',
  headerText: '#E5E7EB',
  headerMeta: '#9CA3AF',
  fieldText: '#D1D5DB',
  fieldTextSecondary: '#9CA3AF',
  paddingBg: 'rgba(107, 114, 128, 0.1)',
  paddingStripe: 'rgba(107, 114, 128, 0.2)',
  shadow: 'rgba(0,0,0,0.3)',
  shadowHover: 'rgba(96,165,250,0.3)',
  connectionLine: '#60A5FA',
  connectionLineDim: 'rgba(96,165,250,0.3)',
  unionHeader: '#8B5CF6',
  unionHeaderText: '#F5F3FF',
  packedBadgeBg: '#422006',
  packedBadgeText: '#FDE68A',
};

// ---- Connection line constants ----
export const LINE = {
  strokeWidth: 1.5,
  strokeWidthHover: 2.5,
  controlPointOffset: 80,
  arrowSize: 6,
};

// ---- Badge shapes per category ----
export const BADGE_SHAPES = {
  integer:  'circle',
  float:    'circle',
  pointer:  'circle',
  array:    'circle',
  struct:   'square',
  bitfield: 'diamond',
  padding:  'stripe',
  enum:     'circle',
};
