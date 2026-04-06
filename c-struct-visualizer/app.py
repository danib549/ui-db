"""
app.py — Flask application for C Struct Visualizer.
Thin route layer: registers blueprints, serves pages.
"""

from flask import Flask, render_template
from cstruct_routes import cstruct_bp

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit

# Register blueprints
app.register_blueprint(cstruct_bp)


@app.route("/")
def index():
    """Serve the main C struct visualizer page."""
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5004)
