/**
 * cstruct-upload.js — Handles file upload (drag-and-drop + file picker)
 * for .c/.h files. Sends to /api/cstruct/upload and loads results into state.
 */

import { EventBus } from '../events.js';
import { loadParseResult, setTargetArch } from './cstruct-state.js';

let dropZone = null;
let fileInput = null;
let lastFiles = null;  // Keep for re-parse on arch change

export function initUpload() {
  dropZone = document.getElementById('upload-zone');
  fileInput = document.getElementById('file-input');

  if (!dropZone || !fileInput) return;

  // Prevent browser default file-open on drag anywhere on the page
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', (e) => e.preventDefault());

  // Click to browse
  dropZone.addEventListener('click', () => fileInput.click());

  // File input change
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      uploadFiles(fileInput.files);
    }
  });

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
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      uploadFiles(files);
    }
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
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        uploadFiles(files);
      }
    });
  }

  // Re-parse on architecture change
  EventBus.on('cstructArchChanged', ({ arch }) => {
    setTargetArch(arch);
    if (lastFiles) {
      uploadFiles(lastFiles);
    }
  });
}

async function uploadFiles(files) {
  lastFiles = files;

  const archSelect = document.getElementById('arch-select');
  const target = archSelect ? archSelect.value : 'arm';

  const formData = new FormData();
  for (const file of files) {
    formData.append('files[]', file);
  }
  formData.append('target', target);

  // Update UI
  setUploadStatus('parsing');

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

    const count = (result.structs?.length || 0) + (result.unions?.length || 0);
    const enumCount = result.enums?.length || 0;
    const fileNames = Array.from(files).map(f => f.name).join(', ');
    setUploadStatus('success', `${fileNames} \u2014 ${count} struct${count !== 1 ? 's' : ''}${enumCount ? `, ${enumCount} enum${enumCount !== 1 ? 's' : ''}` : ''}`);
  } catch (err) {
    setUploadStatus('error', `Network error: ${err.message}`);
  }
}

function setUploadStatus(status, message) {
  const statusEl = document.getElementById('upload-status');
  const statusText = document.getElementById('upload-status-text');
  if (!statusEl || !statusText) return;

  statusEl.className = 'upload-status';
  statusEl.hidden = false;

  if (status === 'parsing') {
    statusEl.classList.add('upload-status--parsing');
    statusText.textContent = 'Parsing...';
  } else if (status === 'success') {
    statusEl.classList.add('upload-status--success');
    statusText.textContent = message;
  } else if (status === 'error') {
    statusEl.classList.add('upload-status--error');
    statusText.textContent = message;
  }
}
