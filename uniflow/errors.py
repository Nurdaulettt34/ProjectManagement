from flask import jsonify, request
from werkzeug.exceptions import HTTPException


def error(message, status):
    """Uniform error body for the whole API: {"error": "..."}."""
    return jsonify({"error": message}), status


def register_error_handlers(app):
    @app.errorhandler(413)
    def too_large(e):
        mb = app.config["MAX_FILE_SIZE"] // (1024 * 1024)
        return error(f"File exceeds the maximum size of {mb} MB.", 413)

    @app.errorhandler(HTTPException)
    def http_error(e):
        if request.path.startswith("/api/"):
            return error(e.description if e.code != 404 else "Not found.", e.code)
        return e

    @app.errorhandler(Exception)
    def unexpected(e):
        app.logger.exception("Unhandled error")
        if request.path.startswith("/api/"):
            return error("Internal server error.", 500)
        return "Internal server error", 500
