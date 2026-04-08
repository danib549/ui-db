"""
c_parser.py — Parse C/H files using libclang to extract struct/union/enum layouts
with precise field offsets, sizes, padding, and nesting connections.

Pure functions only — no Flask, no HTTP, no side effects.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from clang.cindex import (
    Index,
    TranslationUnit,
    CursorKind,
    TypeKind,
    Cursor,
    StorageClass,
)

# Path to bundled fake system headers
HEADERS_DIR = str(Path(__file__).parent / "cstruct_headers")

# Target architecture → libclang triple + metadata
TARGET_MAP: dict[str, dict] = {
    "arm": {
        "triple": "arm-none-eabi",
        "pointer_size": 4,
        "endianness": "little",
        "label": "ARM (32-bit)",
    },
    "sparc": {
        "triple": "sparc-unknown-elf",
        "pointer_size": 4,
        "endianness": "big",
        "label": "SPARC/LEON3",
    },
    "linux_x64": {
        "triple": "x86_64-unknown-linux-gnu",
        "pointer_size": 8,
        "endianness": "little",
        "label": "Linux x86_64",
    },
    "win_x64": {
        "triple": "x86_64-pc-windows-msvc",
        "pointer_size": 8,
        "endianness": "little",
        "label": "Windows x64 (MSVC)",
    },
}

# Known C standard library names — filtered out during parsing so that
# user-uploaded files that redeclare stdlib items don't pollute the sidebar.
STDLIB_NAMES: frozenset[str] = frozenset({
    # ---- Types / structs ----
    "_FILE", "FILE", "_iobuf", "__sFILE", "_IO_FILE",
    "div_t", "ldiv_t", "lconv", "tm", "fpos_t", "va_list",

    # ---- stdio.h ----
    "printf", "fprintf", "sprintf", "snprintf",
    "vprintf", "vfprintf", "vsprintf", "vsnprintf",
    "scanf", "fscanf", "sscanf",
    "fgetc", "fgets", "fputc", "fputs",
    "getc", "getchar", "putc", "putchar", "puts", "ungetc",
    "fopen", "freopen", "fclose", "fflush",
    "fread", "fwrite",
    "fseek", "ftell", "rewind", "fgetpos", "fsetpos",
    "feof", "ferror", "clearerr", "perror",
    "remove", "rename", "tmpfile", "tmpnam",
    "setbuf", "setvbuf",

    # ---- stdlib.h ----
    "malloc", "calloc", "realloc", "free",
    "atoi", "atol", "atoll", "atof",
    "strtol", "strtoul", "strtoll", "strtoull", "strtod", "strtof", "strtold",
    "exit", "abort", "atexit", "_Exit", "quick_exit", "at_quick_exit",
    "qsort", "bsearch",
    "abs", "labs", "llabs", "div", "ldiv", "lldiv",
    "rand", "srand",
    "system", "getenv",

    # ---- string.h ----
    "memcpy", "memmove", "memset", "memcmp", "memchr",
    "strlen", "strcpy", "strncpy",
    "strcat", "strncat",
    "strcmp", "strncmp",
    "strchr", "strrchr", "strstr", "strtok", "strerror",
    "strcoll", "strxfrm", "strspn", "strcspn", "strpbrk",

    # ---- math.h ----
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
    "exp", "exp2", "expm1", "log", "log2", "log10", "log1p",
    "pow", "sqrt", "cbrt", "hypot",
    "ceil", "floor", "round", "trunc", "fabs", "fmod",
    "remainder", "copysign", "nan", "ldexp", "frexp", "modf",
    "isinf", "isnan", "isfinite", "fpclassify",
    "erf", "erfc", "tgamma", "lgamma",
    "nextafter", "nexttoward", "fdim", "fmax", "fmin", "fma",

    # ---- ctype.h ----
    "isalpha", "isdigit", "isalnum", "isspace",
    "isupper", "islower", "isprint", "ispunct",
    "iscntrl", "isxdigit", "isgraph",
    "toupper", "tolower",

    # ---- locale.h ----
    "setlocale", "localeconv",

    # ---- signal.h ----
    "signal", "raise",

    # ---- setjmp.h ----
    "setjmp", "longjmp",

    # ---- time.h ----
    "time", "clock", "difftime", "mktime",
    "strftime", "gmtime", "localtime", "asctime", "ctime",

    # ---- assert.h ----
    "assert",

    # ---- wchar.h ----
    "wprintf", "fwprintf", "swprintf", "wcslen", "wcscpy", "wcscat",
    "wcscmp", "wmemcpy", "wmemset", "wmemcmp",
})


def get_target_info(target_key: str) -> dict:
    """Return target metadata or default to ARM."""
    return TARGET_MAP.get(target_key, TARGET_MAP["arm"])


def parse_c_files(
    file_contents: dict[str, str],
    target: str = "arm",
) -> dict:
    """Parse C source files and extract struct/union/enum layouts.

    Args:
        file_contents: {filename: source_code_string}
        target: Target architecture key (arm, sparc, linux_x64, win_x64)

    Returns:
        {structs, unions, typedefs, enums, connections, warnings, target_info}
    """
    target_info = get_target_info(target)
    triple = target_info["triple"]

    if not file_contents:
        return _empty_result(target_info)

    # Write files to a temp directory so cross-file #includes resolve correctly.
    # unsaved_files can't handle relative include paths between virtual files.
    tmpdir = tempfile.mkdtemp(prefix="cstruct_")
    try:
        return _parse_in_directory(tmpdir, file_contents, triple, target, target_info)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _parse_in_directory(
    tmpdir: str,
    file_contents: dict[str, str],
    triple: str,
    target: str,
    target_info: dict,
) -> dict:
    """Write files to tmpdir, parse with libclang, return results."""
    # Write all uploaded files preserving directory structure
    include_dirs: set[str] = set()
    include_dirs.add(tmpdir)
    written_paths: list[str] = []

    for name, content in file_contents.items():
        safe_name = name.replace("\\", "/")
        file_path = os.path.join(tmpdir, safe_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        written_paths.append(file_path)

        # Add each directory AND all ancestor directories as include paths.
        # This ensures that #include "router/file.h" resolves correctly when
        # "router/" is a sibling folder, not under the including file's dir.
        parent = os.path.dirname(file_path)
        while parent and parent != tmpdir and parent not in include_dirs:
            include_dirs.add(parent)
            parent = os.path.dirname(parent)
        include_dirs.add(parent)  # ensure the last level is added

    # Create a main file that includes all uploaded files
    main_path = os.path.join(tmpdir, "__main__.c")
    includes = "\n".join(f'#include "{p}"' for p in written_paths)
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(includes)

    args = [
        "-target", triple,
        "-std=c11",
        "-I", HEADERS_DIR,
        "-fsyntax-only",
        "-Wno-everything",
    ]
    for d in sorted(include_dirs):
        args.extend(["-I", d])

    index = Index.create()
    try:
        tu = index.parse(
            main_path,
            args=args,
            options=TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
        )
    except Exception as e:
        return {**_empty_result(target_info), "warnings": [f"Parse error: {e}"]}

    # Build a set of absolute paths of user files for filtering
    user_files = set(written_paths)
    user_files.add(main_path)

    # Reverse map: tmpdir absolute path -> original upload filename
    path_map: dict[str, str] = {}
    for name in file_contents:
        safe = name.replace("\\", "/")
        abs_path = os.path.normpath(os.path.join(tmpdir, safe))
        path_map[abs_path] = name

    # Collect diagnostics as warnings
    warnings = _collect_warnings(tu, user_files)

    # Walk AST
    structs = []
    unions = []
    typedefs = {}
    enums = []
    functions = []
    connections = []
    globals_list = []
    seen_names: set[str] = set()
    seen_globals: set[str] = set()
    anon_counter = {"struct": 0, "union": 0}

    _walk_cursor(
        tu.cursor,
        user_files,
        structs,
        unions,
        typedefs,
        enums,
        functions,
        connections,
        seen_names,
        anon_counter,
        target_info,
        path_map,
        globals_list,
        seen_globals,
    )

    # Extract macros (#define constants) from user files
    macros = []
    for child in tu.cursor.get_children():
        if child.kind == CursorKind.MACRO_DEFINITION:
            if _is_from_user_file(child, user_files):
                _process_macro(child, macros, path_map)

    # Extract include graph from translation unit
    includes = []
    seen_includes: set[tuple[str, str]] = set()
    for inc in tu.get_includes():
        source_loc = inc.location
        target_file = inc.include
        if not source_loc or not source_loc.file or not target_file:
            continue
        src_path = os.path.normpath(str(source_loc.file))
        tgt_path = os.path.normpath(str(target_file))
        # Map to user-facing filenames, skip if not in user files
        src_name = path_map.get(src_path)
        tgt_name = path_map.get(tgt_path)
        if not src_name or not tgt_name:
            continue
        edge = (src_name, tgt_name)
        if edge in seen_includes:
            continue
        seen_includes.add(edge)
        includes.append({
            "source": src_name,
            "target": tgt_name,
            "line": source_loc.line,
            "depth": inc.depth,
        })

    # Add diagnostic info if nothing was found
    total = len(structs) + len(unions) + len(enums) + len(functions)
    if total == 0:
        file_list = ", ".join(os.path.basename(f) for f in sorted(user_files) if "__main__" not in f)
        warnings.append(f"No types found in {len(file_contents)} file(s): {file_list}")
        warnings.append(
            "Tip: ensure files contain struct/union/enum definitions "
            "(not just function implementations)"
        )

    # Build reverse typedef map: struct_tag -> preferred typedef name
    # e.g. _sensor_data -> sensor_data_t, so blocks show the cleaner name
    reverse_typedefs: dict[str, str] = {}
    for alias, tag in typedefs.items():
        existing = reverse_typedefs.get(tag)
        # Prefer aliases without leading underscore, then shorter names
        if existing is None or (alias[0] != '_' and existing[0] == '_') or len(alias) < len(existing):
            reverse_typedefs[tag] = alias

    # Add displayName to structs and unions
    for entity in structs + unions:
        name = entity["name"]
        typedef_alias = reverse_typedefs.get(name)
        if typedef_alias and typedef_alias != name:
            entity["displayName"] = typedef_alias
        elif name.startswith("__anon_"):
            entity["displayName"] = "(anonymous)"
        else:
            entity["displayName"] = name

    # Functions keep their own name
    for fn in functions:
        fn["displayName"] = fn["name"]

    # Tag known stdlib entities so the frontend can filter them
    for entity in structs + unions:
        entity["isStdlib"] = entity["name"] in STDLIB_NAMES
    for fn in functions:
        fn["isStdlib"] = fn["name"] in STDLIB_NAMES

    # Prune call connections whose targets aren't in parsed entities
    all_names = seen_names.copy()
    connections[:] = [
        c for c in connections
        if c["type"] != "call" or c["target"] in all_names
    ]

    # Resolve indirect calls through function pointers
    # Build assignment map: field_name → [target_func_names]
    assign_map: dict[str, list[str]] = {}
    for c in connections:
        if c["type"] == "funcptr":
            # field is "via .callback_name" → extract field name
            field = c.get("field", "")
            fname = field.replace("via .", "").replace("via ", "")
            assign_map.setdefault(fname, []).append(c["target"])

    # Match indirect calls to assignments (deduplicate)
    seen_indirect: set[str] = set()
    for fn in functions:
        for ic in fn.get("_indirectCalls", []):
            field_name = ic["field"]
            targets = assign_map.get(field_name, [])
            for t in targets:
                key = f"{ic['caller']}->{t}:{field_name}"
                if t in all_names and key not in seen_indirect:
                    seen_indirect.add(key)
                    connections.append({
                        "source": ic["caller"],
                        "target": t,
                        "type": "indirect_call",
                        "field": f"via .{field_name}",
                    })

    # Clean up internal tracking keys
    for fn in functions:
        fn.pop("_indirectCalls", None)

    return {
        "structs": structs,
        "unions": unions,
        "typedefs": typedefs,
        "enums": enums,
        "functions": functions,
        "connections": connections,
        "globals": globals_list,
        "macros": macros,
        "includes": includes,
        "warnings": warnings,
        "target_info": {
            "key": target,
            "label": target_info["label"],
            "endianness": target_info["endianness"],
            "pointer_size": target_info["pointer_size"],
        },
    }


def _empty_result(target_info: dict) -> dict:
    return {
        "structs": [],
        "unions": [],
        "typedefs": {},
        "enums": [],
        "functions": [],
        "connections": [],
        "globals": [],
        "macros": [],
        "includes": [],
        "warnings": [],
        "target_info": {
            "key": "arm",
            "label": target_info["label"],
            "endianness": target_info["endianness"],
            "pointer_size": target_info["pointer_size"],
        },
    }


def _collect_warnings(tu: TranslationUnit, user_files: set[str]) -> list[str]:
    """Extract useful diagnostics from the translation unit."""
    warnings = []
    for diag in tu.diagnostics:
        msg = diag.spelling
        # Flag missing includes specifically
        if "file not found" in msg.lower():
            fname = msg.split("'")[1] if "'" in msg else msg
            warnings.append(
                f"Missing include: {fname} \u2014 upload this file for complete parsing"
            )
        elif diag.severity >= 3:  # Error or Fatal
            warnings.append(f"Parse warning: {msg}")
    return warnings


def _is_from_user_file(cursor: Cursor, user_files: set[str]) -> bool:
    """Check if a cursor is from one of the user-uploaded files."""
    loc = cursor.location
    if loc.file is None:
        return False
    fname = loc.file.name
    # Direct match (absolute paths)
    if fname in user_files:
        return True
    # Normalize and retry
    normalized = os.path.normpath(fname)
    if normalized in user_files:
        return True
    # Check if any user file path matches as suffix
    for uf in user_files:
        if normalized.endswith(os.path.basename(uf)) or uf.endswith(os.path.basename(normalized)):
            return True
    return False


def _get_source_location(
    cursor: Cursor,
    path_map: dict[str, str],
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """Map a cursor's file location back to the original upload filename.

    Returns (filename, start_line, end_line).
    """
    loc = cursor.location
    if loc.file is None:
        return None, None, None
    normalized = os.path.normpath(loc.file.name)
    original_name = path_map.get(normalized)
    if original_name is None:
        # Fallback: basename matching
        for abs_path, name in path_map.items():
            if normalized.endswith(os.path.basename(abs_path)):
                original_name = name
                break
    if original_name is None:
        return None, None, None
    ext = cursor.extent
    start_line = ext.start.line if ext else loc.line
    end_line = ext.end.line if ext else loc.line
    return original_name, start_line, end_line


def _walk_cursor(
    cursor: Cursor,
    user_files: set[str],
    structs: list,
    unions: list,
    typedefs: dict,
    enums: list,
    functions: list,
    connections: list,
    seen_names: set,
    anon_counter: dict,
    target_info: dict,
    path_map: dict[str, str],
    globals_list: list | None = None,
    seen_globals: set | None = None,
) -> None:
    """Recursively walk the AST and collect type definitions and functions."""
    for child in cursor.get_children():
        # Only process items from user files
        if not _is_from_user_file(child, user_files):
            continue

        if child.kind == CursorKind.STRUCT_DECL:
            _process_record(
                child, False, user_files, structs, unions,
                connections, seen_names, anon_counter, target_info, path_map,
            )
        elif child.kind == CursorKind.UNION_DECL:
            _process_record(
                child, True, user_files, structs, unions,
                connections, seen_names, anon_counter, target_info, path_map,
            )
        elif child.kind == CursorKind.TYPEDEF_DECL:
            _process_typedef(child, typedefs)
        elif child.kind == CursorKind.ENUM_DECL:
            _process_enum(child, enums, seen_names, anon_counter, path_map)
        elif child.kind == CursorKind.FUNCTION_DECL:
            _process_function(child, functions, connections, seen_names, path_map)
        elif child.kind == CursorKind.VAR_DECL and globals_list is not None:
            # File-scope variable (not inside a function body)
            _process_global_var(
                child, globals_list, connections, seen_globals, path_map,
            )
        else:
            # Recurse into children
            _walk_cursor(
                child, user_files, structs, unions,
                typedefs, enums, functions, connections, seen_names,
                anon_counter, target_info, path_map,
                globals_list, seen_globals,
            )


def _process_record(
    cursor: Cursor,
    is_union: bool,
    user_files: set[str],
    structs: list,
    unions: list,
    connections: list,
    seen_names: set,
    anon_counter: dict,
    target_info: dict,
    path_map: dict[str, str],
) -> None:
    """Process a struct or union declaration."""
    # Skip forward declarations (no definition)
    if not cursor.is_definition():
        return

    name = cursor.spelling
    if not name:
        key = "union" if is_union else "struct"
        anon_counter[key] += 1
        name = f"__anon_{key}_{anon_counter[key]}"

    if name in seen_names:
        return
    seen_names.add(name)

    # Get total size
    record_type = cursor.type
    total_size = record_type.get_size()
    if total_size < 0:
        total_size = 0

    # Get alignment
    alignment = record_type.get_align()
    if alignment < 0:
        alignment = 0

    # Check for packed attribute
    packed = _is_packed(cursor)

    # Extract fields
    fields = []
    prev_end_bit = 0

    for field_cursor in cursor.get_children():
        if field_cursor.kind != CursorKind.FIELD_DECL:
            continue

        field = _extract_field(field_cursor, is_union, connections, name, target_info)
        if field is None:
            continue

        # Insert padding before this field (only for non-packed structs)
        if not is_union:
            field_start_bit = field.get("_start_bit", 0)
            if not packed and field_start_bit > prev_end_bit:
                pad_bytes = (field_start_bit - prev_end_bit) // 8
                if pad_bytes > 0:
                    fields.append({
                        "name": f"__pad_{len(fields)}",
                        "type": "(padding)",
                        "offset": prev_end_bit // 8,
                        "size": pad_bytes,
                        "bitOffset": None,
                        "bitSize": None,
                        "category": "padding",
                    })

            # Always track end of this field for tail padding computation
            if field.get("bitSize"):
                prev_end_bit = field_start_bit + field["bitSize"]
            else:
                prev_end_bit = field_start_bit + field["size"] * 8

        # Remove internal tracking key
        field.pop("_start_bit", None)
        fields.append(field)

    # Add tail padding for structs
    if not is_union and total_size > 0 and fields:
        last_end_byte = prev_end_bit // 8
        if (prev_end_bit % 8) != 0:
            last_end_byte += 1
        if last_end_byte < total_size:
            fields.append({
                "name": "(tail padding)",
                "type": "(padding)",
                "offset": last_end_byte,
                "size": total_size - last_end_byte,
                "bitOffset": None,
                "bitSize": None,
                "category": "padding",
            })

    source_file, source_line, source_end_line = _get_source_location(cursor, path_map)

    record = {
        "name": name,
        "sourceFile": source_file,
        "sourceLine": source_line,
        "sourceEndLine": source_end_line,
        "totalSize": total_size,
        "alignment": alignment,
        "packed": packed,
        "isUnion": is_union,
        "fields": fields,
    }

    if is_union:
        unions.append(record)
    else:
        structs.append(record)


def _extract_field(
    cursor: Cursor,
    is_union: bool,
    connections: list,
    parent_name: str,
    target_info: dict,
) -> Optional[dict]:
    """Extract a single field from a struct/union."""
    field_name = cursor.spelling
    field_type = cursor.type

    # Type name
    type_name = field_type.spelling

    # Size in bytes
    size = field_type.get_size()
    if size < 0:
        size = 0

    # Bit offset from struct start
    bit_offset_raw = cursor.get_field_offsetof()
    byte_offset = bit_offset_raw // 8 if bit_offset_raw >= 0 else 0

    # Check if this is a bitfield
    is_bitfield = cursor.is_bitfield()
    bit_size = None
    if is_bitfield:
        bit_size = cursor.get_bitfield_width()

    # Categorize the field
    category = _categorize_type(field_type, is_bitfield)

    # Detect function pointer fields
    funcptr_sig = None
    fp_canonical = field_type.get_canonical()
    if fp_canonical.kind == TypeKind.POINTER:
        pointee = fp_canonical.get_pointee()
        if pointee.kind == TypeKind.FUNCTIONPROTO:
            category = "funcptr"
            funcptr_sig = pointee.spelling

    # Detect nested struct/union references
    ref_struct = None
    canonical = field_type.get_canonical()
    if canonical.kind == TypeKind.RECORD:
        ref_name = canonical.spelling
        # Clean up "struct X" -> "X"
        for prefix in ("struct ", "union "):
            if ref_name.startswith(prefix):
                ref_name = ref_name[len(prefix):]
        if ref_name and ref_name != parent_name:
            ref_struct = ref_name
            connections.append({
                "source": parent_name,
                "target": ref_name,
                "type": "nested",
                "field": field_name,
            })

    # For arrays: check if element type is a struct
    if field_type.kind == TypeKind.CONSTANTARRAY:
        elem = field_type.element_type
        elem_canonical = elem.get_canonical()
        if elem_canonical.kind == TypeKind.RECORD:
            ref_name = elem_canonical.spelling
            for prefix in ("struct ", "union "):
                if ref_name.startswith(prefix):
                    ref_name = ref_name[len(prefix):]
            if ref_name and ref_name != parent_name:
                ref_struct = ref_name
                connections.append({
                    "source": parent_name,
                    "target": ref_name,
                    "type": "nested",
                    "field": field_name,
                })

    result = {
        "name": field_name,
        "type": type_name,
        "offset": byte_offset,
        "size": size,
        "bitOffset": bit_offset_raw if bit_offset_raw >= 0 else None,
        "bitSize": bit_size,
        "category": category,
        "_start_bit": bit_offset_raw if bit_offset_raw >= 0 else 0,
    }

    if ref_struct:
        result["refStruct"] = ref_struct
    if funcptr_sig:
        result["funcptrSig"] = funcptr_sig

    return result


def _categorize_type(field_type, is_bitfield: bool) -> str:
    """Categorize a field type for visual rendering."""
    if is_bitfield:
        return "bitfield"

    canonical = field_type.get_canonical()
    kind = canonical.kind

    if kind == TypeKind.RECORD:
        return "struct"

    if kind == TypeKind.ENUM:
        return "enum"

    if kind == TypeKind.POINTER:
        pointee = canonical.get_pointee()
        if pointee.kind == TypeKind.FUNCTIONPROTO:
            return "funcptr"
        return "pointer"

    if kind == TypeKind.CONSTANTARRAY or kind == TypeKind.INCOMPLETEARRAY:
        return "array"

    if kind in (TypeKind.FLOAT, TypeKind.DOUBLE, TypeKind.LONGDOUBLE):
        return "float"

    if kind == TypeKind.BOOL:
        return "integer"

    # Default: integer (covers char, short, int, long, etc.)
    return "integer"


def _is_packed(cursor: Cursor) -> bool:
    """Check if a struct/union has __attribute__((packed)) or #pragma pack."""
    # Check for packed attribute
    for child in cursor.get_children():
        if child.kind == CursorKind.PACKED_ATTR:
            return True

    # Heuristic: check if alignment equals 1 (packed structs have alignment 1)
    alignment = cursor.type.get_align()
    if alignment == 1:
        # Verify it has fields with types that normally require > 1 alignment
        for child in cursor.get_children():
            if child.kind == CursorKind.FIELD_DECL:
                field_align = child.type.get_align()
                if field_align > 1:
                    return True

    return False


def _process_typedef(cursor: Cursor, typedefs: dict) -> None:
    """Process a typedef declaration."""
    typedef_name = cursor.spelling
    underlying = cursor.underlying_typedef_type

    # Resolve to the canonical type name
    canonical = underlying.get_canonical()
    target_name = canonical.spelling

    # Clean up struct/union prefix
    for prefix in ("struct ", "union "):
        if target_name.startswith(prefix):
            target_name = target_name[len(prefix):]

    if typedef_name and target_name and typedef_name != target_name:
        typedefs[typedef_name] = target_name


def _process_enum(
    cursor: Cursor,
    enums: list,
    seen_names: set,
    anon_counter: dict,
    path_map: dict[str, str],
) -> None:
    """Process an enum declaration."""
    if not cursor.is_definition():
        return

    name = cursor.spelling
    if not name:
        anon_counter.setdefault("enum", 0)
        anon_counter["enum"] += 1
        name = f"__anon_enum_{anon_counter['enum']}"

    if name in seen_names:
        return
    seen_names.add(name)

    values = []
    for child in cursor.get_children():
        if child.kind == CursorKind.ENUM_CONSTANT_DECL:
            values.append({
                "name": child.spelling,
                "value": child.enum_value,
            })

    source_file, source_line, source_end_line = _get_source_location(cursor, path_map)

    enums.append({
        "name": name,
        "sourceFile": source_file,
        "sourceLine": source_line,
        "sourceEndLine": source_end_line,
        "values": values,
    })


# ---- Phase 2: Function extraction ----


def _resolve_struct_name(type_obj) -> Optional[str]:
    """If type is a struct or pointer-to-struct (any depth), return the struct name.

    Handles multi-level pointers (e.g. SensorConfig **) by unwrapping
    all pointer layers before checking for a record type. Uses
    get_canonical() to pierce through typedef aliases.
    """
    canonical = type_obj.get_canonical()

    # Unwrap all pointer layers (SensorConfig **, void ***, etc.)
    while canonical.kind == TypeKind.POINTER:
        canonical = canonical.get_pointee().get_canonical()

    if canonical.kind == TypeKind.RECORD:
        name = canonical.spelling
        for prefix in ("struct ", "union "):
            if name.startswith(prefix):
                name = name[len(prefix):]
        return name or None

    return None


def _is_pointer_type(type_obj) -> bool:
    """Check if a type is any level of pointer."""
    return type_obj.get_canonical().kind == TypeKind.POINTER


def _categorize_param_type(type_obj) -> str:
    """Categorize a function parameter type for visual badging.

    Uses get_canonical() to resolve through typedef aliases so that
    e.g. status_t (typedef for enum) gets categorized as 'enum'.
    """
    canonical = type_obj.get_canonical()

    if canonical.kind == TypeKind.POINTER:
        pointee = canonical.get_pointee()
        if pointee.kind == TypeKind.FUNCTIONPROTO:
            return "funcptr"
        return "pointer"
    if canonical.kind == TypeKind.RECORD:
        return "struct"
    if canonical.kind == TypeKind.ENUM:
        return "enum"
    if canonical.kind in (TypeKind.FLOAT, TypeKind.DOUBLE, TypeKind.LONGDOUBLE):
        return "float"
    if canonical.kind == TypeKind.CONSTANTARRAY or canonical.kind == TypeKind.INCOMPLETEARRAY:
        return "array"
    if canonical.kind == TypeKind.BOOL:
        return "integer"
    return "integer"


def _find_func_refs_in_expr(cursor: Cursor) -> list[str]:
    """Recursively find all DECL_REF_EXPR nodes that reference functions."""
    refs = []
    if cursor.kind == CursorKind.DECL_REF_EXPR:
        ref = cursor.referenced
        if ref and ref.kind == CursorKind.FUNCTION_DECL:
            refs.append(cursor.spelling)
    for child in cursor.get_children():
        refs.extend(_find_func_refs_in_expr(child))
    return refs


def _get_member_field_name(cursor: Cursor) -> Optional[str]:
    """Extract the field name from a MEMBER_REF_EXPR in the LHS of an assignment."""
    if cursor.kind == CursorKind.MEMBER_REF_EXPR:
        return cursor.spelling
    for child in cursor.get_children():
        result = _get_member_field_name(child)
        if result:
            return result
    return None


def _collect_body_refs(
    cursor: Cursor,
    func_name: str,
    connections: list,
    seen_refs: set[str],
    seen_calls: set[str],
    seen_assigns: set[str] | None = None,
    indirect_calls: list | None = None,
) -> None:
    """Recursively walk a function body to find local struct refs, function calls,
    function pointer assignments, and indirect calls.
    """
    if seen_assigns is None:
        seen_assigns = set()
    if indirect_calls is None:
        indirect_calls = []

    for child in cursor.get_children():
        if child.kind == CursorKind.VAR_DECL:
            ref = _resolve_struct_name(child.type)
            if ref and ref not in seen_refs:
                seen_refs.add(ref)
                connections.append({
                    "source": func_name,
                    "target": ref,
                    "type": "uses",
                    "field": child.spelling or "(local)",
                })
            # Check for struct initializer with function pointer assignments
            # e.g. struct driver d = { .init = uart_init, .read = uart_read };
            for init_child in child.get_children():
                if init_child.kind == CursorKind.INIT_LIST_EXPR:
                    _collect_init_list_funcptrs(
                        init_child, child.type, func_name,
                        connections, seen_assigns,
                    )

        elif child.kind == CursorKind.CALL_EXPR:
            callee_name = child.spelling
            ref = child.referenced
            if ref and ref.kind == CursorKind.FUNCTION_DECL:
                # Direct call
                if callee_name and callee_name != func_name and callee_name not in seen_calls:
                    seen_calls.add(callee_name)
                    connections.append({
                        "source": func_name,
                        "target": callee_name,
                        "type": "call",
                        "field": None,
                    })
            else:
                # Indirect call — through a function pointer
                field_name = _get_member_field_name(child)
                if field_name:
                    indirect_calls.append({
                        "caller": func_name,
                        "field": field_name,
                    })

        elif child.kind == CursorKind.BINARY_OPERATOR:
            # Check for funcptr assignment: ctx->callback = some_func
            _collect_assignment_funcptr(
                child, func_name, connections, seen_assigns,
            )

        # Recurse into any compound/control-flow children
        _collect_body_refs(
            child, func_name, connections, seen_refs, seen_calls,
            seen_assigns, indirect_calls,
        )


def _collect_assignment_funcptr(
    cursor: Cursor,
    func_name: str,
    connections: list,
    seen_assigns: set[str],
) -> None:
    """Check if a binary operator is a funcptr assignment like ctx->cb = handler."""
    children = list(cursor.get_children())
    if len(children) != 2:
        return

    lhs, rhs = children

    # Get field name from LHS (MEMBER_REF_EXPR)
    field_name = _get_member_field_name(lhs)
    if not field_name:
        return

    # Find function references in RHS (handles ternary, direct ref, etc.)
    func_refs = _find_func_refs_in_expr(rhs)
    for target in func_refs:
        key = f"{field_name}={target}"
        if key in seen_assigns:
            continue
        seen_assigns.add(key)
        connections.append({
            "source": func_name,
            "target": target,
            "type": "funcptr",
            "field": f"via .{field_name}",
        })


def _collect_init_list_funcptrs(
    cursor: Cursor,
    var_type,
    func_name: str,
    connections: list,
    seen_assigns: set[str],
) -> None:
    """Extract function pointer assignments from struct initializer lists."""
    # Get the struct fields to match init list positions
    canonical = var_type.get_canonical()
    if canonical.kind != TypeKind.RECORD:
        return

    decl = canonical.get_declaration()
    if not decl:
        return

    struct_fields = [
        f for f in decl.get_children()
        if f.kind == CursorKind.FIELD_DECL
    ]

    for i, init_expr in enumerate(cursor.get_children()):
        # Find any function references in this init expression
        func_refs = _find_func_refs_in_expr(init_expr)
        if not func_refs:
            continue

        # Try to get the field name
        field_name = None
        if i < len(struct_fields):
            field_name = struct_fields[i].spelling

        for target in func_refs:
            label = f"via .{field_name}" if field_name else f"via init[{i}]"
            key = f"{label}={target}"
            if key in seen_assigns:
                continue
            seen_assigns.add(key)
            connections.append({
                "source": func_name,
                "target": target,
                "type": "funcptr",
                "field": label,
            })


def _process_global_var(
    cursor: Cursor,
    globals_list: list,
    connections: list,
    seen_globals: set[str],
    path_map: dict[str, str],
) -> None:
    """Extract a file-scope global variable declaration."""
    name = cursor.spelling
    if not name or name in seen_globals:
        return

    # Determine storage class
    sc = cursor.storage_class
    if sc == StorageClass.STATIC:
        storage = "static"
    elif sc == StorageClass.EXTERN:
        storage = "extern"
    else:
        storage = "global"

    type_spelling = cursor.type.spelling
    source_file, _, _ = _get_source_location(cursor, path_map)
    struct_ref = _resolve_struct_name(cursor.type)

    # Check for function pointer assignments in global initializer
    # e.g. static hal_driver_t uart_driver = { .init = uart_init, ... };
    seen_assigns: set[str] = set()
    for child in cursor.get_children():
        if child.kind == CursorKind.INIT_LIST_EXPR:
            _collect_init_list_funcptrs(
                child, cursor.type, name,
                connections, seen_assigns,
            )

    seen_globals.add(name)
    globals_list.append({
        "name": name,
        "type": type_spelling,
        "storage": storage,
        "sourceFile": source_file,
        "structRef": struct_ref,
    })

    # Add connection from global to its struct type
    if struct_ref:
        connections.append({
            "source": name,
            "target": struct_ref,
            "type": "global",
            "field": name,
        })


def _process_macro(
    cursor: Cursor,
    macros: list,
    path_map: dict[str, str],
) -> None:
    """Extract a #define macro with its value from tokens."""
    name = cursor.spelling
    if not name or name.startswith("__") or name.startswith("_"):
        return

    tokens = list(cursor.get_tokens())
    # First token is the macro name, rest is the value
    if len(tokens) <= 1:
        return  # Skip empty macros (guards, flags)

    value = " ".join(t.spelling for t in tokens[1:])
    source_file, _, _ = _get_source_location(cursor, path_map)

    macros.append({
        "name": name,
        "value": value,
        "sourceFile": source_file,
    })


def _process_function(
    cursor: Cursor,
    functions: list,
    connections: list,
    seen_names: set[str],
    path_map: dict[str, str],
) -> None:
    """Extract a function declaration with params, return type, and body struct refs."""
    name = cursor.spelling
    if not name:
        return

    # Prefer definitions over declarations. If we already saw a declaration
    # and this is the definition, replace it. If we already saw the definition, skip.
    is_def = cursor.is_definition()
    existing_idx = None
    for i, f in enumerate(functions):
        if f["name"] == name:
            existing_idx = i
            break

    if existing_idx is not None:
        if not is_def:
            return  # Already have it (maybe even the definition), skip this declaration
        # This is the definition — replace the previous declaration
        # Remove old connections from the previous pass
        connections[:] = [c for c in connections
                         if not (c["source"] == name and c["type"] in ("param", "return", "uses"))]
    elif name in seen_names:
        return

    seen_names.add(name)

    # Return type
    result_type = cursor.result_type
    return_type_str = result_type.spelling
    return_struct = _resolve_struct_name(result_type)
    is_pointer_return = _is_pointer_type(result_type)

    # Params
    params = []
    seen_param_refs: set[str] = set()  # Avoid duplicate param connections

    for child in cursor.get_children():
        if child.kind == CursorKind.PARM_DECL:
            param_type = child.type
            param_name = child.spelling or f"param{len(params)}"
            ref_struct = _resolve_struct_name(param_type)
            is_ptr = _is_pointer_type(param_type)
            category = _categorize_param_type(param_type)

            params.append({
                "name": param_name,
                "type": param_type.spelling,
                "refStruct": ref_struct,
                "isPointer": is_ptr,
                "category": category,
            })

            # Add param connection (deduplicate by struct name)
            if ref_struct and ref_struct not in seen_param_refs:
                seen_param_refs.add(ref_struct)
                connections.append({
                    "source": name,
                    "target": ref_struct,
                    "type": "param",
                    "field": param_name,
                })

    # Return type connection
    if return_struct:
        connections.append({
            "source": name,
            "target": return_struct,
            "type": "return",
            "field": None,
        })

    # Walk function body for local struct variable usage and function calls
    body_refs: set[str] = set()
    # Don't duplicate refs already captured as params or return
    body_refs.update(seen_param_refs)
    if return_struct:
        body_refs.add(return_struct)
    seen_calls: set[str] = set()
    seen_assigns: set[str] = set()
    indirect_calls: list[dict] = []

    for child in cursor.get_children():
        if child.kind == CursorKind.COMPOUND_STMT:
            _collect_body_refs(
                child, name, connections, body_refs, seen_calls,
                seen_assigns, indirect_calls,
            )

    source_file, source_line, source_end_line = _get_source_location(cursor, path_map)

    func_data = {
        "name": name,
        "sourceFile": source_file,
        "sourceLine": source_line,
        "sourceEndLine": source_end_line,
        "returnType": return_type_str,
        "returnStruct": return_struct,
        "isPointerReturn": is_pointer_return,
        "params": params,
        "bodyStructRefs": sorted(body_refs - seen_param_refs - ({return_struct} if return_struct else set())),
        "_indirectCalls": indirect_calls,
    }

    if existing_idx is not None:
        functions[existing_idx] = func_data
    else:
        functions.append(func_data)
