"""The single error envelope used by every handler (planning.md section 6)."""

from flask import jsonify


class ApiError(Exception):
    """Raised anywhere in a request; converted to the envelope by the handler."""

    def __init__(self, status, code, message, field=None, detail=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.detail = detail

    def to_response(self):
        body = {"code": self.code, "message": self.message}
        if self.field is not None:
            body["field"] = self.field
        if self.detail is not None:
            body["detail"] = self.detail
        return jsonify({"error": body}), self.status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return exc.to_response()

    @app.errorhandler(404)
    def _handle_404(_exc):
        return ApiError(404, "NOT_FOUND", "No such endpoint.").to_response()

    @app.errorhandler(405)
    def _handle_405(_exc):
        return ApiError(
            405, "METHOD_NOT_ALLOWED", "That method is not allowed here."
        ).to_response()

    @app.errorhandler(500)
    def _handle_500(_exc):
        return ApiError(500, "INTERNAL_ERROR", "Unexpected server error.").to_response()
