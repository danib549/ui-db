/**
 * csv-import.js — CSV file upload and drag-and-drop handling.
 * Sends files to backend, processes response, adds tables to state.
 */

import { EventBus } from './events.js';
import * as State from './state.js';
import { calculateBlockWidth } from './blocks.js';
import { HEADER_HEIGHT, ROW_HEIGHT, GRID_GAP, GRID_COL_WIDTH, GRID_ROW_HEIGHT, GRID_COLUMNS } from './constants.js';

const GRID_START_X = 40;
const GRID_START_Y = 40;

/** Wire file input and drag-and-drop events. */
export function initUpload() {
  wireFileInput();
  wireDragAndDrop();
}

/** Send files to backend, process response, add tables to state. */
export async function uploadCSVFiles(files) {
  const csvFiles = Array.from(files).filter((f) => f.name.endsWith('.csv'));
  if (csvFiles.length === 0) return;

  const formData = new FormData();
  csvFiles.forEach((f) => formData.append('files', f));

  const existingTables = State.getTableNames();
  if (existingTables.length > 0) {
    formData.append('existing_tables', JSON.stringify(existingTables));
  }

  const response = await fetch('/api/upload-csv', { method: 'POST', body: formData });
  if (!response.ok) return;

  const data = await response.json();
  processUploadResponse(data);
}

// ---- Internal helpers ----

function processUploadResponse(data) {
  const { tables, relationships } = data;
  if (!tables || tables.length === 0) return;

  const existingPositions = State.getPositions();
  const newPositions = findOpenCanvasSpace(existingPositions, tables);

  tables.forEach((table, i) => {
    const width = calculateBlockWidth(table);
    const height = HEADER_HEIGHT + table.columns.length * ROW_HEIGHT;
    State.addTable(table);
    State.setPosition(table.name, { ...newPositions[i], width, height });
  });

  if (relationships && relationships.length > 0) {
    const connections = transformRelationships(relationships);
    State.setConnections(connections);
  }

  updateSidebarTableList();
}

function transformRelationships(relationships) {
  return relationships.map((rel) => ({
    source: { table: rel.source_table, column: rel.source_column },
    target: { table: rel.target_table, column: rel.target_column },
    type: rel.type || 'one-to-many',
    confidence: rel.confidence || 0,
  }));
}

function findOpenCanvasSpace(existingPositions, tables) {
  const occupied = Object.values(existingPositions);
  const positions = [];
  let col = 0;
  let row = 0;

  for (let i = 0; i < tables.length; i++) {
    let candidate = calcGridPosition(col, row);

    while (overlapsAny(candidate, occupied, positions)) {
      col++;
      if (col >= GRID_COLUMNS) {
        col = 0;
        row++;
      }
      candidate = calcGridPosition(col, row);
    }

    positions.push(candidate);
    col++;
    if (col >= GRID_COLUMNS) {
      col = 0;
      row++;
    }
  }

  return positions;
}

function calcGridPosition(col, row) {
  return {
    x: GRID_START_X + col * (GRID_COL_WIDTH + GRID_GAP),
    y: GRID_START_Y + row * (GRID_ROW_HEIGHT + GRID_GAP),
  };
}

function overlapsAny(candidate, ...positionArrays) {
  for (const arr of positionArrays) {
    for (const pos of arr) {
      if (Math.abs(candidate.x - pos.x) < GRID_COL_WIDTH &&
          Math.abs(candidate.y - pos.y) < GRID_ROW_HEIGHT) {
        return true;
      }
    }
  }
  return false;
}

function wireFileInput() {
  const uploadZone = document.getElementById('upload-zone');
  const fileInput = document.getElementById('file-input');
  if (!uploadZone || !fileInput) return;

  uploadZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      uploadCSVFiles(fileInput.files);
      fileInput.value = '';
    }
  });
}

function wireDragAndDrop() {
  const container = document.getElementById('canvas-container');
  const uploadZone = document.getElementById('upload-zone');

  // Prevent browser default on the entire document so drops work anywhere
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', (e) => e.preventDefault());

  // Canvas container drop zone
  if (container) {
    wireDropZone(container, 'canvas-container--drag-over');
  }

  // Sidebar upload zone also accepts drops
  if (uploadZone) {
    wireDropZone(uploadZone, 'sidebar__upload--active');
  }
}

function wireDropZone(element, activeClass) {
  let dragCounter = 0;

  element.addEventListener('dragenter', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter++;
    element.classList.add(activeClass);
  });

  element.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'copy';
  });

  element.addEventListener('dragleave', (e) => {
    e.stopPropagation();
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      element.classList.remove(activeClass);
    }
  });

  element.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter = 0;
    element.classList.remove(activeClass);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      uploadCSVFiles(files);
    }
  });
}

function updateSidebarTableList() {
  const listEl = document.getElementById('table-list');
  if (!listEl) return;

  const tables = State.getTables();
  listEl.innerHTML = '';

  tables.forEach((table) => {
    const li = document.createElement('li');
    li.className = 'sidebar__table-item';
    li.dataset.tableName = table.name;

    const nameSpan = document.createElement('span');
    nameSpan.className = 'sidebar__table-name';
    nameSpan.textContent = table.name;

    const countSpan = document.createElement('span');
    countSpan.className = 'sidebar__table-count';
    countSpan.textContent = `${table.columns.length} cols`;

    li.appendChild(nameSpan);
    li.appendChild(countSpan);

    li.addEventListener('click', () => {
      EventBus.emit('panToTable', table.name);
    });

    listEl.appendChild(li);
  });
}

// Re-render sidebar when tables change
EventBus.on('tableRemoved', updateSidebarTableList);
