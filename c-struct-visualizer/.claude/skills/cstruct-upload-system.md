# Skill: File Upload System

## When to Use
Apply this skill when working on the file upload flow: drag-and-drop handling (files and folders), file/folder picker buttons, recursive directory walking, the upload request to the backend, re-parse on architecture change, and upload status feedback UI. All upload code is in `cstruct-upload.js`.

---

## 1. Upload Flow

```
User action (drag, browse files, browse folder)
  ↓
Collect files → filter C/H extensions → build fileMap {path: File}
  ↓
uploadFileMap(fileMap)
  ↓
FormData with files[] + target arch → POST /api/cstruct/upload
  ↓
Response JSON (structs, unions, functions, connections, fileContents, ...)
  → loadParseResult() → triggers search index build + rendering
  ↓
Cache fileMap as lastFileMap (for re-parse on arch change)
```

## 2. Supported File Extensions

```javascript
const C_EXTENSIONS = new Set(['.c', '.h', '.cpp', '.hpp', '.cc', '.hh', '.cxx', '.hxx']);
```

Files not matching these extensions are silently skipped.

## 3. Three Upload Methods

### Drag-and-Drop
Supported on both the upload zone and the canvas container.

```javascript
// Upload zone: #upload-zone
dropZone.addEventListener('drop', (e) => handleDrop(e.dataTransfer));

// Canvas area: #canvas-container
canvasContainer.addEventListener('drop', (e) => handleDrop(e.dataTransfer));
```

Drag styling:
- Upload zone: `upload-zone--active` class during dragover
- Canvas: `canvas--dragover` class during dragover

**Global prevention**: `document.addEventListener('dragover/drop', e.preventDefault())` prevents the browser from opening files.

### File Picker
```html
<input type="file" id="file-input" multiple accept=".c,.h,.cpp,.hpp,.cc,.hh,.cxx,.hxx">
```
Triggered by clicking the "browse files" button. Supports selecting multiple files.

### Folder Picker
```html
<input type="file" id="folder-input" webkitdirectory>
```
Triggered by clicking the "browse folder" button. Opens a native folder picker. Browser provides all files in the selected directory tree.

## 4. Directory Walking

When a folder is dropped (not selected via the folder picker), the WebKit File System API is used for recursive walking:

```javascript
async function handleDrop(dataTransfer) {
  // Try to get FileSystemEntry objects
  const entries = [];
  for (let i = 0; i < items.length; i++) {
    const entry = items[i].webkitGetAsEntry?.() || items[i].getAsEntry?.();
    if (entry) entries.push(entry);
  }
  // Walk all entries recursively
  const fileMap = {};
  await Promise.all(entries.map(entry => walkEntry(entry, '', fileMap)));
}
```

### `walkEntry()` — Recursive Directory Walker
```javascript
function walkEntry(entry, pathPrefix, fileMap) {
  if (entry.isFile) {
    if (isCFile(entry.name)) {
      fileMap[relativePath] = file;  // Store with relative path as key
    }
  } else if (entry.isDirectory) {
    // Read all entries (handles batched reads)
    // Recurse into each child entry
  }
}
```

### Batched Directory Reading
The `DirectoryReader.readEntries()` API returns results in batches. `readAllEntries()` handles this:

```javascript
function readAllEntries(reader, callback) {
  const all = [];
  const readBatch = () => {
    reader.readEntries((entries) => {
      if (entries.length === 0) callback(all);
      else { all.push(...entries); readBatch(); }
    });
  };
  readBatch();
}
```

### Path Preservation
When walking directories, the relative path is preserved: `sensors/data.h`, `main.c`. This is sent as the filename in FormData so the backend can reconstruct the directory structure for `#include` resolution.

## 5. File Map and FormData

The `fileMap` is a `{relativePath: File}` object. It's sent as multipart FormData:

```javascript
async function uploadFileMap(fileMap) {
  lastFileMap = fileMap;  // Cache for re-parse
  const formData = new FormData();
  for (const [path, file] of Object.entries(fileMap)) {
    formData.append('files[]', file, path);  // path as filename
  }
  formData.append('target', archSelect.value);
  const resp = await fetch('/api/cstruct/upload', { method: 'POST', body: formData });
}
```

## 6. Response Handling

The backend response includes `fileContents` (raw source code strings for the source preview modal), attached by `cstruct_routes.py`. The response is passed to `loadParseResult()` which populates all state including `fileContents`.

## 7. Re-Parse on Architecture Change

When the user changes the target architecture selector, the cached file map is re-uploaded:

```javascript
EventBus.on('cstructArchChanged', ({ arch }) => {
  setTargetArch(arch);
  if (lastFileMap) {
    uploadFileMap(lastFileMap);  // Re-parse same files with new arch
  }
});
```

This avoids requiring the user to re-upload files just to see the layout under a different architecture.

## 8. Status Feedback UI

Upload status is shown via `#upload-status` and `#upload-status-text`:

| State | CSS Class | Message |
|-------|-----------|---------|
| Scanning | `upload-status--parsing` | "Scanning folder for C/H files..." |
| Parsing | `upload-status--parsing` | "Parsing 5 files..." |
| Success | `upload-status--success` | "main.c, types.h — 3 structs, 1 enum" |
| Error | `upload-status--error` | "No .c or .h files found" or "Network error: ..." |

### Success Message Format
```javascript
// Few files: list names directly
"main.c, types.h — 3 structs, 1 enum, 2 functions"

// Many files: show common prefix
"5 files from sensors/ — 8 structs, 2 enums"
```

### Common Prefix Detection
For many-file uploads, extracts the common directory prefix:
```javascript
function getCommonPrefix(paths) {
  // Walk path segments, return longest shared prefix
  // "sensors/data.h", "sensors/config.h" → "sensors/"
}
```

## 9. Error Handling

| Scenario | Handling |
|----------|---------|
| No files dropped | `setUploadStatus('error', 'No .c or .h files found in the dropped items')` |
| No C/H files in selection | `setUploadStatus('error', 'No .c or .h files found')` |
| HTTP error from backend | Parse error JSON if available, show message |
| Network failure | `setUploadStatus('error', 'Network error: ' + err.message)` |

## 10. Anti-Patterns

- **Never read file contents in JS** — send raw File objects via FormData, let the backend read them
- **Never clear lastFileMap on error** — keep it cached so the user can retry or change arch
- **Never block on directory walking** — use async/await with Promise.all for parallel entry walking
- **Never skip the global drag prevention** — without it, the browser opens the dropped file in the current tab
