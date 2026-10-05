"""The offline demo launcher (scripts/analyzer_demo.py): it never touches a
process it did not start, never takes a port that is in use, keeps its state
out of Git, and `reset` deletes only local demo databases it recorded."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))
import _analyzer_demo_server as server  # noqa: E402
import analyzer_demo as demo  # noqa: E402


def test_a_held_port_is_reported_with_its_holder_and_a_free_one_is_not():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        held = demo.port_holder(port)
        assert held and str(os.getpid()) in held                       # names who holds it
    assert demo.port_holder(port) is None


def test_start_refuses_a_held_port_and_kills_nothing(tmp_path, capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        code = demo.main(["start", "--backend-port", str(port), "--state-dir", str(tmp_path)])
        assert code == 2 and "REFUSING TO START" in capsys.readouterr().out
        assert s.fileno() != -1                                           # our listener is untouched
    assert not (tmp_path / "run.json").exists()


def test_ownership_needs_pid_and_start_time():
    me = demo.record(os.getpid())
    assert demo.owned(me) is not None
    assert demo.owned({**me, "create_time": me["create_time"] - 5}) is None    # a reused pid
    assert demo.owned({"pid": 999_999_999, "create_time": 0}) is None
    assert demo.owned(None) is None


def test_stop_leaves_a_process_it_does_not_own(tmp_path):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        demo._save(tmp_path / "run.json", {"backend": {"pid": other.pid, "create_time": 1.0},
                                           "frontend": {"pid": other.pid, "create_time": 1.0}, "db_name": "aai_demo_x1234"})
        assert demo.main(["stop", "--state-dir", str(tmp_path)]) == 0
        assert other.poll() is None                                       # still running
    finally:
        other.kill()


def test_state_must_live_outside_the_repository():
    with pytest.raises(SystemExit):
        demo.check_state_dir(BACKEND / "demo-state")
    demo.check_state_dir(demo.DEFAULT_STATE)


@pytest.mark.parametrize("entry", [{"db_name": "attorney_ai"}, {"db_name": "aai_smoke_1234"},
                                   {"db_name": "aai_demo_x1234", "mongo_port": "1@db.example.net:27017"}])
def test_reset_refuses_anything_not_a_recorded_local_demo_database(entry):
    with pytest.raises(demo.DemoRefused):
        demo.reset_plan([entry], 27018)


def test_reset_lists_only_recorded_names_and_deletes_nothing_without_yes(tmp_path, capsys):
    assert demo.reset_plan([{"db_name": "aai_demo_ab12cd34"}, {"db_name": "aai_demo_ab12cd34"}], 27018) \
        == ["aai_demo_ab12cd34"]
    demo._save(tmp_path / "databases.json", [{"db_name": "aai_demo_doesnotexist0"}])
    if demo.replset_up(27018):
        assert demo.main(["reset", "--state-dir", str(tmp_path)]) == 0
        assert "Nothing to reset" in capsys.readouterr().out


def test_generated_demo_passwords_always_meet_the_registration_policy():
    from app.utils.validators import validate_password_strength
    passwords = {server.demo_password() for _ in range(500)}
    assert len(passwords) == 500 and all(validate_password_strength(p) for p in passwords)


def test_the_build_marker_tracks_the_backend_port(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "FRONTEND", tmp_path)
    assert demo.build_needed(8765) == "no demo build yet"
    (tmp_path / demo.DIST).mkdir()
    (tmp_path / demo.DIST / "BUILD_ID").write_text("x")
    demo._save(tmp_path / demo.DIST / demo.BUILD_MARKER,
               {"api_proxy_target": "http://127.0.0.1:8765", "source": demo.source_fingerprint()})
    assert demo.build_needed(8765) is None
    assert "another backend port" in demo.build_needed(9000)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "page.jsx").write_text("changed")
    assert "source changed" in demo.build_needed(8765)
