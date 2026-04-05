"""Schema optimizer — gated post-processing transforms for rebuild_schema.

Each optimization is one of 16 options the user toggles from the UI. Options
are exposed as `{enabled: bool, mode: "apply" | "flag"}`. "apply" mutates the
schema and appends to `decisions`; "flag" leaves the schema alone and appends
to `flags`. Some options are flag-only (destructive or too speculative to
auto-apply) and ignore the mode field.

Every detector is a pure function: `(schema, dataframes, ...) -> list[dict]`.
Apply functions mutate schema in place and return decision entries.

The canonical option keys and their defaults live in DEFAULT_OPTIONS.
"""

from __future__ import annotations

import re

from schema_builder import (
    add_constraint,
    add_index,
    find_table,
    generate_constraint_name,
    generate_index_name,
    remove_index,
)


# Threshold constants
DOWNSIZE_SAFETY = 1.5          # shrink VARCHAR to ceil(max_len * SAFETY)
ENUM_MAX_UNIQUE = 15
ENUM_MIN_TOTAL = 10
DEAD_COLUMN_MIN_ROWS = 5
FAT_TABLE_COL_THRESHOLD = 50
FAT_TABLE_SPARSE_COL_COUNT = 40
FAT_TABLE_SPARSE_RATIO = 0.9
TIME_SERIES_MIN_ROWS = 1000
IMPLICIT_FK_MIN_OVERLAP = 0.9
LOOKUP_TABLE_MAX_COLS = 2

_FK_SUFFIX = re.compile(r'_(?:id|ref|key)$', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Canonical catalog
# ---------------------------------------------------------------------------

DEFAULT_OPTIONS: dict[str, dict] = {
    # Data-driven structure
    "mn_to_1n_downgrade":              {"enabled": True,  "mode": "apply", "flag_only": False},
    "inline_lookup_tables":            {"enabled": False, "mode": "apply", "flag_only": False},
    "merge_1_1_pairs":                 {"enabled": False, "mode": "flag",  "flag_only": False},
    "drop_orphan_tables":              {"enabled": True,  "mode": "flag",  "flag_only": True},
    # Column optimization
    "type_downsizing":                 {"enabled": True,  "mode": "apply", "flag_only": False},
    "strict_nullability":              {"enabled": True,  "mode": "apply", "flag_only": False},
    "enum_discovery":                  {"enabled": True,  "mode": "apply", "flag_only": False},
    "dead_column_detection":           {"enabled": False, "mode": "flag",  "flag_only": True},
    # Indexes & FKs
    "collapse_redundant_indexes":      {"enabled": True,  "mode": "apply", "flag_only": False},
    "missing_fk_indexes":              {"enabled": True,  "mode": "apply", "flag_only": False},
    "implicit_fk_discovery":           {"enabled": False, "mode": "apply", "flag_only": False},
    # Advanced (flag only)
    "eav_to_jsonb":                    {"enabled": False, "mode": "flag",  "flag_only": True},
    "vertical_split_fat_tables":       {"enabled": False, "mode": "flag",  "flag_only": True},
    "time_series_partition_candidates": {"enabled": False, "mode": "flag",  "flag_only": True},
    # Data integrity (flag only)
    "dangling_reference_detect":       {"enabled": False, "mode": "flag",  "flag_only": True},
    "soft_delete_ghosting":            {"enabled": False, "mode": "flag",  "flag_only": True},
}


def merge_options(user_options: dict | None) -> dict[str, dict]:
    """Merge user-supplied option dict onto DEFAULT_OPTIONS. Unknown keys ignored."""
    result: dict[str, dict] = {}
    user = user_options or {}
    for key, default in DEFAULT_OPTIONS.items():
        user_entry = user.get(key) or {}
        enabled = bool(user_entry.get("enabled", default["enabled"]))
        mode = user_entry.get("mode", default["mode"])
        if default["flag_only"] or mode not in ("apply", "flag"):
            mode = "flag"
        result[key] = {"enabled": enabled, "mode": mode, "flag_only": default["flag_only"]}
    return result


def _active_mode(options: dict, key: str) -> str | None:
    """Return 'apply' | 'flag' if option enabled, else None."""
    opt = options.get(key)
    if not opt or not opt.get("enabled"):
        return None
    return opt.get("mode")


def _flag(rule: str, severity: str, title: str, table: str | None = None,
          column: str | None = None, reason: str = "", evidence: dict | None = None,
          fix_sql: str | None = None) -> dict:
    """Build a flag entry compatible with schema_advisor's advisory schema."""
    return {
        "rule": rule,
        "severity": severity,
        "title": title,
        "table": table,
        "column": column,
        "reason": reason,
        "fix_sql": fix_sql,
        "evidence": evidence or {},
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def apply_optimizations(
    schema: dict,
    dataframes: dict,
    name_map: dict,
    col_map: dict,
    relationships: list[dict],
    options: dict,
) -> tuple[list[dict], list[dict], bool]:
    """Run all enabled optimizations in order.

    Returns (decisions, flags, schema_was_mutated).
    `name_map` maps source table name -> normalized table name.
    `col_map` maps (source_table, source_col) -> normalized col name.
    """
    decisions: list[dict] = []
    flags: list[dict] = []
    mutated = False

    # Build normalized-side helpers
    norm_to_src_table = {v: k for k, v in name_map.items()}
    df_by_norm = {name_map[s]: dataframes.get(s) for s in name_map if s in dataframes}

    # Structural (order matters — downgrades can invalidate inlines, etc.)
    if mode := _active_mode(options, "mn_to_1n_downgrade"):
        d, f, m = _opt_mn_downgrade(schema, df_by_norm, col_map, norm_to_src_table, mode)
        decisions += d; flags += f; mutated = mutated or m

    if mode := _active_mode(options, "inline_lookup_tables"):
        d, f, m = _opt_inline_lookup(schema, mode)
        decisions += d; flags += f; mutated = mutated or m

    if mode := _active_mode(options, "merge_1_1_pairs"):
        d, f, m = _opt_merge_1to1(schema, df_by_norm, col_map, norm_to_src_table, mode)
        decisions += d; flags += f; mutated = mutated or m

    if _active_mode(options, "drop_orphan_tables"):
        flags += _opt_flag_orphan_tables(schema, df_by_norm)

    # Column-level
    if mode := _active_mode(options, "type_downsizing"):
        d, f, m = _opt_type_downsizing(schema, df_by_norm, col_map, norm_to_src_table, mode)
        decisions += d; flags += f; mutated = mutated or m

    if mode := _active_mode(options, "strict_nullability"):
        d, f, m = _opt_strict_nullability(schema, df_by_norm, col_map, norm_to_src_table, mode)
        decisions += d; flags += f; mutated = mutated or m

    if mode := _active_mode(options, "enum_discovery"):
        d, f, m = _opt_enum_discovery(schema, df_by_norm, col_map, norm_to_src_table, mode)
        decisions += d; flags += f; mutated = mutated or m

    if _active_mode(options, "dead_column_detection"):
        flags += _opt_flag_dead_columns(schema, df_by_norm, col_map, norm_to_src_table)

    # Indexes & FKs
    if mode := _active_mode(options, "collapse_redundant_indexes"):
        d, f, m = _opt_collapse_indexes(schema, mode)
        decisions += d; flags += f; mutated = mutated or m

    if mode := _active_mode(options, "missing_fk_indexes"):
        d, f, m = _opt_missing_fk_indexes(schema, mode)
        decisions += d; flags += f; mutated = mutated or m

    if mode := _active_mode(options, "implicit_fk_discovery"):
        d, f, m = _opt_implicit_fk(schema, df_by_norm, col_map, norm_to_src_table, mode)
        decisions += d; flags += f; mutated = mutated or m

    # Advanced / integrity (flag only)
    if _active_mode(options, "eav_to_jsonb"):
        flags += _opt_flag_eav(schema)
    if _active_mode(options, "vertical_split_fat_tables"):
        flags += _opt_flag_fat_tables(schema, df_by_norm, col_map, norm_to_src_table)
    if _active_mode(options, "time_series_partition_candidates"):
        flags += _opt_flag_time_series(schema, df_by_norm, col_map, norm_to_src_table)
    if _active_mode(options, "dangling_reference_detect"):
        flags += _opt_flag_dangling_fks(schema, df_by_norm, col_map, norm_to_src_table)
    if _active_mode(options, "soft_delete_ghosting"):
        flags += _opt_flag_soft_delete(schema, df_by_norm, col_map, norm_to_src_table)

    return decisions, flags, mutated


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _source_df_for(df_by_norm: dict, table_name: str):
    """Get dataframe for a normalized table name."""
    return df_by_norm.get(table_name)


def _source_col_name(col_map: dict, norm_to_src: dict, norm_table: str, norm_col: str) -> str | None:
    """Reverse lookup — find the source column name for a normalized one."""
    src_t = norm_to_src.get(norm_table)
    if src_t is None:
        return None
    for (st, sc), nc in col_map.items():
        if st == src_t and nc == norm_col:
            return sc
    return None


def _fks_by_table(schema: dict) -> dict[str, list[dict]]:
    """Return {table_name: [fk_constraint, ...]}."""
    out: dict[str, list[dict]] = {}
    for t in schema["tables"]:
        out[t["name"]] = [c for c in t.get("constraints", []) if c.get("type") == "fk"]
    return out


def _incoming_fks(schema: dict, target_table: str) -> list[tuple[str, dict]]:
    """Return [(source_table_name, fk_constraint), ...] targeting `target_table`."""
    out: list[tuple[str, dict]] = []
    for t in schema["tables"]:
        for c in t.get("constraints", []):
            if c.get("type") == "fk" and c.get("refTable") == target_table:
                out.append((t["name"], c))
    return out


# ---------------------------------------------------------------------------
# Structural optimizations
# ---------------------------------------------------------------------------

def _opt_mn_downgrade(schema, df_by_norm, col_map, norm_to_src, mode):
    """Detect junction tables whose data is actually 1:N and downgrade them."""
    decisions: list[dict] = []
    flags: list[dict] = []
    mutated = False

    fks_by_tbl = _fks_by_table(schema)
    for tbl in list(schema["tables"]):
        fks = fks_by_tbl.get(tbl["name"], [])
        if len(fks) != 2:
            continue
        # Junction heuristic: only PK + 2 FK cols (possibly plus timestamps)
        non_meta = [c for c in tbl["columns"]
                    if c["name"].lower() not in ("id", "created_at", "updated_at", "deleted_at")
                    and not c.get("isPrimaryKey")]
        fk_col_names = {c["columns"][0] for c in fks if c.get("columns")}
        extras = [c for c in non_meta if c["name"] not in fk_col_names]
        if len(extras) > 1:
            continue

        a, b = fks[0], fks[1]
        a_col = a["columns"][0]
        b_col = b["columns"][0]
        a_ref = a.get("refTable")
        b_ref = b.get("refTable")
        if not a_ref or not b_ref:
            continue

        df_junction = df_by_norm.get(tbl["name"])
        if df_junction is None:
            continue

        src_a_col = _source_col_name(col_map, norm_to_src, tbl["name"], a_col)
        src_b_col = _source_col_name(col_map, norm_to_src, tbl["name"], b_col)
        src_junction = norm_to_src.get(tbl["name"])
        if not (src_a_col and src_b_col and src_junction):
            continue

        # Cardinality: is a_col unique within the junction? Then each row in `a`
        # maps to at most one row in `b` → downgrade to 1:N on `a` side.
        try:
            a_unique = df_junction[src_a_col].is_unique
            b_unique = df_junction[src_b_col].is_unique
        except Exception:
            continue

        if not (a_unique or b_unique):
            continue

        # Decide which side to keep as 1:N
        keep_side, drop_side = (a, b) if a_unique else (b, a)
        keep_ref = keep_side.get("refTable")
        drop_ref = drop_side.get("refTable")
        evidence = {"junction": tbl["name"], "unique_side": keep_side["columns"][0],
                    "row_count": int(len(df_junction))}

        if mode == "flag":
            flags.append(_flag(
                "mn_to_1n_downgrade", "info",
                f"M:N junction '{tbl['name']}' is actually 1:N",
                table=tbl["name"], column=keep_side["columns"][0],
                reason=f"Column is unique in data — relationship to '{keep_ref}' is 1:1 per row",
                evidence=evidence,
            ))
            continue

        # Apply: add FK on `keep_ref` table pointing to `drop_ref`, drop junction
        keep_tbl = find_table(schema, keep_ref)
        drop_ref_tbl = find_table(schema, drop_ref)
        if not keep_tbl or not drop_ref_tbl:
            continue
        new_col_name = f"{drop_ref}_id"
        # Avoid collision
        if any(c["name"] == new_col_name for c in keep_tbl["columns"]):
            new_col_name = f"{drop_ref}_ref_id"
        # Find target PK type
        tgt_pk = next((c for c in drop_ref_tbl["columns"] if c.get("isPrimaryKey")), None)
        if not tgt_pk:
            continue
        keep_tbl["columns"].append({
            "name": new_col_name,
            "type": tgt_pk["type"],
            "nullable": True,
            "isPrimaryKey": False,
            "isUnique": False,
            "identity": None,
            "defaultValue": None,
            "checkExpression": None,
            "comment": None,
        })
        add_constraint(keep_tbl, {
            "type": "fk",
            "columns": [new_col_name],
            "refTable": drop_ref,
            "refColumns": [tgt_pk["name"]],
            "onDelete": "NO ACTION",
            "onUpdate": "NO ACTION",
            "name": generate_constraint_name(keep_ref, [new_col_name], "fk"),
        })
        add_index(keep_tbl, {
            "name": generate_index_name(keep_ref, [new_col_name]),
            "columns": [new_col_name],
            "type": "btree",
            "unique": False,
        })
        schema["tables"] = [t for t in schema["tables"] if t["name"] != tbl["name"]]
        mutated = True
        decisions.append({
            "kind": "mn_downgrade",
            "table": tbl["name"],
            "keep_table": keep_ref,
            "new_column": new_col_name,
            "drop_table_ref": drop_ref,
            "reason": f"Junction data shows 1:N cardinality — replaced with direct FK",
        })

    return decisions, flags, mutated


def _opt_inline_lookup(schema, mode):
    """Inline thin lookup tables (id+name, single inbound FK) into their consumer."""
    decisions: list[dict] = []
    flags: list[dict] = []
    mutated = False

    for tbl in list(schema["tables"]):
        cols = tbl.get("columns", [])
        non_pk = [c for c in cols if not c.get("isPrimaryKey")]
        if len(cols) > LOOKUP_TABLE_MAX_COLS or len(non_pk) != 1:
            continue
        label_col = non_pk[0]
        if label_col.get("name", "").lower() not in ("name", "label", "title", "value", "description"):
            continue
        incoming = _incoming_fks(schema, tbl["name"])
        if len(incoming) != 1:
            continue
        # Don't inline if this lookup has outgoing FKs
        has_outgoing = any(c.get("type") == "fk" for c in tbl.get("constraints", []))
        if has_outgoing:
            continue

        consumer_name, fk = incoming[0]
        fk_col_name = fk["columns"][0]
        consumer = find_table(schema, consumer_name)
        if not consumer:
            continue

        evidence = {"lookup_table": tbl["name"], "consumer": consumer_name,
                    "fk_column": fk_col_name, "inline_as": f"{tbl['name']}_{label_col['name']}"}

        if mode == "flag":
            flags.append(_flag(
                "inline_lookup_tables", "info",
                f"Lookup table '{tbl['name']}' could be inlined",
                table=tbl["name"], reason=f"Only column '{label_col['name']}' is used by '{consumer_name}'",
                evidence=evidence,
            ))
            continue

        # Apply: add column to consumer, remove FK+index referencing lookup, drop lookup
        new_col_name = f"{tbl['name']}_{label_col['name']}"
        if any(c["name"] == new_col_name for c in consumer["columns"]):
            new_col_name = new_col_name + "_val"
        consumer["columns"].append({
            "name": new_col_name,
            "type": label_col["type"],
            "nullable": True,
            "isPrimaryKey": False,
            "isUnique": False,
            "identity": None,
            "defaultValue": None,
            "checkExpression": None,
            "comment": None,
        })
        # Remove the FK constraint and its index, then drop the FK column
        consumer["constraints"] = [c for c in consumer.get("constraints", [])
                                   if not (c.get("type") == "fk" and c.get("refTable") == tbl["name"])]
        consumer["indexes"] = [i for i in consumer.get("indexes", [])
                               if fk_col_name not in i.get("columns", [])]
        consumer["columns"] = [c for c in consumer["columns"] if c["name"] != fk_col_name]
        schema["tables"] = [t for t in schema["tables"] if t["name"] != tbl["name"]]
        mutated = True
        decisions.append({
            "kind": "inline_lookup",
            "table": tbl["name"],
            "inlined_into": consumer_name,
            "column": new_col_name,
            "dropped_fk_column": fk_col_name,
            "reason": f"Thin lookup with single consumer — inlined as '{new_col_name}'",
        })

    return decisions, flags, mutated


def _opt_merge_1to1(schema, df_by_norm, col_map, norm_to_src, mode):
    """Merge tables whose PK values match 1:1 in data."""
    decisions: list[dict] = []
    flags: list[dict] = []
    mutated = False

    # Find pairs connected by FK where both sides have matching unique PKs
    seen_pairs: set[tuple[str, str]] = set()
    for tbl in list(schema["tables"]):
        for fk in [c for c in tbl.get("constraints", []) if c.get("type") == "fk"]:
            ref = fk.get("refTable")
            if not ref or (tbl["name"], ref) in seen_pairs or (ref, tbl["name"]) in seen_pairs:
                continue
            seen_pairs.add((tbl["name"], ref))
            ref_tbl = find_table(schema, ref)
            if not ref_tbl:
                continue
            # FK column must be unique (or the PK itself) for 1:1
            fk_col = fk["columns"][0]
            src_table = norm_to_src.get(tbl["name"])
            src_ref = norm_to_src.get(ref)
            if not (src_table and src_ref):
                continue
            df_src = df_by_norm.get(tbl["name"])
            df_ref = df_by_norm.get(ref)
            if df_src is None or df_ref is None:
                continue
            src_fk = _source_col_name(col_map, norm_to_src, tbl["name"], fk_col)
            src_ref_pk_col = fk.get("refColumns", [None])[0]
            src_ref_pk = _source_col_name(col_map, norm_to_src, ref, src_ref_pk_col) if src_ref_pk_col else None
            if not (src_fk and src_ref_pk):
                continue
            try:
                fk_vals = set(df_src[src_fk].dropna().unique())
                ref_vals = set(df_ref[src_ref_pk].dropna().unique())
            except Exception:
                continue
            if not fk_vals or not ref_vals:
                continue
            # 1:1 means: every FK value is unique AND every ref PK has exactly one child
            try:
                fk_unique = df_src[src_fk].dropna().is_unique
            except Exception:
                fk_unique = False
            if not fk_unique:
                continue
            if fk_vals != ref_vals:
                continue

            evidence = {"pair": [tbl["name"], ref], "shared_keys": len(fk_vals)}
            if mode == "flag":
                flags.append(_flag(
                    "merge_1_1_pairs", "warning",
                    f"Tables '{tbl['name']}' and '{ref}' appear 1:1",
                    table=tbl["name"], reason=f"All {len(fk_vals)} PK values match in both tables",
                    evidence=evidence, fix_sql=f"-- Consider merging {tbl['name']} into {ref}",
                ))
            else:
                # Apply: merge tbl's non-FK columns into ref
                ref_col_names = {c["name"] for c in ref_tbl["columns"]}
                for c in tbl["columns"]:
                    if c["name"] == fk_col or c.get("isPrimaryKey") or c["name"] in ref_col_names:
                        continue
                    ref_tbl["columns"].append(dict(c))
                schema["tables"] = [t for t in schema["tables"] if t["name"] != tbl["name"]]
                mutated = True
                decisions.append({
                    "kind": "merge_1_1",
                    "table": tbl["name"],
                    "merged_into": ref,
                    "reason": f"Data shows 1:1 match on {len(fk_vals)} keys — tables merged",
                })
                break  # tbl is gone, move on
    return decisions, flags, mutated


def _opt_flag_orphan_tables(schema, df_by_norm):
    """Flag tables with no incoming or outgoing FKs."""
    flags: list[dict] = []
    fks_by_tbl = _fks_by_table(schema)
    for tbl in schema["tables"]:
        outgoing = len(fks_by_tbl.get(tbl["name"], []))
        incoming = len(_incoming_fks(schema, tbl["name"]))
        if outgoing == 0 and incoming == 0:
            df = df_by_norm.get(tbl["name"])
            row_count = int(len(df)) if df is not None else None
            flags.append(_flag(
                "drop_orphan_tables", "warning",
                f"Orphan table: '{tbl['name']}'",
                table=tbl["name"],
                reason="No incoming or outgoing foreign keys — possibly unused",
                evidence={"column_count": len(tbl.get("columns", [])), "row_count": row_count},
            ))
    return flags


# ---------------------------------------------------------------------------
# Column-level optimizations
# ---------------------------------------------------------------------------

def _opt_type_downsizing(schema, df_by_norm, col_map, norm_to_src, mode):
    """Shrink oversized int/varchar types to fit observed data."""
    decisions: list[dict] = []
    flags: list[dict] = []
    mutated = False

    for tbl in schema["tables"]:
        df = df_by_norm.get(tbl["name"])
        if df is None:
            continue
        for col in tbl["columns"]:
            src_name = _source_col_name(col_map, norm_to_src, tbl["name"], col["name"])
            if not src_name or src_name not in df.columns:
                continue
            new_type = _downsize_type(col, df[src_name])
            if new_type is None or new_type == col["type"]:
                continue
            evidence = {"from": col["type"], "to": new_type}
            if mode == "flag":
                flags.append(_flag(
                    "type_downsizing", "info",
                    f"Column '{tbl['name']}.{col['name']}' oversized",
                    table=tbl["name"], column=col["name"],
                    reason=f"Actual data fits in {new_type}", evidence=evidence,
                ))
            else:
                old_type = col["type"]
                col["type"] = new_type
                mutated = True
                decisions.append({
                    "kind": "type_downsize", "table": tbl["name"], "column": col["name"],
                    "from_type": old_type, "to_type": new_type,
                    "reason": f"Downsized from {old_type} to fit actual data",
                })
    return decisions, flags, mutated


def _downsize_type(col: dict, series) -> str | None:
    """Return a smaller PG type if the data fits, else None."""
    current = (col.get("type") or "").lower()
    # Integer types
    if current in ("bigint", "integer", "int"):
        try:
            non_null = series.dropna()
            if non_null.empty:
                return None
            max_v = int(abs(non_null.max()))
            min_v = int(non_null.min())
        except Exception:
            return None
        if min_v >= -32768 and max_v <= 32767 and current != "smallint":
            return "smallint"
        if min_v >= -2147483648 and max_v <= 2147483647 and current == "bigint":
            return "integer"
        return None
    # VARCHAR / text
    if current.startswith("varchar") or current == "text":
        try:
            max_len = int(series.dropna().astype(str).str.len().max() or 0)
        except Exception:
            return None
        if max_len == 0:
            return None
        target_len = max(4, int(max_len * DOWNSIZE_SAFETY))
        # Extract current length
        m = re.match(r'varchar\((\d+)\)', current)
        cur_len = int(m.group(1)) if m else 10000
        if target_len < cur_len:
            return f"varchar({target_len})"
    return None


def _opt_strict_nullability(schema, df_by_norm, col_map, norm_to_src, mode):
    """Set NOT NULL when data has zero nulls."""
    decisions: list[dict] = []
    flags: list[dict] = []
    mutated = False

    for tbl in schema["tables"]:
        df = df_by_norm.get(tbl["name"])
        if df is None or len(df) == 0:
            continue
        for col in tbl["columns"]:
            if not col.get("nullable"):
                continue  # already NOT NULL
            if col.get("isPrimaryKey"):
                continue
            src_name = _source_col_name(col_map, norm_to_src, tbl["name"], col["name"])
            if not src_name or src_name not in df.columns:
                continue
            try:
                has_null = int(df[src_name].isna().sum()) > 0
            except Exception:
                continue
            if has_null:
                continue
            evidence = {"row_count": int(len(df)), "null_count": 0}
            if mode == "flag":
                flags.append(_flag(
                    "strict_nullability", "info",
                    f"Column '{tbl['name']}.{col['name']}' has no nulls",
                    table=tbl["name"], column=col["name"],
                    reason="Could be NOT NULL", evidence=evidence,
                ))
            else:
                col["nullable"] = False
                mutated = True
                decisions.append({
                    "kind": "strict_not_null", "table": tbl["name"], "column": col["name"],
                    "reason": f"No nulls observed in {len(df)} rows",
                })
    return decisions, flags, mutated


def _opt_enum_discovery(schema, df_by_norm, col_map, norm_to_src, mode):
    """Flag low-cardinality text columns as ENUM candidates.

    The main rebuild already auto-promotes ENUMs when the option was implicit.
    This option exposes that decision under a user-controlled flag and, in
    flag mode, reports the candidate without creating the enum.
    """
    decisions: list[dict] = []
    flags: list[dict] = []
    mutated = False

    for tbl in schema["tables"]:
        df = df_by_norm.get(tbl["name"])
        if df is None:
            continue
        for col in tbl["columns"]:
            if col.get("isPrimaryKey"):
                continue
            ctype = (col.get("type") or "").lower()
            if not (ctype == "text" or ctype.startswith("varchar")):
                continue
            src_name = _source_col_name(col_map, norm_to_src, tbl["name"], col["name"])
            if not src_name or src_name not in df.columns:
                continue
            try:
                total = int(df[src_name].count())
                unique_vals = df[src_name].dropna().unique()
            except Exception:
                continue
            unique = len(unique_vals)
            if total < ENUM_MIN_TOTAL or unique == 0 or unique > ENUM_MAX_UNIQUE or unique >= total:
                continue
            values = sorted(str(v) for v in unique_vals)
            evidence = {"distinct": unique, "total": total, "values": values[:10]}
            if mode == "flag":
                flags.append(_flag(
                    "enum_discovery", "info",
                    f"ENUM candidate: '{tbl['name']}.{col['name']}'",
                    table=tbl["name"], column=col["name"],
                    reason=f"{unique} distinct values in {total} rows", evidence=evidence,
                ))
            else:
                # The main pipeline may have already created this enum; skip if exists
                enum_name = f"{tbl['name']}_{col['name']}_enum"[:63]
                if any(e["name"] == enum_name for e in schema.get("enums", [])):
                    continue
                schema.setdefault("enums", []).append({"name": enum_name, "values": values})
                col["type"] = enum_name
                mutated = True
                decisions.append({
                    "kind": "enum_discover", "table": tbl["name"], "column": col["name"],
                    "enum_name": enum_name, "values": values,
                    "reason": f"{unique} distinct values promoted to ENUM",
                })
    return decisions, flags, mutated


def _opt_flag_dead_columns(schema, df_by_norm, col_map, norm_to_src):
    """Flag columns that are 100% NULL or 100% a single constant value."""
    flags: list[dict] = []
    for tbl in schema["tables"]:
        df = df_by_norm.get(tbl["name"])
        if df is None or len(df) < DEAD_COLUMN_MIN_ROWS:
            continue
        for col in tbl["columns"]:
            if col.get("isPrimaryKey"):
                continue
            src_name = _source_col_name(col_map, norm_to_src, tbl["name"], col["name"])
            if not src_name or src_name not in df.columns:
                continue
            try:
                non_null = int(df[src_name].count())
                if non_null == 0:
                    flags.append(_flag(
                        "dead_column_detection", "warning",
                        f"All-NULL column: '{tbl['name']}.{col['name']}'",
                        table=tbl["name"], column=col["name"],
                        reason=f"100% NULL across {len(df)} rows",
                        evidence={"row_count": int(len(df))},
                    ))
                    continue
                distinct = int(df[src_name].nunique(dropna=True))
                if distinct == 1 and non_null == len(df):
                    val = df[src_name].dropna().iloc[0]
                    flags.append(_flag(
                        "dead_column_detection", "warning",
                        f"Constant column: '{tbl['name']}.{col['name']}'",
                        table=tbl["name"], column=col["name"],
                        reason=f"Single constant value ({val!r}) across {len(df)} rows",
                        evidence={"row_count": int(len(df)), "constant_value": str(val)[:50]},
                    ))
            except Exception:
                continue
    return flags


# ---------------------------------------------------------------------------
# Index & FK optimizations
# ---------------------------------------------------------------------------

def _opt_collapse_indexes(schema, mode):
    """Drop indexes whose columns are a prefix of another index's columns."""
    decisions: list[dict] = []
    flags: list[dict] = []
    mutated = False

    for tbl in schema["tables"]:
        indexes = tbl.get("indexes", [])
        to_drop: list[str] = []
        for i, a in enumerate(indexes):
            a_cols = a.get("columns", [])
            for j, b in enumerate(indexes):
                if i == j or b["name"] in to_drop:
                    continue
                b_cols = b.get("columns", [])
                # a is redundant if a_cols is a strict prefix of b_cols
                if len(a_cols) < len(b_cols) and a_cols == b_cols[:len(a_cols)] \
                        and a.get("type") == b.get("type") \
                        and not a.get("unique", False):
                    to_drop.append(a["name"])
                    break
        for idx_name in to_drop:
            covered_by = next((i["name"] for i in indexes
                               if i["name"] != idx_name), None)
            evidence = {"dropped": idx_name, "covered_by": covered_by}
            if mode == "flag":
                flags.append(_flag(
                    "collapse_redundant_indexes", "info",
                    f"Redundant index: '{idx_name}'",
                    table=tbl["name"], reason=f"Covered by prefix of '{covered_by}'",
                    evidence=evidence,
                ))
            else:
                remove_index(tbl, idx_name)
                mutated = True
                decisions.append({
                    "kind": "drop_redundant_index", "table": tbl["name"],
                    "index": idx_name, "covered_by": covered_by,
                    "reason": f"Prefix of index '{covered_by}'",
                })
    return decisions, flags, mutated


def _opt_missing_fk_indexes(schema, mode):
    """Ensure every FK column has an index."""
    decisions: list[dict] = []
    flags: list[dict] = []
    mutated = False

    for tbl in schema["tables"]:
        existing_idx = {tuple(i.get("columns", [])) for i in tbl.get("indexes", [])}
        for c in tbl.get("constraints", []):
            if c.get("type") != "fk":
                continue
            cols = tuple(c.get("columns", []))
            if not cols or cols in existing_idx:
                continue
            evidence = {"columns": list(cols), "fk": c.get("name")}
            if mode == "flag":
                flags.append(_flag(
                    "missing_fk_indexes", "warning",
                    f"FK without index: '{tbl['name']}.{cols[0]}'",
                    table=tbl["name"], column=cols[0],
                    reason="FK columns should be indexed", evidence=evidence,
                ))
            else:
                idx_name = generate_index_name(tbl["name"], list(cols))
                add_index(tbl, {
                    "name": idx_name, "columns": list(cols),
                    "type": "btree", "unique": False,
                })
                existing_idx.add(cols)
                mutated = True
                decisions.append({
                    "kind": "add_fk_index", "table": tbl["name"], "index": idx_name,
                    "columns": list(cols),
                    "reason": "Added missing index on FK column",
                })
    return decisions, flags, mutated


def _opt_implicit_fk(schema, df_by_norm, col_map, norm_to_src, mode):
    """Discover *_id columns whose data overlaps another table's PK values."""
    decisions: list[dict] = []
    flags: list[dict] = []
    mutated = False

    # Build PK value sets per table
    pk_values: dict[str, tuple[str, set]] = {}
    for tbl in schema["tables"]:
        pk = next((c for c in tbl["columns"] if c.get("isPrimaryKey")), None)
        df = df_by_norm.get(tbl["name"])
        if not pk or df is None:
            continue
        src_col = _source_col_name(col_map, norm_to_src, tbl["name"], pk["name"])
        if not src_col or src_col not in df.columns:
            continue
        try:
            pk_values[tbl["name"]] = (pk["name"], set(df[src_col].dropna().unique()))
        except Exception:
            continue

    for tbl in schema["tables"]:
        existing_fk_cols = {c["columns"][0] for c in tbl.get("constraints", [])
                             if c.get("type") == "fk" and c.get("columns")}
        df = df_by_norm.get(tbl["name"])
        if df is None:
            continue
        for col in tbl["columns"]:
            cname = col["name"]
            if cname in existing_fk_cols or col.get("isPrimaryKey"):
                continue
            if not _FK_SUFFIX.search(cname):
                continue
            src_col = _source_col_name(col_map, norm_to_src, tbl["name"], cname)
            if not src_col or src_col not in df.columns:
                continue
            try:
                child_vals = set(df[src_col].dropna().unique())
            except Exception:
                continue
            if not child_vals:
                continue
            # Try each candidate table
            best = None
            for cand_tbl, (cand_pk, cand_vals) in pk_values.items():
                if cand_tbl == tbl["name"]:
                    continue
                overlap = len(child_vals & cand_vals) / max(len(child_vals), 1)
                if overlap >= IMPLICIT_FK_MIN_OVERLAP and (best is None or overlap > best[2]):
                    best = (cand_tbl, cand_pk, overlap)
            if not best:
                continue
            cand_tbl, cand_pk, overlap = best
            evidence = {"target_table": cand_tbl, "target_column": cand_pk,
                        "overlap_ratio": round(overlap, 3)}
            if mode == "flag":
                flags.append(_flag(
                    "implicit_fk_discovery", "info",
                    f"Implicit FK: '{tbl['name']}.{cname}' → '{cand_tbl}.{cand_pk}'",
                    table=tbl["name"], column=cname,
                    reason=f"{overlap*100:.0f}% of values exist in {cand_tbl}.{cand_pk}",
                    evidence=evidence,
                ))
            else:
                add_constraint(tbl, {
                    "type": "fk", "columns": [cname], "refTable": cand_tbl,
                    "refColumns": [cand_pk], "onDelete": "NO ACTION",
                    "onUpdate": "NO ACTION",
                    "name": generate_constraint_name(tbl["name"], [cname], "fk"),
                })
                add_index(tbl, {
                    "name": generate_index_name(tbl["name"], [cname]),
                    "columns": [cname], "type": "btree", "unique": False,
                })
                mutated = True
                decisions.append({
                    "kind": "implicit_fk", "table": tbl["name"], "column": cname,
                    "target_table": cand_tbl, "target_column": cand_pk,
                    "overlap": round(overlap, 3),
                    "reason": f"Data overlap {overlap*100:.0f}% with {cand_tbl}.{cand_pk}",
                })
    return decisions, flags, mutated


# ---------------------------------------------------------------------------
# Flag-only advanced / integrity detectors
# ---------------------------------------------------------------------------

def _opt_flag_eav(schema):
    """Flag tables matching the EAV anti-pattern."""
    flags: list[dict] = []
    eav_attr_names = {"attribute_name", "attr_name", "key", "attribute", "property"}
    eav_val_names = {"attribute_value", "attr_value", "value", "val"}
    for tbl in schema["tables"]:
        col_names = {c["name"].lower() for c in tbl["columns"]}
        has_attr = bool(col_names & eav_attr_names)
        has_val = bool(col_names & eav_val_names)
        has_entity_fk = any(c.get("type") == "fk" for c in tbl.get("constraints", []))
        if has_attr and has_val and has_entity_fk:
            flags.append(_flag(
                "eav_to_jsonb", "warning",
                f"EAV pattern detected: '{tbl['name']}'",
                table=tbl["name"],
                reason="Table matches (entity_id, attribute_name, attribute_value) shape",
                evidence={"columns": sorted(col_names)},
                fix_sql=f"-- Consider collapsing {tbl['name']} into a JSONB column on the parent",
            ))
    return flags


def _opt_flag_fat_tables(schema, df_by_norm, col_map, norm_to_src):
    """Flag tables with many columns where most are sparsely populated."""
    flags: list[dict] = []
    for tbl in schema["tables"]:
        cols = tbl.get("columns", [])
        if len(cols) < FAT_TABLE_COL_THRESHOLD:
            continue
        df = df_by_norm.get(tbl["name"])
        if df is None or len(df) == 0:
            continue
        sparse = 0
        total_rows = len(df)
        for col in cols:
            src_name = _source_col_name(col_map, norm_to_src, tbl["name"], col["name"])
            if not src_name or src_name not in df.columns:
                continue
            try:
                null_ratio = 1.0 - (int(df[src_name].count()) / total_rows)
            except Exception:
                continue
            if null_ratio > FAT_TABLE_SPARSE_RATIO:
                sparse += 1
        if sparse >= FAT_TABLE_SPARSE_COL_COUNT:
            flags.append(_flag(
                "vertical_split_fat_tables", "warning",
                f"Fat sparse table: '{tbl['name']}'",
                table=tbl["name"],
                reason=f"{len(cols)} columns, {sparse} are >{FAT_TABLE_SPARSE_RATIO*100:.0f}% NULL",
                evidence={"column_count": len(cols), "sparse_count": sparse},
            ))
    return flags


def _opt_flag_time_series(schema, df_by_norm, col_map, norm_to_src):
    """Flag tables suitable for date-based partitioning."""
    flags: list[dict] = []
    for tbl in schema["tables"]:
        col_names = {c["name"].lower() for c in tbl["columns"]}
        if "created_at" not in col_names or "updated_at" in col_names:
            continue
        df = df_by_norm.get(tbl["name"])
        if df is None or len(df) < TIME_SERIES_MIN_ROWS:
            continue
        has_seq_pk = any(c.get("isPrimaryKey") and (c.get("identity") or "") in ("ALWAYS", "BY DEFAULT")
                         for c in tbl["columns"])
        if not has_seq_pk:
            continue
        flags.append(_flag(
            "time_series_partition_candidates", "info",
            f"Time-series candidate: '{tbl['name']}'",
            table=tbl["name"],
            reason=f"Append-only pattern: sequential PK + created_at, no updated_at, {len(df)} rows",
            evidence={"row_count": int(len(df))},
            fix_sql=f"-- Consider PARTITION BY RANGE (created_at) on {tbl['name']}",
        ))
    return flags


def _opt_flag_dangling_fks(schema, df_by_norm, col_map, norm_to_src):
    """Flag FK columns with values not present in the parent's PK data."""
    flags: list[dict] = []
    # Cache parent PK value sets
    pk_cache: dict[str, set] = {}
    for tbl in schema["tables"]:
        df = df_by_norm.get(tbl["name"])
        if df is None:
            continue
        pk = next((c for c in tbl["columns"] if c.get("isPrimaryKey")), None)
        if not pk:
            continue
        src_pk = _source_col_name(col_map, norm_to_src, tbl["name"], pk["name"])
        if not src_pk or src_pk not in df.columns:
            continue
        try:
            pk_cache[tbl["name"]] = set(df[src_pk].dropna().unique())
        except Exception:
            continue

    for tbl in schema["tables"]:
        df = df_by_norm.get(tbl["name"])
        if df is None:
            continue
        for c in tbl.get("constraints", []):
            if c.get("type") != "fk":
                continue
            ref = c.get("refTable")
            if ref not in pk_cache:
                continue
            fk_col = c["columns"][0]
            src_col = _source_col_name(col_map, norm_to_src, tbl["name"], fk_col)
            if not src_col or src_col not in df.columns:
                continue
            try:
                child_vals = set(df[src_col].dropna().unique())
            except Exception:
                continue
            dangling = child_vals - pk_cache[ref]
            if not dangling:
                continue
            sample = sorted(str(v) for v in list(dangling)[:5])
            flags.append(_flag(
                "dangling_reference_detect", "error",
                f"Dangling FK: '{tbl['name']}.{fk_col}'",
                table=tbl["name"], column=fk_col,
                reason=f"{len(dangling)} values not present in {ref}",
                evidence={"dangling_count": len(dangling), "sample": sample, "target": ref},
            ))
    return flags


def _opt_flag_soft_delete(schema, df_by_norm, col_map, norm_to_src):
    """Flag soft-deleted rows that break unique constraints or bloat junctions."""
    flags: list[dict] = []
    for tbl in schema["tables"]:
        has_deleted_at = any(c["name"].lower() == "deleted_at" for c in tbl["columns"])
        if not has_deleted_at:
            continue
        df = df_by_norm.get(tbl["name"])
        if df is None:
            continue
        src_del = _source_col_name(col_map, norm_to_src, tbl["name"], "deleted_at")
        if not src_del or src_del not in df.columns:
            continue
        try:
            deleted_rows = int(df[src_del].notna().sum())
        except Exception:
            continue
        if deleted_rows == 0:
            continue
        # Check if a unique constraint has duplicates when counting soft-deleted
        unique_cols = [c["columns"] for c in tbl.get("constraints", [])
                        if c.get("type") == "unique"]
        issues = []
        for uc in unique_cols:
            src_uc = [_source_col_name(col_map, norm_to_src, tbl["name"], n) for n in uc]
            if not all(src_uc) or not all(c in df.columns for c in src_uc):
                continue
            try:
                dup_count = int(df.duplicated(subset=src_uc).sum())
            except Exception:
                continue
            if dup_count > 0:
                issues.append({"unique_columns": uc, "duplicate_count": dup_count})
        flags.append(_flag(
            "soft_delete_ghosting", "warning",
            f"Soft-deleted rows in '{tbl['name']}'",
            table=tbl["name"],
            reason=f"{deleted_rows} soft-deleted rows; consider hard-drop before rebuild",
            evidence={"deleted_count": deleted_rows, "unique_conflicts": issues},
        ))
    return flags
