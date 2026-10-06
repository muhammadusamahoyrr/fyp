"""One-command OFFLINE Document Analyzer demo (FYP presentation; never deployed).

    venv\\Scripts\\python scripts\\analyzer_demo.py start     # replset + backend + frontend, prints URLs
    venv\\Scripts\\python scripts\\analyzer_demo.py status
    venv\\Scripts\\python scripts\\analyzer_demo.py stop      # stops ONLY what `start` started
    venv\\Scripts\\python scripts\\analyzer_demo.py reset     # lists the demo databases it would drop
    venv\\Scripts\\python scripts\\analyzer_demo.py reset --yes
    venv\\Scripts\\python scripts\\analyzer_demo.py fixtures  # (re)writes the three synthetic PDFs

What `start` does, in order, failing loudly at each step:
  1. refuses if a previous demo is still running, or if a port is taken (it
     names the holder; it never stops it -- choose another port with
     --backend-port / --frontend-port);
  2. reuses the local dev replica set on 127.0.0.1:27018, or starts it
     (scripts/dev_mongo_replset.py) and remembers that it did;
  3. writes the synthetic demo PDFs;
  4. builds the frontend into frontend/.next-build when the build is missing,
     older than the source, or made for another backend port;
  5. starts the backend demo server (scripts/_analyzer_demo_server.py) on a
     FRESH database `aai_demo_<hex>` with demo mode on, and `next start`;
  6. waits until both answer, and prints the URLs and where the (generated,
     per-start) demo account passwords are -- never the passwords themselves.

Nothing here edits `.env` / `.env.local`: every setting is process-scoped. All
runtime state (pids, logs, accounts, uploads, fixtures) lives OUTSIDE the
repository, in --state-dir (default: %TEMP%\\attorney-ai-analyzer-demo).
`stop` stops a process only if its pid AND start time match what `start`
recorded. `reset` drops only databases `start` recorded, only on this machine,
only named aai_demo_<suffix>, and only with --yes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
FRONTEND = ROOT / "frontend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

DEFAULT_STATE = Path(tempfile.gettempdir()) / "attorney-ai-analyzer-demo"
BACKEND_PORT, FRONTEND_PORT, MONGO_PORT = 8765, 3765, 27018
DIST = ".next-build"
BUILD_MARKER = "analyzer-demo-build.json"
VENV_PY = BACKEND / "venv" / "Scripts" / "python.exe"
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable      # the backend's own interpreter
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class DemoRefused(RuntimeError):
    pass


#: The backup launcher's own databases: fresh, local, and named for it, so
#: `reset` can never reach the application's database.
DEMO_DB_NAME = re.compile(r"^aai_demo_[a-z0-9]{4,40}$")


def check_database(mongodb_url: str, db_name: str) -> None:
    """Refuse anything but a local, dedicated backup-demo database."""
    from app.services.analyzer import simulated_provider
    if not simulated_provider.local_database(mongodb_url):
        raise DemoRefused("the demo runs only against a database on this machine")
    if not DEMO_DB_NAME.match(db_name or ""):
        raise DemoRefused("the demo runs only against a database named aai_demo_<suffix>")


def mongo_url(port: int) -> str:
    return f"mongodb://127.0.0.1:{port}/?replicaSet=rs0"


# ── state ───────────────────────────────────────────────────────────────────

def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def check_state_dir(state: Path) -> None:
    """Runtime state (passwords file, logs, uploads) must never land in Git."""
    try:
        state.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise SystemExit(f"refused: --state-dir must be outside the repository ({ROOT})")


# ── processes and ports ─────────────────────────────────────────────────────

def record(pid: int) -> dict:
    import psutil
    return {"pid": pid, "create_time": psutil.Process(pid).create_time()}


def owned(rec: dict | None):
    """The live process `rec` describes -- only if its pid AND start time still
    match (a reused pid is someone else's process). Otherwise None."""
    import psutil
    if not rec:
        return None
    try:
        proc = psutil.Process(rec["pid"])
        return proc if abs(proc.create_time() - rec["create_time"]) < 0.01 and proc.is_running() else None
    except (psutil.Error, KeyError, TypeError):
        return None


def port_holder(port: int) -> str | None:
    """None when 127.0.0.1:port is free; otherwise who holds it, for the message."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return None
        except OSError:
            pass
    import psutil
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN and c.pid:
                try:
                    return f"pid {c.pid} ({psutil.Process(c.pid).name()})"
                except psutil.Error:
                    return f"pid {c.pid}"
    except psutil.Error:
        pass
    return "an unknown process"


def _stop_tree(proc, timeout: float = 10) -> None:
    import psutil
    procs = proc.children(recursive=True) + [proc]
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    psutil.wait_procs(procs, timeout=timeout)


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _wait(what: str, check, proc, timeout: float, log: Path) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        if proc is not None and proc.poll() is not None:
            raise StartFailed(f"{what} exited (code {proc.returncode}). Last lines of {log}:\n{_tail(log)}")
        time.sleep(1)
    raise StartFailed(f"{what} did not become ready in {int(timeout)}s. Last lines of {log}:\n{_tail(log)}")


def _tail(path: Path, n: int = 15) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return "(no log)"


class StartFailed(RuntimeError):
    pass


# ── the replica set ─────────────────────────────────────────────────────────

def replset_up(port: int) -> bool:
    from pymongo import MongoClient
    try:
        with MongoClient(f"mongodb://127.0.0.1:{port}/?directConnection=true", serverSelectionTimeoutMS=1500) as c:
            return bool(c.admin.command("hello").get("setName"))
    except Exception:
        return False


# ── the frontend build ──────────────────────────────────────────────────────

def source_fingerprint() -> str:
    """Changes whenever a file that shapes the production build changes."""
    h = hashlib.sha256()
    files = [FRONTEND / n for n in ("next.config.js", "package.json", "package-lock.json", "jsconfig.json")]
    for top in ("src", "public"):
        for dirpath, _, names in os.walk(FRONTEND / top):
            files += [Path(dirpath) / n for n in names]
    for f in sorted(files):
        try:
            st = f.stat()
        except OSError:
            continue
        h.update(f"{f.relative_to(FRONTEND)}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def build_needed(backend_port: int) -> str | None:
    marker = _load(FRONTEND / DIST / BUILD_MARKER, None)
    if not (FRONTEND / DIST / "BUILD_ID").exists() or marker is None:
        return "no demo build yet"
    if marker.get("api_proxy_target") != f"http://127.0.0.1:{backend_port}":
        return "the existing build points at another backend port"
    if marker.get("source") != source_fingerprint():
        return "the frontend source changed since the last build"
    return None


def _node_env(backend_port: int) -> dict:
    env = os.environ.copy()
    env.update({"NEXT_DIST_DIR": DIST, "API_PROXY_TARGET": f"http://127.0.0.1:{backend_port}",
                "NEXT_TELEMETRY_DISABLED": "1", "NODE_ENV": "production"})
    return env


def build_frontend(backend_port: int, state: Path) -> None:
    log = state / "frontend-build.log"
    print(f"  building the frontend (a few minutes; log: {log}) ...", flush=True)
    with log.open("w", encoding="utf-8") as out:
        code = subprocess.call(["node", "node_modules/next/dist/bin/next", "build"], cwd=FRONTEND,
                               env=_node_env(backend_port), stdout=out, stderr=subprocess.STDOUT)
    if code != 0:
        raise StartFailed(f"the frontend build failed (code {code}). Last lines of {log}:\n{_tail(log)}")
    _save(FRONTEND / DIST / BUILD_MARKER, {"api_proxy_target": f"http://127.0.0.1:{backend_port}",
                                           "source": source_fingerprint()})


# ── commands ────────────────────────────────────────────────────────────────

def cmd_fixtures(args) -> int:
    import analyzer_demo_fixtures
    out = args.out or (args.state_dir / "fixtures")
    for path in analyzer_demo_fixtures.build(out):
        print(f"  {path}")
    return 0


def cmd_start(args) -> int:
    state_dir: Path = args.state_dir
    check_state_dir(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    run_file = state_dir / "run.json"
    run = _load(run_file, {})
    if owned(run.get("backend")) or owned(run.get("frontend")):
        print("A demo is already running. `status` shows it; `stop` stops it.")
        return 1
    for name, port in (("backend", args.backend_port), ("frontend", args.frontend_port)):
        holder = port_holder(port)
        if holder:
            print(f"REFUSING TO START: port {port} (demo {name}) is held by {holder}.\n"
                  f"  The demo never stops another program. Close it yourself, or pick a free port:\n"
                  f"  analyzer_demo.py start --{name}-port <another port>")
            return 2

    db_name = f"aai_demo_{secrets.token_hex(4)}"
    check_database(mongo_url(args.mongo_port), db_name)
    started = {"backend_port": args.backend_port, "frontend_port": args.frontend_port,
               "mongo_port": args.mongo_port, "db_name": db_name, "started_at": time.time()}
    for stale in ("backend.stop", "backend.ready.json", "backend.exit.json", "accounts.json"):
        (state_dir / stale).unlink(missing_ok=True)
    try:
        print("[1/5] database")
        if replset_up(args.mongo_port):
            print(f"  reusing the replica set on 127.0.0.1:{args.mongo_port}")
            started["mongo_started_by_demo"] = False
        else:
            print(f"  starting the dev replica set on 127.0.0.1:{args.mongo_port}")
            code = subprocess.call([PY, str(BACKEND / "scripts" / "dev_mongo_replset.py"),
                                    "--port", str(args.mongo_port)], cwd=BACKEND)
            if code != 0 or not replset_up(args.mongo_port):
                raise StartFailed("the replica set did not start (see the output above; is MongoDB installed?)")
            started["mongo_started_by_demo"] = True
        history = _load(state_dir / "databases.json", [])
        _save(state_dir / "databases.json", history + [{"db_name": db_name, "mongo_port": args.mongo_port}])
        _save(run_file, started)

        print("[2/5] synthetic demo documents")
        cmd_fixtures(argparse.Namespace(out=None, state_dir=state_dir))

        print("[3/5] frontend build")
        why = "--rebuild was given" if args.rebuild else build_needed(args.backend_port)
        if why:
            print(f"  rebuilding: {why}")
            build_frontend(args.backend_port, state_dir)
        else:
            print("  the existing build is current")

        print("[4/5] backend (demo mode, fresh database)")
        log = state_dir / "backend.log"
        with log.open("a", encoding="utf-8") as out:
            out.write(f"\n=== analyzer demo start {time.strftime('%Y-%m-%d %H:%M:%S')} db={db_name} ===\n")
            out.flush()
            backend = subprocess.Popen(
                [PY, str(BACKEND / "scripts" / "_analyzer_demo_server.py"),
                 "--port", str(args.backend_port), "--frontend-port", str(args.frontend_port),
                 "--mongo", mongo_url(args.mongo_port), "--db-name", db_name, "--state", str(state_dir)],
                cwd=BACKEND, stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        started["backend"] = record(backend.pid)
        _save(run_file, started)
        ready_file = state_dir / "backend.ready.json"
        _wait("the backend", lambda: ready_file.exists() and _http_ok(f"http://127.0.0.1:{args.backend_port}/"),
              backend, 180, log)
        ready = _load(ready_file, {})
        if not (ready.get("ai_provider") == "simulated" and ready.get("analyzer_ready")):
            raise StartFailed(f"the backend started but the analyzer is not ready: {ready.get('analyzer_problems')}")

        print("[5/5] frontend")
        flog = state_dir / "frontend.log"
        with flog.open("a", encoding="utf-8") as out:
            frontend = subprocess.Popen(
                ["node", "node_modules/next/dist/bin/next", "start", "-p", str(args.frontend_port),
                 "-H", "127.0.0.1"], cwd=FRONTEND, env=_node_env(args.backend_port),
                stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        started["frontend"] = record(frontend.pid)
        _save(run_file, started)
        _wait("the frontend", lambda: _http_ok(f"http://127.0.0.1:{args.frontend_port}/login"), frontend, 90, flog)
    except (StartFailed, KeyboardInterrupt) as e:
        print(f"\nSTART FAILED: {e}\nStopping what this start launched ...", file=sys.stderr)
        _save(run_file, started)
        cmd_stop(args, quiet=True)
        return 1

    print(f"""
Analyzer demo is up (OFFLINE: simulated AI, synthetic documents only).
  Open:        http://127.0.0.1:{args.frontend_port}/login
  Backend:     http://127.0.0.1:{args.backend_port}  (database {db_name} on 127.0.0.1:{args.mongo_port})
  Accounts:    {state_dir / 'accounts.json'}   (passwords are generated for this start)
  Documents:   {state_dir / 'fixtures'}
  Logs:        {state_dir}
  Stop:        venv\\Scripts\\python scripts\\analyzer_demo.py stop""")
    return 0


def cmd_stop(args, quiet: bool = False) -> int:
    state_dir: Path = args.state_dir
    run_file = state_dir / "run.json"
    run = _load(run_file, {})
    if not run:
        print("No demo recorded as running.")
        return 0
    backend = owned(run.get("backend"))
    if backend:
        (state_dir / "backend.stop").write_text("stop", encoding="utf-8")
        try:
            backend.wait(timeout=30)
            print("  backend stopped (graceful)")
        except Exception:
            _stop_tree(backend)
            print("  backend did not stop within 30s; stopped its own process tree")
    elif run.get("backend"):
        print("  backend: not running (or the pid now belongs to another program -- left alone)")
    frontend = owned(run.get("frontend"))
    if frontend:
        _stop_tree(frontend)
        print("  frontend stopped")
    elif run.get("frontend"):
        print("  frontend: not running (or the pid now belongs to another program -- left alone)")
    if run.get("mongo_started_by_demo"):
        subprocess.call([PY, str(BACKEND / "scripts" / "dev_mongo_replset.py"),
                         "--port", str(run["mongo_port"]), "--stop"], cwd=BACKEND)
        print("  replica set stopped (the demo had started it)")
    elif not quiet:
        print("  replica set left running (it was already running before the demo)")
    (state_dir / "backend.stop").unlink(missing_ok=True)
    (state_dir / "accounts.json").unlink(missing_ok=True)       # this start's passwords are now useless
    run_file.unlink(missing_ok=True)
    print(f"Stopped. The demo database {run.get('db_name')} is kept; `reset` lists what it would drop.")
    return 0


def cmd_status(args) -> int:
    run = _load(args.state_dir / "run.json", {})
    if not run:
        print("Not running.")
        return 0
    for name in ("backend", "frontend"):
        print(f"  {name:9} {'running' if owned(run.get(name)) else 'NOT running'}"
              f"  port {run.get(name + '_port')}")
    print(f"  database  {run.get('db_name')} on 127.0.0.1:{run.get('mongo_port')}"
          f" ({'started by the demo' if run.get('mongo_started_by_demo') else 'pre-existing replica set'})")
    print(f"  open      http://127.0.0.1:{run.get('frontend_port')}/login")
    return 0


def reset_plan(history: list, mongo_port: int) -> list[str]:
    """The recorded demo databases that `reset --yes` would drop (validated)."""
    names = []
    for entry in history:
        name = entry.get("db_name", "")
        check_database(mongo_url(entry.get("mongo_port", mongo_port)), name)   # raises otherwise
        names.append(name)
    return sorted(set(names))


def cmd_reset(args) -> int:
    from pymongo import MongoClient

    state_dir: Path = args.state_dir
    check_state_dir(state_dir)
    run = _load(state_dir / "run.json", {})
    if owned(run.get("backend")) or owned(run.get("frontend")):
        print("refused: the demo is running. `stop` it first.")
        return 1
    history = _load(state_dir / "databases.json", [])
    try:
        names = reset_plan(history, args.mongo_port)
    except DemoRefused as e:
        print(f"refused: the recorded list contains something that is not a local demo database ({e}).")
        return 2
    if not replset_up(args.mongo_port):
        print(f"The replica set on 127.0.0.1:{args.mongo_port} is not running; start it with "
              f"`venv\\Scripts\\python scripts\\dev_mongo_replset.py` and run reset again.")
        return 1
    with MongoClient(mongo_url(args.mongo_port), serverSelectionTimeoutMS=5000) as client:
        present = [n for n in names if n in client.list_database_names()]
        uploads = [state_dir / "uploads" / n for n in names if (state_dir / "uploads" / n).exists()]
        if not present and not uploads:
            print("Nothing to reset: no recorded demo database exists.")
            _save(state_dir / "databases.json", [])
            return 0
        print("reset would delete ONLY these (recorded by `start`, local, named aai_demo_*):")
        for n in present:
            print(f"  database {n} on 127.0.0.1:{args.mongo_port}")
        for u in uploads:
            print(f"  folder   {u}")
        if not args.yes:
            print("Nothing deleted. Run `reset --yes` to delete exactly the above.")
            return 1
        for n in present:
            check_database(mongo_url(args.mongo_port), n)
            client.drop_database(n)
    for u in uploads:
        if u.parent == state_dir / "uploads" and DEMO_DB_NAME.match(u.name):
            shutil.rmtree(u)
    _save(state_dir / "databases.json", [])
    print("Reset done.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("start", "stop", "status", "reset", "fixtures"))
    parser.add_argument("--backend-port", type=int, default=BACKEND_PORT)
    parser.add_argument("--frontend-port", type=int, default=FRONTEND_PORT)
    parser.add_argument("--mongo-port", type=int, default=MONGO_PORT)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--rebuild", action="store_true", help="start: rebuild the frontend even if current")
    parser.add_argument("--yes", action="store_true", help="reset: really delete the listed demo data")
    parser.add_argument("--out", type=Path, default=None, help="fixtures: where to write the PDFs")
    args = parser.parse_args(argv)
    return {"start": cmd_start, "stop": cmd_stop, "status": cmd_status, "reset": cmd_reset,
            "fixtures": cmd_fixtures}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
