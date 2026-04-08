# Skill: C Parser Engine — libclang AST Parsing

## When to Use
Apply this skill when working on `c_parser.py` — the backend parsing engine. Covers libclang integration, AST walking, struct/union/enum/function extraction, field offset and padding computation, bitfield handling, type categorization, typedef resolution, multi-file include resolution, source file tracking, stdlib tagging, and target architecture configuration.

---

## 1. Parsing Pipeline

```
parse_c_files(file_contents, target)
  ↓
_parse_in_directory(tmpdir, file_contents, triple, target, target_info)
  1. Write files to tmpdir preserving directory structure
  2. Collect include directories (each file's parent dir + all ancestors)
  3. Create __main__.c with #include for all files
  4. Set up libclang args: -target, -std=c11, -I headers, -I dirs
  5. Index.parse() with PARSE_DETAILED_PROCESSING_RECORD
  6. Build path_map: {abs_path → original_upload_filename}
  7. _collect_warnings() — extract diagnostics
  8. _walk_cursor() — recursive AST traversal (passes path_map for source tracking)
  9. Build reverse typedef map for display names
  10. Tag stdlib entities with isStdlib flag
  11. Return JSON result dict
```

### Key Implementation Detail: Temp Directory

libclang needs real files on disk for `#include` resolution between files. The `unsaved_files` API can't handle relative includes between virtual files. So:

1. All uploaded files are written to a temp directory, preserving relative paths
2. A synthetic `__main__.c` is created that `#include`s every uploaded file
3. Every parent directory AND all ancestor directories become `-I` include paths
4. After parsing, the temp directory is cleaned up in a `finally` block

```python
# Example: user uploads "sensors/data.h" and "main.c"
# tmpdir structure:
#   /tmp/cstruct_xxx/sensors/data.h
#   /tmp/cstruct_xxx/main.c
#   /tmp/cstruct_xxx/__main__.c  →  #include "/tmp/.../sensors/data.h"\n#include "/tmp/.../main.c"
```

### Include Directory Ancestry

To handle `#include "router/file.h"` when `router/` is a sibling folder:
```python
parent = os.path.dirname(file_path)
while parent and parent != tmpdir and parent not in include_dirs:
    include_dirs.add(parent)
    parent = os.path.dirname(parent)
```

## 2. AST Walking — `_walk_cursor()`

Recursive traversal of the translation unit's AST. Only processes nodes from user-uploaded files (skips system headers).

| Cursor Kind | Handler | Output |
|-------------|---------|--------|
| `STRUCT_DECL` | `_process_record(is_union=False)` | → structs list |
| `UNION_DECL` | `_process_record(is_union=True)` | → unions list |
| `TYPEDEF_DECL` | `_process_typedef()` | → typedefs dict |
| `ENUM_DECL` | `_process_enum()` | → enums list |
| `FUNCTION_DECL` | `_process_function()` | → functions list + connections |
| Other | Recurse into children | — |

### User File Filtering — `_is_from_user_file()`

Checks `cursor.location.file.name` against the set of uploaded file paths. Uses direct match, normalized match, and basename suffix match to handle path normalization differences across OS.

## 3. Source File Tracking

Every entity (struct, union, enum, function) gets `sourceFile` and `sourceLine` via `_get_source_location()`:

```python
def _get_source_location(cursor, path_map):
    """Map a cursor's file location back to the original upload filename."""
    normalized = os.path.normpath(loc.file.name)
    original_name = path_map.get(normalized)
    # Fallback: basename matching
    return original_name, loc.line
```

The `path_map` is built before AST walking:
```python
path_map = {}
for name in file_contents:
    safe = name.replace("\\", "/")
    abs_path = os.path.normpath(os.path.join(tmpdir, safe))
    path_map[abs_path] = name
```

This enables:
- By-file layout grouping in the frontend
- Source file preview modal (double-click a block)
- File-based filtering in the search toolbar

## 4. Struct/Union Processing — `_process_record()`

### Guards
- `cursor.is_definition()` — skip forward declarations
- `name in seen_names` — skip duplicates

### Anonymous Types
If `cursor.spelling` is empty, auto-generates name: `__anon_struct_1`, `__anon_union_2`, etc.

### Field Extraction — `_extract_field()`

For each `FIELD_DECL` child:

| Property | Source | Notes |
|----------|--------|-------|
| `name` | `cursor.spelling` | Field name |
| `type` | `field_type.spelling` | Type name string |
| `offset` | `cursor.get_field_offsetof() // 8` | Byte offset from struct start |
| `size` | `field_type.get_size()` | Size in bytes |
| `bitOffset` | `cursor.get_field_offsetof()` | Raw bit offset |
| `bitSize` | `cursor.get_bitfield_width()` | Bitfield width (null if not bitfield) |
| `category` | `_categorize_type()` | Visual category for badges |
| `refStruct` | Canonical type check | Name of referenced struct (if any) |

### Padding Calculation

For **structs only** (not unions), padding is inserted between fields where there are gaps:

```python
# Inter-field padding:
if field_start_bit > prev_end_bit:
    pad_bytes = (field_start_bit - prev_end_bit) // 8
    # Insert padding row: {name: "__pad_N", category: "padding", ...}

# Tail padding:
if last_end_byte < total_size:
    # Insert: {name: "(tail padding)", category: "padding", ...}
```

### Packed Detection — `_is_packed()`

Two methods:
1. Direct: `PACKED_ATTR` child node (from `__attribute__((packed))`)
2. Heuristic: alignment == 1 AND at least one field has alignment > 1

### Nested Struct References

When a field's canonical type is `TypeKind.RECORD`, a connection is added:
```python
connections.append({
    "source": parent_name,    # e.g., "my_struct"
    "target": ref_name,       # e.g., "nested_struct"
    "type": "nested",
    "field": field_name,
})
```

Also handles arrays of structs (`TypeKind.CONSTANTARRAY` → check element type).

## 5. Type Categorization — `_categorize_type()`

| Category | TypeKind Match |
|----------|---------------|
| `"bitfield"` | `is_bitfield` flag |
| `"struct"` | `RECORD` |
| `"enum"` | `ENUM` |
| `"pointer"` | `POINTER` |
| `"array"` | `CONSTANTARRAY`, `INCOMPLETEARRAY` |
| `"float"` | `FLOAT`, `DOUBLE`, `LONGDOUBLE` |
| `"integer"` | Everything else (char, short, int, long, bool) |

Uses `get_canonical()` to resolve through typedefs before checking kind.

## 6. Function Extraction — `_process_function()`

### Parameter Processing
For each `PARM_DECL` child:
- Extract type, name, category
- `_resolve_struct_name()` — unwrap all pointer layers, check if base type is `RECORD`
- If param references a struct, add `"param"` connection

### Return Type
- `cursor.result_type` → check for struct reference
- If return type is a struct, add `"return"` connection

### Body Walking — `_collect_body_struct_refs()`
- Recursively walks `COMPOUND_STMT` and all nested scopes
- Finds `VAR_DECL` nodes with struct types
- Adds `"uses"` connections (deduplicated against params and return)

### Definition vs Declaration Priority
- If we already have a declaration and encounter the definition: replace it
- If we already have the definition: skip the declaration
- Old connections from the replaced declaration are cleaned up

## 7. Typedef Resolution

### Forward Map
`_process_typedef()` builds `typedefs[alias] = canonical_name`:
```python
# typedef struct _sensor_data sensor_data_t;
# → typedefs["sensor_data_t"] = "_sensor_data"
```

### Reverse Map (Display Names)
After all types are collected, build reverse mapping for cleaner display:
```python
# Preference order:
# 1. Aliases without leading underscore
# 2. Shorter aliases
# _sensor_data → sensor_data_t (preferred display name)
```

## 8. Stdlib Tagging

Known C standard library names are defined in `STDLIB_NAMES` frozenset. After parsing, entities are tagged:

```python
for entity in structs + unions:
    entity["isStdlib"] = entity["name"] in STDLIB_NAMES
for fn in functions:
    fn["isStdlib"] = fn["name"] in STDLIB_NAMES
```

Categories covered: stdio.h, stdlib.h, string.h, math.h, ctype.h, locale.h, signal.h, setjmp.h, time.h, assert.h, wchar.h functions and types.

Frontend uses this flag to filter stdlib items from the sidebar and canvas by default.

## 9. Target Architecture Configuration

Defined in `TARGET_MAP`:

```python
TARGET_MAP = {
    "arm":       {"triple": "arm-none-eabi",              "pointer_size": 4, "endianness": "little"},
    "sparc":     {"triple": "sparc-unknown-elf",          "pointer_size": 4, "endianness": "big"},
    "linux_x64": {"triple": "x86_64-unknown-linux-gnu",   "pointer_size": 8, "endianness": "little"},
    "win_x64":   {"triple": "x86_64-pc-windows-msvc",     "pointer_size": 8, "endianness": "little"},
}
```

The triple is passed to libclang as `-target <triple>`, which controls:
- Pointer size (4 vs 8 bytes)
- Default alignment rules
- ABI-specific struct layout
- Endianness (affects layout visualization context, not parsing)

## 10. Bundled Headers (`cstruct_headers/`)

Minimal C standard library header stubs so libclang doesn't error on `#include <stdint.h>`, `<stdbool.h>`, etc. These define the standard types (uint32_t, bool, size_t) but don't include actual libc implementations.

Current bundled headers: stdbool.h, stdint.h, stddef.h, stdio.h, stdlib.h, string.h, assert.h, ctype.h, errno.h, float.h, limits.h, locale.h, math.h, pthread.h, signal.h, unistd.h.

Path: `HEADERS_DIR = Path(__file__).parent / "cstruct_headers"`
Passed as: `-I <HEADERS_DIR>`

## 11. Warning System

### Missing Includes
Extracted from libclang diagnostics where `"file not found"` appears in the message:
```
"Missing include: config.h — upload this file for complete parsing"
```

### Parse Errors
Diagnostics with severity >= 3 (Error or Fatal):
```
"Parse warning: unknown type name 'custom_type_t'"
```

### Empty Results
If no types found after parsing:
```
"No types found in 3 file(s): main.c, util.c, types.h"
"Tip: ensure files contain struct/union/enum definitions (not just function implementations)"
```

## 12. Anti-Patterns

- **Never import Flask in c_parser.py** — it's pure functions only
- **Never cache AST results** — each parse is a fresh temp directory + Index
- **Never skip temp directory cleanup** — always use `try/finally` with `shutil.rmtree`
- **Never assume file paths match** — use normalized comparison in `_is_from_user_file`
- **Never trust negative values from libclang** — `get_size()` and `get_field_offsetof()` can return -1 for incomplete types; default to 0
- **Never forget path_map** — every _process_* function that creates entities must pass path_map for source tracking
