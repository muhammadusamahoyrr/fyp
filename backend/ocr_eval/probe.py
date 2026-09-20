"""Read-only probe: what OCR capability does THIS machine actually have?

Installs nothing, downloads nothing, and does not touch PATH or any environment
variable. Every external call is a version/list query with a timeout.

WHY IT ALSO LOOKS OFF-PATH

`shutil.which` answers "can the server invoke `tesseract`", which is the question
that matters for running the product. It does not answer "is Tesseract installed
on this box", and on Windows those come apart constantly — the default installer
drops the binary in Program Files and does not add it to PATH. Reporting "not
installed" when a binary is sitting right there would send someone off to install
what they already have. So well-known locations are CHECKED and reported
separately, clearly marked as not-invocable. Checking is not altering: nothing
here writes to PATH, and the caller still sees `on_path: false`.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

#: Version/list queries only. Long enough for a cold start on a loaded machine,
#: short enough that a hung binary cannot stall the probe.
_CMD_TIMEOUT_SECONDS = 15

#: Language packs the intake evidence pipeline would need. `urd` is Urdu; `osd`
#: is orientation-and-script detection, which is what a rotated phone photo of an
#: FIR needs before any recognition is worth attempting.
REQUIRED_LANGS = ("eng", "urd", "osd")

#: Checked but never added to PATH. See the module docstring.
_WELL_KNOWN_TESSERACT = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)


def redact_path(value: str | None) -> str | None:
    """Replace the user's home directory with `~`.

    Reports get pasted into tickets and shared. An absolute path under a home
    directory carries the operating-system account name, which is PII we have no
    reason to publish to say whether a binary exists.
    """
    if not value:
        return value
    try:
        home = str(Path.home())
    except (RuntimeError, OSError):
        return value
    if not home:
        return value
    # Windows paths are case-insensitive; compare on a folded copy but slice the
    # original so the returned string keeps its real casing.
    if value[: len(home)].lower() == home.lower():
        return "~" + value[len(home):]
    return value


def _run(cmd: list[str]) -> dict:
    """Run a read-only query. Never raises; reports how it failed instead."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CMD_TIMEOUT_SECONDS,
            # Inherit the environment unchanged — the probe must observe the
            # machine as the server would see it, not a version it arranged.
            env=os.environ.copy(),
        )
    except FileNotFoundError:
        return {"ok": False, "reason": "not_found", "stdout": "", "stderr": ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout", "stdout": "", "stderr": ""}
    except OSError as exc:
        return {"ok": False, "reason": f"os_error: {exc.__class__.__name__}",
                "stdout": "", "stderr": ""}
    return {
        "ok": proc.returncode == 0,
        "reason": "ok" if proc.returncode == 0 else f"exit_{proc.returncode}",
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


def _parse_tesseract_version(text: str) -> str | None:
    """`tesseract 5.3.4.20240503` -> `5.3.4.20240503`.

    Tesseract prints the version on the first line and then a block of the
    libraries it was linked against, so only the first line is considered.
    """
    first = (text or "").strip().splitlines()
    if not first:
        return None
    m = re.search(r"tesseract\s+v?([0-9][0-9A-Za-z.\-]*)", first[0], re.IGNORECASE)
    return m.group(1) if m else None


def probe_tesseract() -> dict:
    """Engine presence, exact version, and language packs."""
    on_path = shutil.which("tesseract")

    off_path = []
    for candidate in _WELL_KNOWN_TESSERACT:
        try:
            if Path(candidate).is_file():
                off_path.append(candidate)
        except OSError:
            continue

    result: dict = {
        "available": bool(on_path),
        "on_path": bool(on_path),
        "path": redact_path(on_path),
        "version": None,
        "languages_present": [],
        "languages_required": list(REQUIRED_LANGS),
        "languages_missing": list(REQUIRED_LANGS),
        "found_off_path_not_invocable": [redact_path(p) for p in off_path],
        "notes": [],
    }

    if not on_path:
        if off_path:
            result["notes"].append(
                "A Tesseract binary exists at a well-known location but is not on "
                "PATH, so the server cannot invoke it. Reported as unavailable; "
                "PATH was NOT modified by this probe."
            )
        else:
            result["notes"].append("No Tesseract binary on PATH.")
        return result

    version = _run([on_path, "--version"])
    if version["ok"] or version["stdout"] or version["stderr"]:
        # Tesseract has historically written --version to stderr on some builds,
        # so both streams are considered before concluding nothing came back.
        result["version"] = _parse_tesseract_version(
            version["stdout"] or version["stderr"])
    if result["version"] is None:
        result["notes"].append(
            f"Binary present but the version could not be parsed ({version['reason']})."
        )

    langs = _run([on_path, "--list-langs"])
    if langs["ok"]:
        lines = [ln.strip() for ln in (langs["stdout"] or "").splitlines()]
        # The first line is a header ("List of available languages (N):").
        present = [ln for ln in lines[1:] if ln and " " not in ln]
        result["languages_present"] = sorted(present)
        result["languages_missing"] = [
            lang for lang in REQUIRED_LANGS if lang not in present]
    else:
        result["notes"].append(
            f"Could not list language packs ({langs['reason']}); "
            "treating all required packs as missing."
        )

    return result


def _package(dist_name: str, import_name: str | None = None) -> dict:
    """Is this Python package importable, and at what version?

    Importability and installed-metadata are separate questions — a broken
    native wheel imports-fails while still reporting a version — so both are
    recorded rather than collapsed into one boolean.
    """
    import importlib
    import importlib.metadata as md

    out: dict = {"available": False, "version": None, "import_error": None}
    try:
        out["version"] = md.version(dist_name)
    except Exception:
        out["version"] = None

    try:
        importlib.import_module(import_name or dist_name)
        out["available"] = True
    except Exception as exc:
        # The class name only. An import error message can contain absolute
        # paths from the loader, and this output gets shared.
        out["import_error"] = exc.__class__.__name__

    return out


def probe_python_packages() -> dict:
    return {
        "pypdfium2": _package("pypdfium2"),
        "pillow": _package("pillow", "PIL"),
        "pytesseract": _package("pytesseract"),
        # Not requested, but this is what the CURRENT pipeline extracts with, so
        # a readiness report that omitted it would be describing a different
        # system than the one in production.
        "pypdf": _package("pypdf"),
        "python_docx": _package("python-docx", "docx"),
    }


def probe_docker() -> dict:
    """CLI and daemon reported SEPARATELY.

    `docker` being installed says nothing about whether a container can run:
    on a developer laptop the CLI is present and the daemon is stopped most of
    the time. Collapsing them into "docker: yes" is how a plan to ship OCR in a
    sidecar gets approved against a machine that cannot start one.
    """
    cli_path = shutil.which("docker")
    out: dict = {
        "cli_available": bool(cli_path),
        "cli_path": redact_path(cli_path),
        "cli_version": None,
        "daemon_available": False,
        "daemon_version": None,
        "daemon_error": None,
    }
    if not cli_path:
        return out

    # `docker --version` and NOT `docker version --format {{.Client.Version}}`:
    # the latter contacts the daemon and exits non-zero when it is unreachable,
    # so on a machine with the CLI installed and Docker Desktop stopped it
    # reports the client version as unknown — conflating the two facts this
    # function exists to keep apart.
    cli = _run([cli_path, "--version"])
    if cli["ok"]:
        m = re.search(r"([0-9]+\.[0-9][0-9A-Za-z.\-]*)", cli["stdout"] or "")
        out["cli_version"] = m.group(1) if m else (cli["stdout"] or "").strip() or None

    # Server version only succeeds when a daemon is actually reachable.
    daemon = _run([cli_path, "version", "--format", "{{.Server.Version}}"])
    if daemon["ok"] and (daemon["stdout"] or "").strip():
        out["daemon_available"] = True
        out["daemon_version"] = daemon["stdout"].strip()
    else:
        out["daemon_error"] = daemon["reason"]

    return out


def probe_platform() -> dict:
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "executable": redact_path(sys.executable),
    }


def engine_ready(tesseract: dict | None = None) -> tuple[bool, list[str]]:
    """Can an accuracy benchmark legitimately run on this machine?

    Returns (ready, reasons). Requires both an invocable binary and every
    required language pack: a run missing `urd` would quietly become an
    English-only benchmark whose headline number describes a different product.
    """
    t = tesseract if tesseract is not None else probe_tesseract()
    reasons: list[str] = []
    if not t.get("available"):
        reasons.append("tesseract binary not available on PATH")
    missing = list(t.get("languages_missing") or [])
    if missing:
        reasons.append("missing language packs: " + ", ".join(missing))
    return (not reasons), reasons


def probe() -> dict:
    """The whole picture, JSON-serialisable and free of private paths."""
    tesseract = probe_tesseract()
    ready, reasons = engine_ready(tesseract)
    return {
        "schema": "ocr_capability_probe/1",
        "platform": probe_platform(),
        "tesseract": tesseract,
        "python_packages": probe_python_packages(),
        "docker": probe_docker(),
        "engine_ready_for_benchmark": ready,
        "engine_blockers": reasons,
    }


def main() -> int:
    report = probe()
    print(json.dumps(report, indent=2, sort_keys=True))
    # Exit 0 whether or not the engine is present: "the engine is missing" is a
    # successful probe, not a probe failure, and a CI step that treats it as an
    # error teaches people to ignore the step.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
