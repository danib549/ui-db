"""Flask Blueprint for /api/builder/* routes — keeps app.py thin."""

from flask import Blueprint, request, jsonify, current_app

builder_bp = Blueprint('builder', __name__, url_prefix='/api/builder')


def _validate_schema_structure(schema: dict) -> list[str]:
    """Check required fields exist before passing to generators.

    Returns list of error messages. Empty list means valid structure.
    """
    errors: list[str] = []

    for i, table in enumerate(schema.get("tables", [])):
        if not table.get("name"):
            errors.append(f"Table at index {i} is missing 'name'")
            continue
        tname = table["name"]

        for j, col in enumerate(table.get("columns", [])):
            if not col.get("name"):
                errors.append(f"Column at index {j} in table '{tname}' is missing 'name'")
            if "type" not in col:
                errors.append(f"Column '{col.get('name', f'at index {j}')}' in table '{tname}' is missing 'type'")

        for c in table.get("constraints", []):
            if not c.get("name"):
                errors.append(f"Constraint in table '{tname}' is missing 'name'")
            if c.get("type") == "fk":
                if not c.get("refTable"):
                    errors.append(f"FK constraint '{c.get('name', '?')}' in table '{tname}' is missing 'refTable'")
                if not c.get("refColumns"):
                    errors.append(f"FK constraint '{c.get('name', '?')}' in table '{tname}' is missing 'refColumns'")
            if c.get("type") == "check":
                if not c.get("expression"):
                    errors.append(f"CHECK constraint '{c.get('name', '?')}' in table '{tname}' is missing 'expression'")

        for idx in table.get("indexes", []):
            if not idx.get("name"):
                errors.append(f"Index in table '{tname}' is missing 'name'")

    for i, enum in enumerate(schema.get("enums", [])):
        if not enum.get("name"):
            errors.append(f"Enum at index {i} is missing 'name'")
        if "values" not in enum:
            errors.append(f"Enum '{enum.get('name', f'at index {i}')}' is missing 'values'")

    return errors


@builder_bp.route('/validate', methods=['POST'])
def validate():
    """Validate schema, return errors."""
    from pg_validator import validate_schema

    data = request.get_json(silent=True) or {}
    schema = data.get("schema")

    if not schema:
        return jsonify({"error": "schema is required"}), 400

    structure_errors = _validate_schema_structure(schema)
    if structure_errors:
        return jsonify({"error": "Invalid schema structure", "details": structure_errors}), 400

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

    structure_errors = _validate_schema_structure(schema)
    if structure_errors:
        return jsonify({"error": "Invalid schema structure", "details": structure_errors}), 400

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

    structure_errors = _validate_schema_structure(modified)
    if structure_errors:
        return jsonify({"error": "Invalid schema structure", "details": structure_errors}), 400

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

    # Wrap single table in a schema for structural validation
    structure_errors = _validate_schema_structure({"tables": [table], "enums": []})
    if structure_errors:
        return jsonify({"error": "Invalid table structure", "details": structure_errors}), 400

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
