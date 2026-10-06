import importlib.util
from pathlib import Path


_PATH = Path(__file__).parents[1] / "scripts" / "manual_smoke" / "_smoke_env.py"
_SPEC = importlib.util.spec_from_file_location("manual_smoke_env", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)


def test_manual_smokes_default_to_the_browser_facing_next_origin(monkeypatch):
    monkeypatch.delenv("SMOKE_ORIGIN", raising=False)
    assert _MODULE.smoke_origins() == (
        "http://127.0.0.1:3000/api/v1",
        "ws://127.0.0.1:3000",
    )


def test_manual_smokes_support_https_tunnels(monkeypatch):
    monkeypatch.setenv("SMOKE_ORIGIN", "https://demo.example/")
    assert _MODULE.smoke_origins() == (
        "https://demo.example/api/v1",
        "wss://demo.example",
    )
