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

// ---- Field category colors (light mode — warm tones) ----
export const CATEGORY_COLORS = {
  integer:  '#5C7A3E',
  float:    '#D4782A',
  pointer:  '#9B6B9E',
  array:    '#4A8C7A',
  struct:   '#C4841D',
  bitfield: '#B8962B',
  padding:  '#B8A48C',
  enum:     '#B85470',
  funcptr:  '#7C3AED',
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
  funcptr:  '#A78BFA',
};

// ---- Canvas colors (light mode — Anthropic warm palette) ----
export const CANVAS_COLORS = {
  bg: '#F5F0E8',
  dot: '#DDD4C4',
  boxBg: '#FFFDF8',
  boxBorder: '#D4C4AA',
  boxBorderHover: '#C4841D',
  boxBorderSelected: '#A06B15',
  headerBg: '#F0E8D8',
  headerText: '#2C1E0E',
  headerMeta: '#7A6A54',
  fieldText: '#3E2A14',
  fieldTextSecondary: '#7A6A54',
  paddingBg: 'rgba(180, 160, 130, 0.08)',
  paddingStripe: 'rgba(180, 160, 130, 0.15)',
  shadow: 'rgba(62, 42, 20, 0.08)',
  shadowHover: 'rgba(196, 132, 29, 0.2)',
  connectionLine: '#C4841D',
  connectionLineDim: 'rgba(196, 132, 29, 0.3)',
  unionHeader: '#8B5A2B',
  unionHeaderText: '#FFF8EE',
  packedBadgeBg: '#FEF3C7',
  packedBadgeText: '#92400E',
  functionHeader: '#5C7A3E',
  functionHeaderText: '#F5F8F0',
  connectionParam: '#6A8EC4',
  connectionReturn: '#5C7A3E',
  connectionUses: '#B8A48C',
  connectionCall: '#D4782A',
  connectionGlobal: '#6366F1',
  connectionFuncptr: '#7C3AED',
  connectionIndirectCall: '#9333EA',
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
  functionHeader: '#10B981',
  functionHeaderText: '#ECFDF5',
  connectionParam: '#93C5FD',
  connectionReturn: '#34D399',
  connectionUses: '#6B7280',
  connectionCall: '#FB923C',
  connectionGlobal: '#818CF8',
  connectionFuncptr: '#A78BFA',
  connectionIndirectCall: '#C084FC',
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
  funcptr:  'triangle',
};
