"""Schema advisor — deterministic rules over CSVs loaded in the designer.

Pure functions that read already-detected designer state (loaded_tables,
loaded_dataframes, detected_relationships) and emit improvement advisories.
No HTTP, no side effects.

Inputs:
    tables: list[dict] — shape of loaded_tables.values() from app.py
        each table = {
            "name": str,
            "columns": [{name, type, nullable, unique_count, total_count,
                          key_type: "PK"|"FK"|"UQ"|None}, ...],
            "group": str,
        }
    dataframes: dict[str, pd.DataFrame]
    relationships: list[dict] — from relationship_analyzer
        each rel = {
            "source_table", "source_column",
            "target_table", "target_column",
            "type": "one-to-one"|"one-to-many"|"many-to-many",
            "confidence": "high"|"medium"|"low",
        }

Advisory shape:
    {
        "rule":     str,
        "severity": "error"|"warning"|"info",
        "title":    str,
        "table":    str | None,
        "column":   str | None,
        "reason":   str,
        "fix_sql":  str | None,  # suggested PG DDL (quoted identifiers)
        "evidence": dict | None,
    }
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

ENUM_MAX_UNIQUE = 15
ENUM_MIN_TOTAL = 10
HIGH_NULL_RATIO = 0.5
WIDE_AVG_LEN = 500
AUDIT_NAMES = {"created_at", "updated_at", "createdat", "updatedat"}


def _quote(name: str) -> str:
    """Safe PG identifier quoting — rejects embedded double quotes."""
    safe = name.replace('"', "")
    return f'"{safe}"'


def _advisory(
    rule: str,
    severity: str,
    title: str,
    reason: str,
    table: str | None = None,
    column: str | None = None,
    fix_sql: str | None = None,
    evidence: dict | None = None,
) -> dict:
    return {
        "rule": rule,
        "severity": severity,
        "title": title,
        "table": table,
        "column": column,
        "reason": reason,
        "fix_sql": fix_sql,
        "evidence": evidence,
    }


def _find_column(table: dict, col_name: str) -> dict | None:
    for c in table.get("columns", []):
        if c.get("name") == col_name:
            return c
    return None


def _pk_columns(table: dict) -> list[str]:
    return [c["name"] for c in table.get("columns", []) if c.get("key_type") == "PK"]


def _fk_columns(table: dict) -> list[str]:
    return [c["name"] for c in table.get("columns", []) if c.get("key_type") == "FK"]


def _null_ratio(df: pd.DataFrame | None, col_name: str) -> float | None:
    if df is None or col_name not in df.columns:
        return None
    total = len(df)
    if total == 0:
        return None
    non_null = int(df[col_name].count())
    return round((total - non_null) / total, 3)


def _avg_string_len(df: pd.DataFrame | None, col_name: str) -> float | None:
    if df is None or col_name not in df.columns:
        return None
    series = df[col_name].dropna()
    if series.empty:
        return None
    try:
        return float(series.astype(str).str.len().mean())
    except Exception:
        return None


def _sample_values(df: pd.DataFrame | None, col_name: str, n: int = 10) -> list[str]:
    if df is None or col_name not in df.columns:
        return []
    vals = df[col_name].dropna().unique()
    return [str(v) for v in vals[:n]]


# ---------- Rules ----------


def rule_missing_primary_key(tables: list[dict], *_args) -> list[dict]:
    out: list[dict] = []
    for table in tables:
        tname = table.get("name", "")
        if _pk_columns(table):
            continue
        out.append(_advisory(
            rule="missing_primary_key",
            severity=SEVERITY_WARNING,
            title="Table has no detected primary key",
            reason=(
                "No column in this table has a unique non-null value set with "
                "an identifier-like name. Without a PK, rows cannot be "
                "referenced, replicated, or safely updated by identity."
            ),
            table=tname,
            fix_sql=(
                f'-- Add surrogate PK to {tname}\n'
                f'ALTER TABLE {_quote(tname)} '
                f'ADD COLUMN "id" bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY;'
            ),
            evidence={"columns": [c.get("name") for c in table.get("columns", [])]},
        ))
    return out


def rule_unmarked_unique(tables: list[dict], *_args) -> list[dict]:
    """Columns with 100% unique non-null values that aren't marked PK/UQ."""
    out: list[dict] = []
    for table in tables:
        tname = table.get("name", "")
        for col in table.get("columns", []):
            key_type = col.get("key_type")
            if key_type in ("PK", "UQ"):
                continue
            unique = col.get("unique_count", 0)
            total = col.get("total_count", 0)
            if unique != total or total < 10 or unique < 10:
                continue
            if col.get("nullable", True):
                continue
            out.append(_advisory(
                rule="unmarked_unique",
                severity=SEVERITY_INFO,
                title="Column is unique but not marked",
                reason=(
                    f"All {total} values in '{col['name']}' are distinct and "
                    "non-null. Consider adding a UNIQUE constraint."
                ),
                table=tname,
                column=col["name"],
                fix_sql=(
                    f'ALTER TABLE {_quote(tname)} '
                    f'ADD CONSTRAINT {_quote(tname + "_" + col["name"] + "_key")} '
                    f'UNIQUE ({_quote(col["name"])});'
                ),
                evidence={"unique_count": unique, "total_count": total},
            ))
    return out


def rule_high_null_ratio(tables: list[dict], dataframes: dict, *_args) -> list[dict]:
    out: list[dict] = []
    for table in tables:
        tname = table.get("name", "")
        df = dataframes.get(tname)
        if df is None:
            continue
        for col in table.get("columns", []):
            cname = col.get("name", "")
            ratio = _null_ratio(df, cname)
            if ratio is None or ratio < HIGH_NULL_RATIO:
                continue
            pct = int(ratio * 100)
            out.append(_advisory(
                rule="high_null_ratio",
                severity=SEVERITY_INFO,
                title=f"{pct}% of values are NULL",
                reason=(
                    f"Column '{cname}' is null in {pct}% of {len(df)} rows. "
                    "Consider extracting it to a sparse side-table, adding a "
                    "DEFAULT, or reviewing whether it belongs here."
                ),
                table=tname,
                column=cname,
                evidence={"null_ratio": ratio, "total_rows": len(df)},
            ))
    return out


def rule_enum_candidate(tables: list[dict], dataframes: dict, *_args) -> list[dict]:
    out: list[dict] = []
    for table in tables:
        tname = table.get("name", "")
        df = dataframes.get(tname)
        for col in table.get("columns", []):
            cname = col.get("name", "")
            ctype = col.get("type", "")
            if ctype not in ("VARCHAR", "TEXT"):
                continue
            unique = col.get("unique_count", 0)
            total = col.get("total_count", 0)
            if unique <= 0 or unique > ENUM_MAX_UNIQUE or total < ENUM_MIN_TOTAL:
                continue
            if col.get("key_type") in ("PK", "UQ"):
                continue
            samples = _sample_values(df, cname, n=unique)
            enum_name = f"{tname}_{cname}_enum"
            values_sql = ", ".join(f"'{v.replace(chr(39), chr(39)*2)}'" for v in samples)
            out.append(_advisory(
                rule="enum_candidate",
                severity=SEVERITY_INFO,
                title="Column is an enum candidate",
                reason=(
                    f"Only {unique} distinct values across {total} rows. "
                    "A PostgreSQL ENUM type enforces valid values and uses "
                    "4 bytes regardless of label length."
                ),
                table=tname,
                column=cname,
                fix_sql=(
                    f'CREATE TYPE {_quote(enum_name)} AS ENUM ({values_sql});\n'
                    f'ALTER TABLE {_quote(tname)} '
                    f'ALTER COLUMN {_quote(cname)} TYPE {_quote(enum_name)} '
                    f'USING {_quote(cname)}::{_quote(enum_name)};'
                ),
                evidence={
                    "unique_count": unique,
                    "total_count": total,
                    "sample_values": samples,
                },
            ))
    return out


def rule_wide_varchar(tables: list[dict], dataframes: dict, *_args) -> list[dict]:
    out: list[dict] = []
    for table in tables:
        tname = table.get("name", "")
        df = dataframes.get(tname)
        if df is None:
            continue
        for col in table.get("columns", []):
            cname = col.get("name", "")
            ctype = col.get("type", "")
            if ctype not in ("VARCHAR", "TEXT"):
                continue
            avg_len = _avg_string_len(df, cname)
            if avg_len is None or avg_len < WIDE_AVG_LEN:
                continue
            out.append(_advisory(
                rule="wide_varchar",
                severity=SEVERITY_INFO,
                title="Column holds long text values",
                reason=(
                    f"Average length is {int(avg_len)} characters. Use TEXT "
                    "for unbounded long strings, or consider splitting this "
                    "field into a separate table if it is rarely queried."
                ),
                table=tname,
                column=cname,
                fix_sql=(
                    f'ALTER TABLE {_quote(tname)} '
                    f'ALTER COLUMN {_quote(cname)} TYPE text;'
                ),
                evidence={"avg_length": int(avg_len)},
            ))
    return out


def rule_boolean_masquerading(tables: list[dict], dataframes: dict, *_args) -> list[dict]:
    """INT columns that only hold 0/1 values — suggest BOOLEAN."""
    out: list[dict] = []
    for table in tables:
        tname = table.get("name", "")
        df = dataframes.get(tname)
        if df is None:
            continue
        for col in table.get("columns", []):
            cname = col.get("name", "")
            if col.get("type") not in ("INT", "FLOAT"):
                continue
            if col.get("key_type") in ("PK", "FK", "UQ"):
                continue
            if cname not in df.columns:
                continue
            vals = df[cname].dropna().unique()
            if len(vals) == 0 or len(vals) > 2:
                continue
            try:
                int_vals = {int(v) for v in vals}
            except (TypeError, ValueError):
                continue
            if not int_vals.issubset({0, 1}):
                continue
            out.append(_advisory(
                rule="boolean_masquerading",
                severity=SEVERITY_INFO,
                title="Numeric column holds only 0/1",
                reason=(
                    f"Column '{cname}' contains only {sorted(int_vals)}. "
                    "Storing it as BOOLEAN is clearer and one byte smaller."
                ),
                table=tname,
                column=cname,
                fix_sql=(
                    f'ALTER TABLE {_quote(tname)} '
                    f'ALTER COLUMN {_quote(cname)} TYPE boolean '
                    f'USING ({_quote(cname)} <> 0);'
                ),
                evidence={"distinct_values": sorted(int_vals)},
            ))
    return out


def rule_orphan_fk(tables: list[dict], _dfs: dict, relationships: list[dict]) -> list[dict]:
    """FK-named columns that have no detected target relationship."""
    out: list[dict] = []
    matched: set[tuple[str, str]] = {
        (r["source_table"], r["source_column"]) for r in relationships
    }
    for table in tables:
        tname = table.get("name", "")
        for col in table.get("columns", []):
            if col.get("key_type") != "FK":
                continue
            if (tname, col["name"]) in matched:
                continue
            out.append(_advisory(
                rule="orphan_fk",
                severity=SEVERITY_WARNING,
                title="Foreign-key-named column has no detected target",
                reason=(
                    f"Column '{col['name']}' looks like a foreign key but no "
                    "matching PK/UQ column was found in any loaded table. "
                    "Either the target table isn't loaded, the column is "
                    "misnamed, or values don't match an existing key."
                ),
                table=tname,
                column=col["name"],
                evidence={"detected_fk_name": col["name"]},
            ))
    return out


def rule_low_confidence_fk(_tables: list[dict], _dfs: dict, relationships: list[dict]) -> list[dict]:
    out: list[dict] = []
    for rel in relationships:
        if rel.get("confidence") not in ("low", "medium"):
            continue
        out.append(_advisory(
            rule="low_confidence_fk",
            severity=SEVERITY_INFO,
            title="Low-confidence relationship",
            reason=(
                f"Detected {rel['source_table']}.{rel['source_column']} → "
                f"{rel['target_table']}.{rel['target_column']} "
                f"with {rel.get('confidence', '?')} confidence. Some source "
                "values may not exist in the target key — data cleanup may "
                "be needed before enforcing a FK constraint."
            ),
            table=rel["source_table"],
            column=rel["source_column"],
            evidence={
                "target": f"{rel['target_table']}.{rel['target_column']}",
                "confidence": rel.get("confidence"),
                "cardinality": rel.get("type"),
            },
        ))
    return out


def rule_missing_fk_index(_tables: list[dict], _dfs: dict, relationships: list[dict]) -> list[dict]:
    """Every detected FK should be indexed in the target PG schema."""
    out: list[dict] = []
    for rel in relationships:
        src_table = rel["source_table"]
        src_col = rel["source_column"]
        idx_name = f"{src_table}_{src_col}_idx"[:63]
        out.append(_advisory(
            rule="missing_fk_index",
            severity=SEVERITY_WARNING,
            title="Foreign key needs an index",
            reason=(
                f"Joins from {src_table}.{src_col} to "
                f"{rel['target_table']}.{rel['target_column']} will scan the "
                "full child table without an index. Add this CREATE INDEX "
                "when you build the PostgreSQL schema."
            ),
            table=src_table,
            column=src_col,
            fix_sql=(
                f'CREATE INDEX {_quote(idx_name)} ON {_quote(src_table)} '
                f'({_quote(src_col)});'
            ),
            evidence={"references": f"{rel['target_table']}.{rel['target_column']}"},
        ))
    return out


def rule_missing_audit_columns(tables: list[dict], *_args) -> list[dict]:
    out: list[dict] = []
    for table in tables:
        tname = table.get("name", "")
        col_names = {c.get("name", "").lower().replace("_", "") for c in table.get("columns", [])}
        if col_names & {n.replace("_", "") for n in AUDIT_NAMES}:
            continue
        out.append(_advisory(
            rule="missing_audit_columns",
            severity=SEVERITY_INFO,
            title="No audit timestamp columns",
            reason=(
                "Table has no created_at/updated_at columns. Audit timestamps "
                "are useful for debugging, sync, and ordering."
            ),
            table=tname,
            fix_sql=(
                f'ALTER TABLE {_quote(tname)} '
                f'ADD COLUMN "created_at" timestamptz NOT NULL DEFAULT NOW(), '
                f'ADD COLUMN "updated_at" timestamptz;'
            ),
        ))
    return out


def rule_naming_consistency(tables: list[dict], *_args) -> list[dict]:
    names = [t.get("name", "") for t in tables if t.get("name")]
    if len(names) < 3:
        return []
    plural = [n for n in names if n.lower().endswith("s")]
    singular = [n for n in names if not n.lower().endswith("s")]
    if len(plural) >= 2 and len(singular) >= 2:
        return [_advisory(
            rule="naming_consistency",
            severity=SEVERITY_INFO,
            title="Mixed singular/plural table names",
            reason=(
                f"{len(plural)} plural tables ({', '.join(sorted(plural)[:3])}) "
                f"and {len(singular)} singular "
                f"({', '.join(sorted(singular)[:3])}). Pick one convention."
            ),
            evidence={"plural": plural, "singular": singular},
        )]
    return []


# ---------- Orchestration ----------


ALL_RULES = (
    rule_missing_primary_key,
    rule_unmarked_unique,
    rule_orphan_fk,
    rule_missing_fk_index,
    rule_low_confidence_fk,
    rule_enum_candidate,
    rule_boolean_masquerading,
    rule_high_null_ratio,
    rule_wide_varchar,
    rule_missing_audit_columns,
    rule_naming_consistency,
)


def analyze_designer_schema(
    tables: list[dict],
    dataframes: dict,
    relationships: list[dict],
) -> dict:
    """Run all rules against designer CSV state. Returns a report."""
    advisories: list[dict] = []
    for rule in ALL_RULES:
        advisories.extend(rule(tables, dataframes, relationships))

    counts = {"error": 0, "warning": 0, "info": 0}
    for a in advisories:
        counts[a["severity"]] = counts.get(a["severity"], 0) + 1

    return {
        "advisories": advisories,
        "counts": counts,
        "scores": _compute_scores(tables, relationships, advisories),
        "stats": {
            "tables": len(tables),
            "relationships": len(relationships),
            "columns": sum(len(t.get("columns", [])) for t in tables),
        },
    }


def _compute_scores(
    tables: list[dict],
    relationships: list[dict],
    advisories: list[dict],
) -> dict:
    if not tables:
        return {"structure": 1.0, "type_precision": 1.0, "relationships": 1.0}

    total_cols = sum(len(t.get("columns", [])) for t in tables) or 1
    no_pk = sum(1 for a in advisories if a["rule"] == "missing_primary_key")
    structure = max(0.0, 1.0 - no_pk / len(tables))

    type_issues = sum(
        1 for a in advisories
        if a["rule"] in ("wide_varchar", "enum_candidate", "boolean_masquerading")
    )
    type_precision = max(0.0, 1.0 - type_issues / total_cols)

    rel_issues = sum(
        1 for a in advisories
        if a["rule"] in ("orphan_fk", "low_confidence_fk")
    )
    rel_total = len(relationships) + rel_issues or 1
    rel_score = max(0.0, 1.0 - rel_issues / rel_total)

    return {
        "structure": round(structure, 2),
        "type_precision": round(type_precision, 2),
        "relationships": round(rel_score, 2),
    }


# ---------- LLM-friendly Markdown ----------


def advisory_to_markdown(advisory: dict, schema_context: dict | None = None) -> str:
    """Render a single advisory as a self-contained Markdown block.

    An LLM with no prior context can understand this block — it includes
    the rule, evidence, affected table/column, and proposed fix SQL.
    """
    severity_symbol = {
        "error": "[ERROR]",
        "warning": "[WARNING]",
        "info": "[INFO]",
    }.get(advisory["severity"], "[INFO]")

    lines: list[str] = []
    lines.append(f"## Advisory: {advisory['title']}")
    lines.append(f"**Severity:** {severity_symbol} {advisory['severity']}")
    lines.append(f"**Rule ID:** `{advisory['rule']}`")
    if advisory.get("table"):
        loc = advisory["table"]
        if advisory.get("column"):
            loc += f".{advisory['column']}"
        lines.append(f"**Location:** `{loc}`")
    lines.append("")
    lines.append("### Why")
    lines.append(advisory["reason"])
    lines.append("")

    if advisory.get("evidence"):
        lines.append("### Evidence")
        for k, v in advisory["evidence"].items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    if schema_context:
        ctx_lines = _render_table_context(schema_context, advisory)
        if ctx_lines:
            lines.append("### Table context")
            lines.extend(ctx_lines)
            lines.append("")

    if advisory.get("fix_sql"):
        lines.append("### Suggested change")
        lines.append("```sql")
        lines.append(advisory["fix_sql"])
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _render_table_context(schema_context: dict, advisory: dict) -> list[str]:
    """Render a small context block about the affected table."""
    tname = advisory.get("table")
    if not tname:
        return []
    tables_by_name = schema_context.get("tables_by_name", {})
    t = tables_by_name.get(tname)
    if not t:
        return []

    lines: list[str] = []
    lines.append(f"- Table `{tname}` has {len(t.get('columns', []))} columns")
    pks = [c["name"] for c in t.get("columns", []) if c.get("key_type") == "PK"]
    fks = [c["name"] for c in t.get("columns", []) if c.get("key_type") == "FK"]
    if pks:
        lines.append(f"- Primary key: {', '.join(pks)}")
    if fks:
        lines.append(f"- Foreign keys: {', '.join(fks)}")

    # Include related relationships
    rels = schema_context.get("rels_by_table", {}).get(tname, [])
    if rels:
        lines.append("- Relationships:")
        for r in rels[:5]:
            lines.append(
                f"  - `{r['source_table']}.{r['source_column']}` → "
                f"`{r['target_table']}.{r['target_column']}` "
                f"({r.get('type', 'n/a')}, {r.get('confidence', 'n/a')})"
            )
    return lines


def report_to_markdown(
    report: dict,
    tables: list[dict],
    relationships: list[dict],
) -> str:
    """Render the full report as a single copy-paste Markdown document.

    Includes summary, scores, schema snapshot, relationship table, and all
    advisories. Designed for pasting into an external LLM for triage.
    """
    counts = report.get("counts", {})
    scores = report.get("scores", {})
    stats = report.get("stats", {})

    tables_by_name = {t["name"]: t for t in tables}
    rels_by_table: dict[str, list[dict]] = {}
    for r in relationships:
        rels_by_table.setdefault(r["source_table"], []).append(r)
        rels_by_table.setdefault(r["target_table"], []).append(r)

    schema_context = {
        "tables_by_name": tables_by_name,
        "rels_by_table": rels_by_table,
    }

    lines: list[str] = []
    lines.append("# Schema Advisory Report")
    lines.append("")
    lines.append(
        f"Tables: {stats.get('tables', 0)} · "
        f"Columns: {stats.get('columns', 0)} · "
        f"Relationships: {stats.get('relationships', 0)}"
    )
    lines.append(
        f"Issues: {counts.get('error', 0)} error, "
        f"{counts.get('warning', 0)} warning, "
        f"{counts.get('info', 0)} info"
    )
    lines.append("")

    lines.append("## Project context")
    lines.append(
        "This schema was inferred from CSV files loaded in the DB Diagram "
        "Visualizer. Primary keys, foreign keys, and relationships were "
        "auto-detected from column names, uniqueness, null ratios, and "
        "value overlap between columns. The user is planning to build a "
        "production PostgreSQL schema from these CSVs and wants targeted, "
        "evidence-backed improvement suggestions."
    )
    lines.append("")

    lines.append("## Scores (0.0 – 1.0)")
    lines.append(f"- **Structure**: {scores.get('structure', 'n/a')} (PK coverage)")
    lines.append(f"- **Type precision**: {scores.get('type_precision', 'n/a')} (enum/bool/text fit)")
    lines.append(f"- **Relationships**: {scores.get('relationships', 'n/a')} (FK confidence)")
    lines.append("")

    lines.append("## Detected tables")
    lines.append("| Table | Cols | PK | FK cols |")
    lines.append("|-------|------|----|---------|")
    for t in tables:
        pks = [c["name"] for c in t.get("columns", []) if c.get("key_type") == "PK"]
        fks = [c["name"] for c in t.get("columns", []) if c.get("key_type") == "FK"]
        lines.append(
            f"| {t['name']} | {len(t.get('columns', []))} | "
            f"{', '.join(pks) or '—'} | {', '.join(fks) or '—'} |"
        )
    lines.append("")

    if relationships:
        lines.append("## Detected relationships")
        lines.append("| Source | Target | Type | Confidence |")
        lines.append("|--------|--------|------|------------|")
        for r in relationships:
            lines.append(
                f"| {r['source_table']}.{r['source_column']} "
                f"| {r['target_table']}.{r['target_column']} "
                f"| {r.get('type', 'n/a')} "
                f"| {r.get('confidence', 'n/a')} |"
            )
        lines.append("")

    lines.append("## Advisories")
    lines.append("")
    for a in report.get("advisories", []):
        lines.append(advisory_to_markdown(a, schema_context))
        lines.append("---")
        lines.append("")

    lines.append("## How to use this report")
    lines.append(
        "Paste this whole document into your LLM chat and ask: "
        "\"Which 3 advisories should I apply first for the biggest impact?\" "
        "or \"Rewrite my PostgreSQL DDL applying all warning-level fixes.\" "
        "Each advisory is self-contained with evidence and suggested SQL."
    )

    return "\n".join(lines)
