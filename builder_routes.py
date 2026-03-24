"""Flask Blueprint for /api/builder/* routes — keeps app.py thin."""

from flask import Blueprint, request, jsonify, current_app

builder_bp = Blueprint('builder', __name__, url_prefix='/api/builder')


@builder_bp.route('/validate', methods=['POST'])
def validate():
    """Validate schema, return errors."""
    from pg_validator import validate_schema

    data = request.get_json(silent=True) or {}
    schema = data.get("schema")

    if not schema:
        return jsonify({"error": "schema is required"}), 400

    issues = validate_schema(schema)
    return jsonify({"issues": issues})


@builder_bp.route('/generate-ddl', methods=['POST'])
def generate_ddl():
    """Generate PostgreSQL DDL from schema."""
    from ddl_generator import generate_full_ddl

    data = request.get_json(silent=True) or {}
    schema = data.get("schema")

    if not schema:
        return jsonify({"error": "schema is required"}), 400

    sql = generate_full_ddl(schema)
    return jsonify({"sql": sql})


@builder_bp.route('/generate-migration', methods=['POST'])
def generate_migration():
    """Generate migration SQL (ALTER-based if original exists, INSERT if source mapped)."""
    from schema_differ import generate_migration_ddl
    from ddl_generator import generate_full_ddl
    from migration_generator import generate_migration_sql

    data = request.get_json(silent=True) or {}
    original = data.get("original")
    modified = data.get("modified")
    source_mapping = data.get("sourceMapping", {})

    if not modified:
        return jsonify({"error": "modified schema is required"}), 400

    result: dict = {"mode": "create", "schemaSql": "", "dataSql": ""}

    if original:
        result["mode"] = "alter"
        result["schemaSql"] = generate_migration_ddl(original, modified)
    else:
        result["schemaSql"] = generate_full_ddl(modified)

    if source_mapping:
        result["dataSql"] = generate_migration_sql(source_mapping, modified)

    return jsonify(result)


@builder_bp.route('/import-sql', methods=['POST'])
def import_sql():
    """Parse uploaded .sql file into builder schema."""
    from ddl_parser import parse_ddl

    sql = ""
    if request.files.get("file"):
        raw = request.files["file"].read()
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                sql = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    else:
        data = request.get_json(silent=True) or {}
        sql = data.get("sql", "")

    if not sql.strip():
        return jsonify({"error": "No SQL provided"}), 400

    result = parse_ddl(sql)
    return jsonify({
        "schema": {
            "name": "public",
            "tables": result["tables"],
            "enums": result["enums"],
        },
        "warnings": result["warnings"],
    })


@builder_bp.route('/type-suggest', methods=['POST'])
def type_suggest():
    """Suggest PG type from source column metadata."""
    from type_mapper import suggest_pg_type

    data = request.get_json(silent=True) or {}
    source_type = data.get("sourceType", "VARCHAR")
    column_name = data.get("column", "")
    nullable = data.get("nullable", True)
    unique_count = data.get("uniqueCount", 0)
    total_count = data.get("totalCount", 0)
    sample_values = data.get("sampleValues")

    # Optionally load DataFrame from app's loaded tables
    df = None
    table_name = data.get("table", "")
    if table_name:
        loaded_dfs = getattr(current_app, 'loaded_dataframes', {})
        df = loaded_dfs.get(table_name)

    result = suggest_pg_type(
        source_type=source_type,
        column_name=column_name,
        nullable=nullable,
        unique_count=unique_count,
        total_count=total_count,
        sample_values=sample_values,
        df=df,
    )
    return jsonify(result)


@builder_bp.route('/preview-table', methods=['POST'])
def preview_table():
    """Preview DDL for a single table."""
    from ddl_generator import generate_table_preview

    data = request.get_json(silent=True) or {}
    table = data.get("table")

    if not table:
        return jsonify({"error": "table is required"}), 400

    sql = generate_table_preview(table)
    return jsonify({"sql": sql})


@builder_bp.route('/source-tables', methods=['GET'])
def source_tables():
    """Return list of loaded CSV tables available for source mapping."""
    loaded = getattr(current_app, 'loaded_tables', {})
    tables = []
    for name, info in loaded.items():
        tables.append({
            "name": name,
            "columns": info.get("columns", []),
        })
    return jsonify({"tables": tables})
