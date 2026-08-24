"""serve.py must not claim to have started a server it did not start.

Two failures, both observed live on 2026-08-24 while debugging a UI bug:

  1. `start` printed "started pid N -> http://127.0.0.1:8000" while uvicorn was
     dying with [Errno 10048]. An older orphaned server kept answering, so the
     port looked healthy and the wrong build was tested for an entire session.
  2. `start` opened the log with "w", truncating the RUNNING server's log —
     destroying the access lines that would have shown whether a user's click
     ever reached the backend.
"""
import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "serve_mod", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "serve.py")
serve = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(serve)


class _Res:
    def __init__(self, stdout): self.stdout = stdout


NETSTAT = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       14404
  TCP    127.0.0.1:9999         0.0.0.0:0              LISTENING       777
  TCP    127.0.0.1:8000         127.0.0.1:57394        TIME_WAIT       0
"""


class TestPortHolder:
    def test_it_finds_the_listening_pid(self, monkeypatch):
        monkeypatch.setattr(serve.subprocess, "run", lambda *a, **k: _Res(NETSTAT))
        assert serve._port_holder("127.0.0.1", 8000) == 14404

    def test_a_free_port_returns_none(self, monkeypatch):
        monkeypatch.setattr(serve.subprocess, "run", lambda *a, **k: _Res(NETSTAT))
        assert serve._port_holder("127.0.0.1", 8123) is None

    def test_non_listening_rows_are_ignored(self, monkeypatch):
        """TIME_WAIT on the same port is not a holder — treating it as one would
        refuse to start after every restart."""
        only_wait = "  TCP    127.0.0.1:8000    127.0.0.1:1  TIME_WAIT       0\n"
        monkeypatch.setattr(serve.subprocess, "run", lambda *a, **k: _Res(only_wait))
        assert serve._port_holder("127.0.0.1", 8000) is None

    def test_it_does_not_confuse_ports_by_prefix(self, monkeypatch):
        monkeypatch.setattr(serve.subprocess, "run", lambda *a, **k: _Res(NETSTAT))
        assert serve._port_holder("127.0.0.1", 800) is None

    def test_a_netstat_failure_does_not_block_startup(self, monkeypatch):
        """If the check itself breaks, fall back to starting — a broken guard
        must not make the tool unusable."""
        def _boom(*a, **k): raise OSError("netstat missing")
        monkeypatch.setattr(serve.subprocess, "run", _boom)
        assert serve._port_holder("127.0.0.1", 8000) is None


def test_the_log_is_opened_for_append_not_truncation():
    """Opening "w" destroyed the running server's access history. The evidence
    of what a user actually did is worth more than a small log file."""
    import inspect
    src = inspect.getsource(serve.start)
    assert 'open(LOG_FILE, "a"' in src
    assert 'open(LOG_FILE, "w"' not in src


def test_start_refuses_when_the_port_is_held():
    import inspect
    src = inspect.getsource(serve.start)
    assert "_port_holder" in src
    # the refusal must come before the process is spawned
    assert src.index("_port_holder") < src.index("subprocess.Popen")
