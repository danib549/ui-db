/**
 * cstruct-modal.js — Source file preview modal.
 * Double-click a block to see the C source file with the definition highlighted.
 */

import { getEntity, getFileContent } from './cstruct-state.js';

let modalEl = null;

function ensureModal() {
  if (modalEl) return;

  modalEl = document.createElement('div');
  modalEl.className = 'source-modal';
  modalEl.innerHTML = `
    <div class="source-modal__backdrop"></div>
    <div class="source-modal__dialog">
      <div class="source-modal__header">
        <div class="source-modal__title"></div>
        <button class="source-modal__close" title="Close">&times;</button>
      </div>
      <div class="source-modal__content">
        <pre class="source-modal__code"></pre>
      </div>
    </div>
  `;
  document.body.appendChild(modalEl);

  // Close handlers
  modalEl.querySelector('.source-modal__backdrop').addEventListener('click', closeSourceModal);
  modalEl.querySelector('.source-modal__close').addEventListener('click', closeSourceModal);
  document.addEventListener('keydown', onKeyDown);
}

function onKeyDown(e) {
  if (e.key === 'Escape' && modalEl && modalEl.classList.contains('source-modal--open')) {
    closeSourceModal();
  }
}

export function openSourceModal(entityName) {
  ensureModal();

  const entity = getEntity(entityName);
  if (!entity) {
    console.warn('[source-modal] entity not found:', entityName);
    return;
  }
  if (!entity.sourceFile) {
    console.warn('[source-modal] no sourceFile for:', entityName, entity);
    return;
  }

  const content = getFileContent(entity.sourceFile);
  if (!content) {
    console.warn('[source-modal] no file content for:', entity.sourceFile);
    return;
  }

  console.log('[source-modal]', entityName, 'file:', entity.sourceFile,
    'lines:', entity.sourceLine, '-', entity.sourceEndLine);

  // Set title
  const displayName = entity.displayName || entity.name;
  const titleEl = modalEl.querySelector('.source-modal__title');
  titleEl.textContent = `${entity.sourceFile}`;

  // Render code with line numbers — no highlighting, just show the file
  const lines = content.split('\n');
  const codeEl = modalEl.querySelector('.source-modal__code');

  let html = '';
  for (let i = 0; i < lines.length; i++) {
    const lineNum = i + 1;
    const escapedLine = escapeHtml(lines[i]) || ' ';
    html += `<div class="source-modal__line" data-line="${lineNum}">` +
      `<span class="source-modal__line-num">${lineNum}</span>` +
      `<span class="source-modal__line-text">${escapedLine}</span>` +
      `</div>`;
  }
  codeEl.innerHTML = html;

  // Show modal
  modalEl.classList.add('source-modal--open');

  // Scroll to top
  requestAnimationFrame(() => {
    const contentEl = modalEl.querySelector('.source-modal__content');
    contentEl.scrollTop = 0;
  });
}

export function closeSourceModal() {
  if (modalEl) {
    modalEl.classList.remove('source-modal--open');
  }
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
