"""Flask application — thin route layer for the DB Diagram Visualizer."""

import json

from flask import Flask, request, jsonify, render_template
import pandas as pd
from werkzeug.utils import secure_filename

from csv_handler import parse_csv_columns
from key_detector import detect_keys
from relationship_analyzer import detect_relationships
from search import search_all_tables
from trace import trace_value


app = Flask(__name__)

# In-memory storage
loaded_tables: dict[str, dict] = {}
loaded_dataframes: dict[str, pd.DataFrame] = {}
detected_relationships: list[dict] = []


@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.route("/api/upload-csv", methods=["POST"])
def upload_csv():
    """Accept CSV file uploads, parse columns, detect keys and relationships.

    Expects multipart form data with a 'files' field (one or more CSV files).
    Optionally accepts 'existing_tables' as a JSON string for incremental upload.
    """
    global detected_relationships

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

    new_tables: list[dict] = []
    all_table_names = list(loaded_tables.keys())

    for file in files:
        if not file or not file.filename:
            continue

        filename = secure_filename(file.filename)
        if not filename.lower().endswith(".csv"):
            continue

        table_name = filename.rsplit(".", 1)[0]

        try:
            df = pd.read_csv(file)
        except Exception:
            continue

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

    detected_relationships = detect_relationships(
        list(loaded_tables.values()), loaded_dataframes,
    )

    return jsonify({
        "tables": list(loaded_tables.values()),
        "relationships": detected_relationships,
    })


@app.route("/api/detect-relationships", methods=["POST"])
def redetect_relationships():
    """Re-detect relationships for all currently loaded tables."""
    global detected_relationships

    detected_relationships = detect_relationships(
        list(loaded_tables.values()), loaded_dataframes,
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
    app.run(debug=True, port=5000)
