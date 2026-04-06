"""
cstruct_routes.py — Flask Blueprint for /api/cstruct/* endpoints.
Handles file upload and dispatches to c_parser.py.
"""

from flask import Blueprint, request, jsonify
from c_parser import parse_c_files, TARGET_MAP

cstruct_bp = Blueprint("cstruct", __name__, url_prefix="/api/cstruct")


@cstruct_bp.route("/upload", methods=["POST"])
def upload():
    """Parse uploaded .c/.h files and return struct layouts.

    Accepts multipart form with:
      - files[]: one or more .c/.h files
      - target: architecture key (arm, sparc, linux_x64, win_x64)
    """
    target = request.form.get("target", "arm")

    # Collect uploaded files
    file_contents: dict[str, str] = {}
    uploaded = request.files.getlist("files[]")

    if not uploaded:
        return jsonify({"error": "No files uploaded"}), 400

    for f in uploaded:
        if f.filename:
            content = f.read().decode("utf-8", errors="replace")
            file_contents[f.filename] = content

    if not file_contents:
        return jsonify({"error": "No valid files found"}), 400

    result = parse_c_files(file_contents, target)
    return jsonify(result)


@cstruct_bp.route("/targets", methods=["GET"])
def list_targets():
    """Return available target architectures."""
    targets = []
    for key, info in TARGET_MAP.items():
        targets.append({
            "key": key,
            "label": info["label"],
            "endianness": info["endianness"],
            "pointer_size": info["pointer_size"],
        })
    return jsonify({"targets": targets})
