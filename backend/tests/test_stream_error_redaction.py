"""SSE error frames must not carry provider detail to the user.

An SSE stream cannot return a normal error response — by the time generation
fails the StreamingResponse has begun, so the stream is the only channel left.
`str(exc)` was the obvious thing to put there and the wrong one. Verified live
before the fix: a user asking about theft received

    data: {"error": "Error code: 401 - {'error': {'message': 'Invalid API Key',
           'type': 'invalid_request_error', 'code': 'invalid_api_key'}}"}

naming the provider and our auth state. Other failures would name billing status
or the local model path. The WebSocket chat path already returned a friendly
message; these HTTP streams did not, and they are what the chat UI calls.
"""
import json

from app.api.v1.routes import ai


class TestTheErrorFrame:
    def test_it_is_valid_sse(self):
        frame = ai._stream_error("test")
        assert frame.startswith("data: ")
        assert frame.endswith("\n\n")
        json.loads(frame[len("data: "):].strip())

    def test_it_says_nothing_operational(self):
        payload = json.loads(ai._stream_error("test")[len("data: "):].strip())
        msg = payload["error"]
        for forbidden in ("API_KEY", "api_key", "401", "Invalid API Key",
                          "GROQ", "GEMINI", "OPENROUTER", "OLLAMA", "Traceback"):
            assert forbidden not in msg

    def test_it_tells_the_user_something_useful(self):
        """A blank or bare 'error' teaches nothing. The user should know it is
        transient and that their question was not lost."""
        msg = json.loads(ai._stream_error("test")[len("data: "):].strip())["error"]
        assert "temporarily unavailable" in msg
        assert "not lost" in msg

    def test_the_detail_still_reaches_the_log(self, caplog):
        """Redacting the user's copy must not blind the operator."""
        import logging
        with caplog.at_level(logging.ERROR):
            try:
                raise RuntimeError("Invalid API Key")
            except RuntimeError:
                ai._stream_error("ai.stream")
        assert any("streaming generation failed" in r.getMessage() for r in caplog.records)


def test_no_route_yields_a_raw_exception():
    """The regression itself: str(exc) must not reappear in an SSE frame."""
    import inspect
    src = inspect.getsource(ai)
    body = src.split("_STREAM_ERROR", 1)[1]      # skip the explanatory comment
    assert "'error': str(exc)" not in body
    assert '"error": str(exc)' not in body
