"""Schema advisor — deterministic rules that suggest DB improvements.

Pure functions over the builder schema dict. No HTTP, no side effects.
Each rule returns a list of advisory dicts. The route layer concatenates
them and returns a single report.

Advisory shape:
    {
        "rule":     "missing_fk_index",
        "severity": "error" | "warning" | "info",
        "title":    "Missing index on foreign key",
        "table":    "orders",
        "column":   "customer_id" | None,
        "reason":   "Human-readable why",
        "fix_ddl":  "CREATE INDEX ..." | None,
        "evidence": { ... } | None,
    }
"""

from __future__ import annotations

import re

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

VARCHAR_WIDE_THRESHOLD = 500
_VARCHAR_RE = re.compile(r"^\s*varchar\s*\(\s*(\d+)\s*\)\s*$", re.IGNORECASE)
_AUDIT_NAMES = {"created_at", "updated_at"}


def _quote(name: str) -> str:
    """Safely quote a PG identifier (mirrors ddl_generator.quote_identifier)."""
    if '"' in name:
        return f'"{name.replace(chr(34), "")}"'
    return f'"{name}"'


def _advisory(
    rule: str,
    severity: str,
    title: str,
    reason: str,
    table: str | None = None,
    column: str | None = None,
    fix_ddl: str | None = None,
    evidence: dict | None = None,
) -> dict:
    return {
        "rule": rule,
        "severity": severity,
        "title": title,
        "table": table,
        "column": column,
        "reason": reason,
        "fix_ddl": fix_ddl,
        "evidence": evidence,
    }


def _fk_constraints(table: dict) -> list[dict]:
    return [c for c in table.get("constraints", []) if c.get("type") == "fk"]


def _pk_constraint(table: dict) -> dict | None:
    for c in table.get("constraints", []):
        if c.get("type") == "pk":
            return c
    return None


def _has_pk_column(table: dict) -> bool:
    return any(c.get("isPrimaryKey") for c in table.get("columns", []))


def _find_column(table: dict, name: str) -> dict | None:
    for c in table.get("columns", []):
        if c.get("name") == name:
            return c
    return None


def _find_table(schema: dict, name: str) -> dict | None:
    for t in schema.get("tables", []):
        if t.get("name") == name:
            return t
    return None


def _index_covers(index: dict, columns: list[str]) -> bool:
    """True if the index's leading columns match the target list exactly."""
    idx_cols = index.get("columns", [])
    if len(idx_cols) != len(columns):
        return False
    return all(a == b for a, b in zip(idx_cols, columns))


def _index_starts_with(index: dict, columns: list[str]) -> bool:
    """True if the index's leading columns begin with the target list."""
    idx_cols = index.get("columns", [])
    if len(idx_cols) < len(columns):
        return False
    return all(a == b for a, b in zip(idx_cols, columns))


# ---------- Rules ----------


def rule_missing_fk_index(schema: dict) -> list[dict]:
    """FK columns without an index slow joins and cascades."""
    out: list[dict] = []
    for table in schema.get("tables", []):
        tname = table.get("name", "")
        indexes = table.get("indexes", [])
        for fk in _fk_constraints(table):
            fk_cols = fk.get("columns", [])
            if not fk_cols:
                continue
            # PK on the same leading columns also serves as an index
            pk = _pk_constraint(table)
            if pk and _index_starts_with({"columns": pk.get("columns", [])}, fk_cols):
                continue
            if any(_index_starts_with(idx, fk_cols) for idx in indexes):
                continue
            # Also treat a UNIQUE constraint on these columns as index coverage
            unique_covered = any(
                c.get("type") == "unique" and _index_starts_with({"columns": c.get("columns", [])}, fk_cols)
                for c in table.get("constraints", [])
            )
            if unique_covered:
                continue

            idx_name = f"{tname}_{'_'.join(fk_cols)}_idx"[:63]
            cols_sql = ", ".join(_quote(c) for c in fk_cols)
            fix_ddl = f"CREATE INDEX {_quote(idx_name)} ON {_quote(tname)} ({cols_sql});"
            ref = f"{fk.get('refTable', '?')}({', '.join(fk.get('refColumns', []))})"
            out.append(_advisory(
                rule="missing_fk_index",
                severity=SEVERITY_WARNING,
                title="Missing index on foreign key",
                reason=(
                    f"FK column(s) {fk_cols} reference {ref} but have no "
                    "supporting index. Joins and cascading deletes will scan "
                    "the full child table."
                ),
                table=tname,
                column=fk_cols[0] if len(fk_cols) == 1 else None,
                fix_ddl=fix_ddl,
                evidence={"fk_columns": fk_cols, "references": ref},
            ))
    return out


def rule_missing_primary_key(schema: dict) -> list[dict]:
    """Every table should have a primary key."""
    out: list[dict] = []
    for table in schema.get("tables", []):
        tname = table.get("name", "")
        if _pk_constraint(table) is None and not _has_pk_column(table):
            out.append(_advisory(
                rule="missing_primary_key",
                severity=SEVERITY_WARNING,
                title="Table has no primary key",
                reason=(
                    "Tables without a primary key cannot be replicated, cannot "
                    "be referenced by foreign keys, and make updates by row "
                    "identity unreliable."
                ),
                table=tname,
                evidence={"columns": [c.get("name") for c in table.get("columns", [])]},
            ))
    return out


def rule_wide_varchar(schema: dict) -> list[dict]:
    """VARCHAR(N) where N > 500 should usually be TEXT."""
    out: list[dict] = []
    for table in schema.get("tables", []):
        tname = table.get("name", "")
        for col in table.get("columns", []):
            ctype = str(col.get("type", ""))
            m = _VARCHAR_RE.match(ctype)
            if not m:
                continue
            n = int(m.group(1))
            if n <= VARCHAR_WIDE_THRESHOLD:
                continue
            out.append(_advisory(
                rule="wide_varchar",
                severity=SEVERITY_INFO,
                title="Wide VARCHAR — consider TEXT",
                reason=(
                    f"VARCHAR({n}) has no storage advantage over TEXT in "
                    "PostgreSQL. TEXT is idiomatic for long/unbounded strings."
                ),
                table=tname,
                column=col.get("name"),
                fix_ddl=(
                    f'ALTER TABLE {_quote(tname)} '
                    f'ALTER COLUMN {_quote(col.get("name", ""))} TYPE text;'
                ),
                evidence={"current_type": ctype, "length": n},
            ))
    return out


def rule_fk_pk_type_drift(schema: dict) -> list[dict]:
    """FK column type should match the referenced PK column type."""
    out: list[dict] = []
    for table in schema.get("tables", []):
        tname = table.get("name", "")
        for fk in _fk_constraints(table):
            ref_table = _find_table(schema, fk.get("refTable", ""))
            if ref_table is None:
                continue
            fk_cols = fk.get("columns", [])
            ref_cols = fk.get("refColumns", [])
            if len(fk_cols) != len(ref_cols):
                continue
            for fk_col_name, ref_col_name in zip(fk_cols, ref_cols):
                fk_col = _find_column(table, fk_col_name)
                ref_col = _find_column(ref_table, ref_col_name)
                if not fk_col or not ref_col:
                    continue
                t_fk = str(fk_col.get("type", "")).strip().lower()
                t_ref = str(ref_col.get("type", "")).strip().lower()
                if not t_fk or not t_ref or t_fk == t_ref:
                    continue
                out.append(_advisory(
                    rule="fk_pk_type_drift",
                    severity=SEVERITY_WARNING,
                    title="FK and PK types differ",
                    reason=(
                        f"FK {tname}.{fk_col_name} ({t_fk}) references "
                        f"{ref_table.get('name')}.{ref_col_name} ({t_ref}). "
                        "Differing types force implicit casts on every join "
                        "and can defeat index use."
                    ),
                    table=tname,
                    column=fk_col_name,
                    fix_ddl=(
                        f'ALTER TABLE {_quote(tname)} '
                        f'ALTER COLUMN {_quote(fk_col_name)} TYPE {t_ref};'
                    ),
                    evidence={
                        "fk_type": t_fk,
                        "pk_type": t_ref,
                        "references": f"{ref_table.get('name')}.{ref_col_name}",
                    },
                ))
    return out


def rule_missing_audit_columns(schema: dict) -> list[dict]:
    """Flag tables with no created_at/updated_at (informational only)."""
    out: list[dict] = []
    for table in schema.get("tables", []):
        tname = table.get("name", "")
        col_names = {c.get("name", "").lower() for c in table.get("columns", [])}
        missing = sorted(_AUDIT_NAMES - col_names)
        if not missing or len(missing) < 2:
            # Only flag when BOTH are missing, to reduce noise
            continue
        out.append(_advisory(
            rule="missing_audit_columns",
            severity=SEVERITY_INFO,
            title="No audit timestamp columns",
            reason=(
                f"Table has no {', '.join(missing)} columns. Audit timestamps "
                "are useful for debugging, sync, and soft-ordering."
            ),
            table=tname,
            fix_ddl=(
                f'ALTER TABLE {_quote(tname)} '
                f'ADD COLUMN "created_at" timestamptz NOT NULL DEFAULT NOW(), '
                f'ADD COLUMN "updated_at" timestamptz;'
            ),
            evidence={"missing": missing},
        ))
    return out


def rule_nullable_fk(schema: dict) -> list[dict]:
    """Nullable FK columns may be intentional (optional relation) — info only."""
    out: list[dict] = []
    for table in schema.get("tables", []):
        tname = table.get("name", "")
        for fk in _fk_constraints(table):
            for col_name in fk.get("columns", []):
                col = _find_column(table, col_name)
                if not col:
                    continue
                if col.get("nullable", True):
                    out.append(_advisory(
                        rule="nullable_fk",
                        severity=SEVERITY_INFO,
                        title="Nullable foreign key",
                        reason=(
                            "FK column is nullable. This is fine for optional "
                            "relations; add NOT NULL if the relation is "
                            "mandatory."
                        ),
                        table=tname,
                        column=col_name,
                        evidence={"references": fk.get("refTable")},
                    ))
    return out


def rule_naming_consistency(schema: dict) -> list[dict]:
    """Warn when table names mix singular/plural styles."""
    out: list[dict] = []
    tables = [t.get("name", "") for t in schema.get("tables", []) if t.get("name")]
    if len(tables) < 3:
        return out
    plural = [t for t in tables if t.endswith("s")]
    singular = [t for t in tables if not t.endswith("s")]
    if plural and singular and len(plural) >= 2 and len(singular) >= 2:
        out.append(_advisory(
            rule="naming_consistency",
            severity=SEVERITY_INFO,
            title="Mixed singular/plural table names",
            reason=(
                f"Schema mixes plural ({', '.join(sorted(plural)[:3])}) and "
                f"singular ({', '.join(sorted(singular)[:3])}) table names. "
                "Pick one convention for consistency."
            ),
            evidence={"plural": plural, "singular": singular},
        ))
    return out


def rule_redundant_index(schema: dict) -> list[dict]:
    """Flag indexes that duplicate a PK/UQ on the same columns."""
    out: list[dict] = []
    for table in schema.get("tables", []):
        tname = table.get("name", "")
        pk = _pk_constraint(table)
        unique_col_sets = []
        if pk:
            unique_col_sets.append(("primary key", pk.get("columns", [])))
        for c in table.get("constraints", []):
            if c.get("type") == "unique":
                unique_col_sets.append(("unique constraint", c.get("columns", [])))
        for idx in table.get("indexes", []):
            if idx.get("unique"):
                continue
            idx_cols = idx.get("columns", [])
            for label, cols in unique_col_sets:
                if cols and _index_covers(idx, cols):
                    out.append(_advisory(
                        rule="redundant_index",
                        severity=SEVERITY_INFO,
                        title="Index duplicates existing constraint",
                        reason=(
                            f"Index {idx.get('name')} on {idx_cols} duplicates "
                            f"the {label} on the same columns. The constraint "
                            "already creates an index."
                        ),
                        table=tname,
                        fix_ddl=f'DROP INDEX {_quote(idx.get("name", ""))};',
                        evidence={"index": idx.get("name"), "duplicates": label},
                    ))
                    break
    return out


# ---------- Orchestration ----------


ALL_RULES = (
    rule_missing_primary_key,
    rule_missing_fk_index,
    rule_fk_pk_type_drift,
    rule_wide_varchar,
    rule_nullable_fk,
    rule_missing_audit_columns,
    rule_redundant_index,
    rule_naming_consistency,
)


def analyze_schema(schema: dict) -> dict:
    """Run all rules and return a structured advisory report."""
    advisories: list[dict] = []
    for rule in ALL_RULES:
        advisories.extend(rule(schema))

    counts = {"error": 0, "warning": 0, "info": 0}
    for a in advisories:
        counts[a["severity"]] = counts.get(a["severity"], 0) + 1

    return {
        "advisories": advisories,
        "counts": counts,
        "scores": _compute_scores(schema, advisories),
    }


def _compute_scores(schema: dict, advisories: list[dict]) -> dict:
    """Rough 0.0–1.0 scores across three dimensions."""
    tables = schema.get("tables", [])
    if not tables:
        return {"index_coverage": 1.0, "type_precision": 1.0, "structure": 1.0}

    # Index coverage: 1 - (missing_fk_index / fk_count)
    fk_count = sum(len(_fk_constraints(t)) for t in tables)
    missing_idx = sum(1 for a in advisories if a["rule"] == "missing_fk_index")
    index_coverage = 1.0 if fk_count == 0 else max(0.0, 1.0 - missing_idx / fk_count)

    # Type precision: 1 - (type drift + wide varchar) / total columns
    total_cols = sum(len(t.get("columns", [])) for t in tables) or 1
    type_issues = sum(
        1 for a in advisories
        if a["rule"] in ("fk_pk_type_drift", "wide_varchar")
    )
    type_precision = max(0.0, 1.0 - type_issues / total_cols)

    # Structure: 1 - (tables without PK / table count)
    no_pk = sum(1 for a in advisories if a["rule"] == "missing_primary_key")
    structure = max(0.0, 1.0 - no_pk / len(tables))

    return {
        "index_coverage": round(index_coverage, 2),
        "type_precision": round(type_precision, 2),
        "structure": round(structure, 2),
    }
