"""Flask application — thin route layer for the DB Diagram Visualizer."""

import json
import mimetypes

from flask import Flask, request, jsonify, render_template
import pandas as pd
from werkzeug.utils import secure_filename

from csv_handler import parse_csv_columns
from key_detector import detect_keys
from metadata_parser import (
    is_metadata_file,
    parse_metadata_csvs,
    build_table_name_map,
    apply_metadata_keys,
    build_metadata_relationships,
)
from relationship_analyzer import detect_relationships
from schema_advisor import analyze_designer_schema, report_to_markdown, advisory_to_markdown
from search import search_all_tables
from trace import trace_value
from builder_routes import builder_bp

# Ensure .js files are served with the correct MIME type
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')

app = Flask(__name__)
app.register_blueprint(builder_bp)

# In-memory storage
loaded_tables: dict[str, dict] = {}
loaded_dataframes: dict[str, pd.DataFrame] = {}
detected_relationships: list[dict] = []
metadata_relationships: list[dict] = []  # from SQL Server metadata CSVs
has_metadata_loaded: bool = False

# Expose shared data on app object so blueprints can access via current_app
app.loaded_tables = loaded_tables
app.loaded_dataframes = loaded_dataframes


@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.route("/builder")
def builder():
    """Serve the PostgreSQL Schema Builder page."""
    return render_template("builder.html")


@app.route("/api/upload-csv", methods=["POST"])
def upload_csv():
    """Accept CSV file uploads, parse columns, detect keys and relationships.

    Expects multipart form data with a 'files' field (one or more CSV files).
    Optionally accepts 'existing_tables' as a JSON string for incremental upload.
    """
    global detected_relationships, metadata_relationships, has_metadata_loaded

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400

    existing_json = request.form.get("existing_tables")
    if existing_json:
        try:
            existing = json.loads(existing_json)
            for table in existing:
                name = table.get("name", "")
                if name and name not in loaded_tables:
                    loaded_tables[name] = table
        except (json.JSONDecodeError, TypeError):
            pass

    # Separate metadata files from data files
    metadata_raw: dict[str, bytes] = {}
    data_files = []

    for file in files:
        if not file or not file.filename:
            continue

        filename = secure_filename(file.filename)
        if not filename.lower().endswith(".csv"):
            continue

        raw = file.read()
        file.seek(0)

        if is_metadata_file(filename):
            metadata_raw[filename] = raw
        else:
            data_files.append((filename, raw))

    # Parse metadata CSVs (PKs, FKs, column types) if present
    metadata = parse_metadata_csvs(metadata_raw)
    has_metadata = bool(metadata_raw)

    new_tables: list[dict] = []
    all_table_names = list(loaded_tables.keys())

    for filename, raw in data_files:
        table_name = filename.rsplit(".", 1)[0]

        try:
            # Try utf-8-sig first (handles BOM from SQL Server exports)
            for encoding in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    import io
                    text = raw.decode(encoding)
                    df = pd.read_csv(io.StringIO(text), engine="python", sep=None, index_col=False)
                    break
                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue
            else:
                continue
        except Exception:
            continue

        # Clean column names: strip whitespace
        df.columns = [str(c).strip() for c in df.columns]

        # Drop unnamed index columns (common in SQL Server exports)
        unnamed_cols = [c for c in df.columns if c.startswith("Unnamed:")]
        if unnamed_cols:
            df = df.drop(columns=unnamed_cols)

        if df.empty and df.columns.empty:
            continue

        all_table_names.append(table_name)
        columns = parse_csv_columns(df)
        columns = detect_keys(table_name, columns, all_table_names)
        group = _detect_group(table_name)

        table_info = {
            "name": table_name,
            "columns": columns,
            "group": group,
        }

        loaded_tables[table_name] = table_info
        loaded_dataframes[table_name] = df
        new_tables.append(table_info)

    # If metadata CSVs were provided, use them for accurate keys and relationships
    if has_metadata:
        has_metadata_loaded = True

        # Collect all table names referenced in metadata
        meta_table_names: set[str] = set()
        for pk_table in metadata["primary_keys"]:
            meta_table_names.add(pk_table)
        for fk in metadata["foreign_keys"]:
            meta_table_names.add(fk["parent_table"])
            meta_table_names.add(fk["referenced_table"])
        for (tbl, _col) in metadata["columns"]:
            meta_table_names.add(tbl)

        # Map metadata table names -> loaded table names
        name_map = build_table_name_map(
            list(loaded_tables.keys()), meta_table_names,
        )

        # Apply PK and column type metadata to each table
        for meta_name, loaded_name in name_map.items():
            if loaded_name in loaded_tables:
                apply_metadata_keys(
                    loaded_tables[loaded_name],
                    metadata["primary_keys"],
                    metadata["columns"],
                    meta_name,
                )

        # Build and store metadata relationships separately
        metadata_relationships = build_metadata_relationships(
            metadata["foreign_keys"],
            name_map,
            loaded_tables,
            loaded_dataframes,
        )

    # Combine relationships from all enabled sources
    detected_relationships = _combine_relationships(
        use_metadata=has_metadata,
        use_name_based=True,
        use_value_matching=request.form.get("value_matching", "").lower() == "true",
    )

    return jsonify({
        "tables": list(loaded_tables.values()),
        "relationships": detected_relationships,
        "has_metadata": has_metadata_loaded,
    })


@app.route("/api/detect-relationships", methods=["POST"])
def redetect_relationships():
    """Re-detect relationships for all currently loaded tables.

    Accepts JSON body with boolean flags:
      metadata (default true), name_based (default true), value_matching (default false).
    """
    global detected_relationships

    data = request.get_json(silent=True) or {}
    detected_relationships = _combine_relationships(
        use_metadata=data.get("metadata", True),
        use_name_based=data.get("name_based", True),
        use_value_matching=data.get("value_matching", False),
    )

    return jsonify({"relationships": detected_relationships})


@app.route("/api/search", methods=["POST"])
def search():
    """Search for a value across loaded tables.

    Expects JSON body: {query, mode, scope}.
    """
    data = request.get_json(silent=True) or {}
    query = data.get("query", "")
    mode = data.get("mode", "contains")
    scope = data.get("scope", "all")

    results = search_all_tables(loaded_dataframes, query, mode, scope)
    return jsonify(results)


@app.route("/api/trace", methods=["POST"])
def trace():
    """Trace a value across tables via FK relationships.

    Expects JSON body: {table, column, value, depth}.
    """
    data = request.get_json(silent=True) or {}
    table = data.get("table", "")
    column = data.get("column", "")
    value = data.get("value", "")
    depth = data.get("depth", 5)

    if not table or not column:
        return jsonify({"error": "table and column are required"}), 400

    results = trace_value(
        list(loaded_tables.values()),
        detected_relationships,
        loaded_dataframes,
        table,
        column,
        str(value),
        max_depth=int(depth),
    )
    return jsonify(results)


@app.route("/api/table-data")
def table_data():
    """Return row data for a table as a JSON grid.

    Query params: table. Returns columns metadata and up to 500 rows.
    """
    table = request.args.get("table", "")
    if not table:
        return jsonify({"error": "table is required"}), 400

    table_info = loaded_tables.get(table)
    df = loaded_dataframes.get(table)
    if table_info is None or df is None:
        return jsonify({"error": "table not found"}), 404

    columns = table_info.get("columns", [])
    col_names = [c["name"] for c in columns]
    rows = df[col_names].head(500).fillna("").astype(str).values.tolist()

    return jsonify({
        "table": table,
        "columns": columns,
        "rows": rows,
    })


@app.route("/api/column-values")
def column_values():
    """Return unique values for a specific table column.

    Query params: table, column. Returns up to 100 unique non-null values.
    """
    table = request.args.get("table", "")
    column = request.args.get("column", "")

    if not table or not column:
        return jsonify({"error": "table and column are required"}), 400

    df = loaded_dataframes.get(table)
    if df is None or column not in df.columns:
        return jsonify({"error": "table or column not found"}), 404

    values = df[column].dropna().unique()
    values_list = [str(v) for v in values[:100]]
    return jsonify({"table": table, "column": column, "values": values_list})


@app.route("/api/analyze-schema", methods=["POST"])
def analyze_schema():
    """Run the schema advisor over loaded CSV tables and detected relationships.

    Returns:
        advisories — list of improvement suggestions with fix SQL
        counts — {error, warning, info} tallies
        scores — {structure, type_precision, relationships} 0.0-1.0
        stats  — {tables, columns, relationships}
        markdown — full LLM-friendly copy-paste report
    """
    if not loaded_tables:
        return jsonify({
            "advisories": [],
            "counts": {"error": 0, "warning": 0, "info": 0},
            "scores": {"structure": 1.0, "type_precision": 1.0, "relationships": 1.0},
            "stats": {"tables": 0, "columns": 0, "relationships": 0},
            "markdown": "",
        })

    tables = list(loaded_tables.values())
    report = analyze_designer_schema(
        tables,
        loaded_dataframes,
        detected_relationships,
    )
    report["markdown"] = report_to_markdown(report, tables, detected_relationships)
    return jsonify(report)


@app.route("/api/advisory-markdown", methods=["POST"])
def advisory_markdown():
    """Render a single advisory as standalone Markdown for copy-paste.

    Expects JSON body: {advisory: {...}}. Uses current loaded state to
    attach table context.
    """
    data = request.get_json(silent=True) or {}
    advisory = data.get("advisory")
    if not advisory:
        return jsonify({"error": "advisory is required"}), 400

    tables_by_name = dict(loaded_tables)
    rels_by_table: dict[str, list[dict]] = {}
    for r in detected_relationships:
        rels_by_table.setdefault(r["source_table"], []).append(r)
        rels_by_table.setdefault(r["target_table"], []).append(r)

    md = advisory_to_markdown(advisory, {
        "tables_by_name": tables_by_name,
        "rels_by_table": rels_by_table,
    })
    return jsonify({"markdown": md})


@app.route("/api/debug-table")
def debug_table():
    """Debug endpoint — shows raw column info for a loaded table."""
    table = request.args.get("table", "")
    df = loaded_dataframes.get(table)
    table_info = loaded_tables.get(table)
    if df is None:
        return jsonify({"error": "table not found"}), 404

    df_cols = list(df.columns)
    meta_cols = [c["name"] for c in table_info.get("columns", [])]
    first_row = df.head(1).fillna("").astype(str).values.tolist()

    return jsonify({
        "df_columns": df_cols,
        "meta_columns": meta_cols,
        "match": df_cols == meta_cols,
        "df_shape": list(df.shape),
        "first_row": first_row[0] if first_row else [],
    })


def _combine_relationships(
    use_metadata: bool = True,
    use_name_based: bool = True,
    use_value_matching: bool = False,
) -> list[dict]:
    """Combine relationships from enabled sources, deduplicating by key."""
    combined: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    # Metadata relationships first (highest confidence)
    if use_metadata and metadata_relationships:
        for rel in metadata_relationships:
            key = (rel["source_table"], rel["source_column"],
                   rel["target_table"], rel["target_column"])
            if key not in seen:
                seen.add(key)
                combined.append(rel)

    # Heuristic relationships (name-based and/or value-based)
    if use_name_based or use_value_matching:
        heuristic = detect_relationships(
            list(loaded_tables.values()), loaded_dataframes,
            value_matching=use_value_matching,
            name_matching=use_name_based,
        )
        for rel in heuristic:
            key = (rel["source_table"], rel["source_column"],
                   rel["target_table"], rel["target_column"])
            if key not in seen:
                seen.add(key)
                combined.append(rel)

    return combined


def _detect_group(table_name: str) -> str:
    """Auto-detect a group from a table name prefix.

    'auth_users' -> 'auth', 'order_items' -> 'order',
    'users' -> '' (no prefix).
    """
    parts = table_name.split("_")
    if len(parts) >= 2:
        return parts[0]
    return ""


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
