"""The analyzer's refusals: a stable code, a human message, an HTTP status.

Raised by the service layer, translated once by the route. The code is what a
client branches on; the message is safe to show (fixed vocabulary, no driver
or file content).
"""
from __future__ import annotations


class AnalyzerError(Exception):
    status = 400

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        if status is not None:
            self.status = status


class UploadRejected(AnalyzerError):
    status = 422


class AnalyzerConflict(AnalyzerError):
    status = 409


class AnalyzerNotFound(AnalyzerError):
    status = 404

    def __init__(self, message: str = "No such analysis."):
        super().__init__("not_found", message)


class AnalyzerUnavailable(AnalyzerError):
    status = 503
