/**
 * cstruct-upload.js — Handles file upload (drag-and-drop + file/folder picker)
 * for .c/.h files. Supports dropping entire project folders — recursively
 * finds all C/H files automatically. Sends to /api/cstruct/upload.
 */

import { EventBus } from '../events.js';
import { loadParseResult, setTargetArch } from './cstruct-state.js';

const C_EXTENSIONS = new Set(['.c', '.h', '.cpp', '.hpp', '.cc', '.hh', '.cxx', '.hxx']);

let dropZone = null;
let fileInput = null;
let folderInput = null;
let lastFileMap = null;  // {filename: File} — kept for re-parse on arch change

export function initUpload() {
  dropZone = document.getElementById('upload-zone');
  fileInput = document.getElementById('file-input');
  folderInput = document.getElementById('folder-input');

  if (!dropZone) return;

  // Prevent browser default file-open on drag anywhere on the page
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', (e) => e.preventDefault());

  // Click zones
  const browseFiles = document.getElementById('browse-files');
  const browseFolder = document.getElementById('browse-folder');
  if (browseFiles && fileInput) {
    browseFiles.addEventListener('click', (e) => {
      e.stopPropagation();
      fileInput.click();
    });
  }
  if (browseFolder && folderInput) {
    browseFolder.addEventListener('click', (e) => {
      e.stopPropagation();
      folderInput.click();
    });
  }

  // File input change
  if (fileInput) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length > 0) {
        handleFileList(fileInput.files);
      }
    });
  }

  // Folder input change
  if (folderInput) {
    folderInput.addEventListener('change', () => {
      if (folderInput.files.length > 0) {
        handleFileList(folderInput.files);
      }
    });
  }

  // Drag and drop on the upload zone
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.add('upload-zone--active');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('upload-zone--active');
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove('upload-zone--active');
    handleDrop(e.dataTransfer);
  });

  // Also allow drop on the canvas area
  const canvasContainer = document.getElementById('canvas-container');
  if (canvasContainer) {
    canvasContainer.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.stopPropagation();
      canvasContainer.classList.add('canvas--dragover');
    });
    canvasContainer.addEventListener('dragleave', () => {
      canvasContainer.classList.remove('canvas--dragover');
    });
    canvasContainer.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      canvasContainer.classList.remove('canvas--dragover');
      handleDrop(e.dataTransfer);
    });
  }

  // Re-parse on architecture change
  EventBus.on('cstructArchChanged', ({ arch }) => {
    setTargetArch(arch);
    if (lastFileMap) {
      uploadFileMap(lastFileMap);
    }
  });
}

// ---- Drop handling ----

async function handleDrop(dataTransfer) {
  const items = dataTransfer.items;
  if (!items || items.length === 0) {
    // Fallback: no items API, use files directly
    handleFileList(dataTransfer.files);
    return;
  }

  // Check if any dropped item is a directory
  const entries = [];
  for (let i = 0; i < items.length; i++) {
    const entry = items[i].webkitGetAsEntry?.() || items[i].getAsEntry?.();
    if (entry) {
      entries.push(entry);
    }
  }

  if (entries.length === 0) {
    handleFileList(dataTransfer.files);
    return;
  }

  // Walk all entries (files and directories) recursively
  setUploadStatus('scanning');
  const fileMap = {};
  await Promise.all(entries.map(entry => walkEntry(entry, '', fileMap)));

  const count = Object.keys(fileMap).length;
  if (count === 0) {
    setUploadStatus('error', 'No .c or .h files found in the dropped items');
    return;
  }

  setUploadStatus('parsing', `Found ${count} C/H file${count !== 1 ? 's' : ''}, parsing...`);
  await uploadFileMap(fileMap);
}

/** Recursively walk a FileSystemEntry, collecting C/H files into fileMap. */
function walkEntry(entry, pathPrefix, fileMap) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      if (isCFile(entry.name)) {
        entry.file((file) => {
          const relativePath = pathPrefix ? `${pathPrefix}/${entry.name}` : entry.name;
          fileMap[relativePath] = file;
          resolve();
        }, () => resolve());
      } else {
        resolve();
      }
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      readAllEntries(reader, (entries) => {
        const newPrefix = pathPrefix ? `${pathPrefix}/${entry.name}` : entry.name;
        Promise.all(entries.map(e => walkEntry(e, newPrefix, fileMap))).then(resolve);
      });
    } else {
      resolve();
    }
  });
}

/** Read all entries from a directory reader (handles batched reads). */
function readAllEntries(reader, callback) {
  const all = [];
  const readBatch = () => {
    reader.readEntries((entries) => {
      if (entries.length === 0) {
        callback(all);
      } else {
        all.push(...entries);
        readBatch(); // readEntries returns results in batches
      }
    }, () => callback(all));
  };
  readBatch();
}

/** Handle a plain FileList (from file input or non-directory drop). */
function handleFileList(files) {
  const fileMap = {};
  for (const file of files) {
    const path = file.webkitRelativePath || file.name;
    if (isCFile(file.name)) {
      fileMap[path] = file;
    }
  }

  const count = Object.keys(fileMap).length;
  if (count === 0) {
    setUploadStatus('error', 'No .c or .h files found');
    return;
  }

  uploadFileMap(fileMap);
}

function isCFile(name) {
  const dot = name.lastIndexOf('.');
  if (dot < 0) return false;
  return C_EXTENSIONS.has(name.slice(dot).toLowerCase());
}

// ---- Upload ----

async function uploadFileMap(fileMap) {
  lastFileMap = fileMap;

  const archSelect = document.getElementById('arch-select');
  const target = archSelect ? archSelect.value : 'arm';

  const formData = new FormData();
  for (const [path, file] of Object.entries(fileMap)) {
    formData.append('files[]', file, path);
  }
  formData.append('target', target);

  const fileCount = Object.keys(fileMap).length;
  setUploadStatus('parsing', `Parsing ${fileCount} file${fileCount !== 1 ? 's' : ''}...`);

  try {
    const resp = await fetch('/api/cstruct/upload', {
      method: 'POST',
      body: formData,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: 'Upload failed' }));
      setUploadStatus('error', err.error || 'Upload failed');
      return;
    }

    const result = await resp.json();
    loadParseResult(result);

    const structCount = (result.structs?.length || 0) + (result.unions?.length || 0);
    const enumCount = result.enums?.length || 0;
    const paths = Object.keys(fileMap);
    const summary = fileCount <= 3
      ? paths.join(', ')
      : `${fileCount} files from ${getCommonPrefix(paths)}`;
    const funcCount = result.functions?.length || 0;
    const types = [
      structCount ? `${structCount} struct${structCount !== 1 ? 's' : ''}` : '',
      enumCount ? `${enumCount} enum${enumCount !== 1 ? 's' : ''}` : '',
      funcCount ? `${funcCount} function${funcCount !== 1 ? 's' : ''}` : '',
    ].filter(Boolean).join(', ');

    setUploadStatus('success', `${summary} \u2014 ${types || 'no types found'}`);
  } catch (err) {
    setUploadStatus('error', `Network error: ${err.message}`);
  }
}

/** Extract the common directory prefix from a list of paths. */
function getCommonPrefix(paths) {
  if (paths.length === 0) return '';
  if (paths.length === 1) return paths[0];
  const parts = paths[0].split('/');
  let common = [];
  for (let i = 0; i < parts.length - 1; i++) {
    if (paths.every(p => p.split('/')[i] === parts[i])) {
      common.push(parts[i]);
    } else {
      break;
    }
  }
  return common.length > 0 ? common.join('/') + '/' : '';
}

// ---- Status UI ----

function setUploadStatus(status, message) {
  const statusEl = document.getElementById('upload-status');
  const statusText = document.getElementById('upload-status-text');
  if (!statusEl || !statusText) return;

  statusEl.className = 'upload-status';
  statusEl.hidden = false;

  if (status === 'scanning') {
    statusEl.classList.add('upload-status--parsing');
    statusText.textContent = 'Scanning folder for C/H files...';
  } else if (status === 'parsing') {
    statusEl.classList.add('upload-status--parsing');
    statusText.textContent = message || 'Parsing...';
  } else if (status === 'success') {
    statusEl.classList.add('upload-status--success');
    statusText.textContent = message;
  } else if (status === 'error') {
    statusEl.classList.add('upload-status--error');
    statusText.textContent = message;
  }
}
