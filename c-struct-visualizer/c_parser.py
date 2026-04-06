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

        # Add each directory as an include path
        parent = os.path.dirname(file_path)
        include_dirs.add(parent)

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

    # Collect diagnostics as warnings
    warnings = _collect_warnings(tu, user_files)

    # Walk AST
    structs = []
    unions = []
    typedefs = {}
    enums = []
    connections = []
    seen_names: set[str] = set()
    anon_counter = {"struct": 0, "union": 0}

    _walk_cursor(
        tu.cursor,
        user_files,
        structs,
        unions,
        typedefs,
        enums,
        connections,
        seen_names,
        anon_counter,
        target_info,
    )

    # Add diagnostic info if nothing was found
    total = len(structs) + len(unions) + len(enums)
    if total == 0:
        file_list = ", ".join(os.path.basename(f) for f in sorted(user_files) if "__main__" not in f)
        warnings.append(f"No types found in {len(file_contents)} file(s): {file_list}")
        warnings.append(
            "Tip: ensure files contain struct/union/enum definitions "
            "(not just function implementations)"
        )

    return {
        "structs": structs,
        "unions": unions,
        "typedefs": typedefs,
        "enums": enums,
        "connections": connections,
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
        "connections": [],
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


def _walk_cursor(
    cursor: Cursor,
    user_files: set[str],
    structs: list,
    unions: list,
    typedefs: dict,
    enums: list,
    connections: list,
    seen_names: set,
    anon_counter: dict,
    target_info: dict,
) -> None:
    """Recursively walk the AST and collect type definitions."""
    for child in cursor.get_children():
        # Only process items from user files
        if not _is_from_user_file(child, user_files):
            # Still recurse into included user files
            if child.location.file and _is_from_user_file(child, user_files):
                pass  # will be handled below
            else:
                continue

        if child.kind == CursorKind.STRUCT_DECL:
            _process_record(
                child, False, user_files, structs, unions,
                connections, seen_names, anon_counter, target_info,
            )
        elif child.kind == CursorKind.UNION_DECL:
            _process_record(
                child, True, user_files, structs, unions,
                connections, seen_names, anon_counter, target_info,
            )
        elif child.kind == CursorKind.TYPEDEF_DECL:
            _process_typedef(child, typedefs)
        elif child.kind == CursorKind.ENUM_DECL:
            _process_enum(child, enums, seen_names, anon_counter)
        else:
            # Recurse into children
            _walk_cursor(
                child, user_files, structs, unions,
                typedefs, enums, connections, seen_names,
                anon_counter, target_info,
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

    record = {
        "name": name,
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

    enums.append({
        "name": name,
        "values": values,
    })
