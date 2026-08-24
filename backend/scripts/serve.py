"""serve.py — start and gracefully stop the backend on Windows.

    python scripts/serve.py start [--local-only] [-- <uvicorn args>]
    python scripts/serve.py stop
    python scripts/serve.py status

Why this exists
---------------
threshold_manager batches samples and flushes every 25; the lifespan shutdown
writes the remainder out so a stop doesn't discard it. That fix only helps if
the process is actually signalled -- and on Windows a detached console process
cannot be. `taskkill /PID` without /F returns:

    ERROR: The process ... can only be terminated forcefully (with /F option)

and /F runs no shutdown code at all, so the buffered remainder dies with it.
There is no SIGTERM to fall back on.

The obvious Windows answer -- a CTRL_BREAK console control event -- does not
work here, and it fails in a way worth recording so nobody re-attempts it:
GenerateConsoleCtrlEvent can only signal process groups attached to the
CALLER's console, so a `stop` invoked from a separate shell gets

    WinError 87: The parameter is incorrect

no matter how the child was created. Attaching to the target's console first is
possible but fragile, and breaks entirely once the launching console is gone.

So the trigger is a sentinel file instead of a signal. `start` runs uvicorn
programmatically in a child that holds the Server object and watches for the
sentinel; `stop` creates it. The child sets `server.should_exit`, which is
uvicorn's own graceful path -- identical to Ctrl+C, lifespan shutdown runs, the
threshold buffer flushes. No consoles, no signals, no platform quirks.

`stop` forces a kill only after the graceful path has had time, and says
plainly when it had to, because that is the case where samples were lost.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND   = Path(__file__).resolve().parents[1]
PID_FILE  = BACKEND / ".serve.pid"
STOP_FILE = BACKEND / ".serve.stop"
LOG_FILE  = BACKEND / "serve.log"

# Long enough for shutdown to flush Redis and close Mongo/Chroma -- but the
# real driver is in-flight work. uvicorn waits for open requests to finish, and
# one turn against a CPU-bound local model can hold a connection for minutes
# (measured: a single triage call at 240s). A grace shorter than the slowest
# in-flight request turns every stop into a forced kill, which is exactly the
# buffer loss the graceful path exists to prevent. Override with --grace.
DEFAULT_GRACE_SECONDS = 300


def _running(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                         capture_output=True, text=True).stdout
    return str(pid) in out


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = json.loads(PID_FILE.read_text())["pid"]
    except Exception:
        return None
    return pid if _running(pid) else None


def _port_holder(host: str, port: int) -> int | None:
    """PID already listening on host:port, if any.

    The pid file is not enough. It only knows about servers THIS script started,
    so an instance left over from another shell — or one whose pid file was
    cleaned up — is invisible to it. Asking the OS is the only reliable check.
    """
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    except Exception:
        return None
    needle = f"{host}:{port}"
    for line in out.splitlines():
        parts = line.split()
        # Columns: Proto  Local  Foreign  State  PID. Compare the LOCAL address
        # as a whole token — a substring test reports the holder of :8000 when
        # asked about :800, since one is a prefix of the other.
        if len(parts) >= 5 and parts[1] == needle and parts[3] == "LISTENING":
            if parts[-1].isdigit():
                return int(parts[-1])
    return None


def start(args) -> int:
    if (pid := _read_pid()):
        print(f"already running (pid {pid}). Use `stop` first.")
        return 1

    # Refuse to start on an occupied port. Without this, uvicorn binds, fails
    # with [Errno 10048], and dies — while this script has already printed
    # "started pid N -> http://...". The old server keeps answering, so the port
    # looks healthy and the operator believes their new build is live when it is
    # not. That cost a debugging session: a UI bug was investigated against a
    # server running different code, and the truncated log (see below) hid it.
    if (holder := _port_holder(args.host, args.port)):
        print(f"  REFUSING TO START: {args.host}:{args.port} is already held by "
              f"pid {holder}.")
        print(f"  That process is serving right now — anything you test will hit "
              f"IT, not this build.")
        print(f"  Stop it first:  python scripts/serve.py stop")
        print(f"  Or if it is orphaned:  taskkill /PID {holder} /F")
        return 1

    env = os.environ.copy()
    if args.local_only:
        env["LLM_LOCAL_ONLY"] = "true"
        print("  LLM_LOCAL_ONLY=true — the cloud chain is disabled; a local "
              "failure will error rather than become a paid request.")

    STOP_FILE.unlink(missing_ok=True)   # a stale sentinel would stop it at once

    cmd = [str(BACKEND / "venv" / "Scripts" / "python.exe"),
           str(Path(__file__).resolve()), "_child",
           "--host", args.host, "--port", str(args.port)]

    # APPEND, never truncate. Opening "w" destroyed the log of whatever was
    # already running — including the access lines needed to see whether a
    # user's click ever reached the server. Losing that evidence is worse than
    # a large file, and the banner below keeps runs separable.
    log = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    log.write(f"\n{'=' * 70}\n=== serve.py start {datetime.now().isoformat(timespec='seconds')} "
              f"— {args.host}:{args.port}"
              f"{' — LLM_LOCAL_ONLY' if args.local_only else ''}\n{'=' * 70}\n")
    log.flush()
    proc = subprocess.Popen(cmd, cwd=str(BACKEND), env=env, stdout=log,
                            stderr=subprocess.STDOUT)
    PID_FILE.write_text(json.dumps({"pid": proc.pid, "started": time.time()}))

    print(f"  started pid {proc.pid} -> http://{args.host}:{args.port}")
    print(f"  log: {LOG_FILE}")
    print("  stop it with `python scripts/serve.py stop` so buffered threshold "
          "samples flush.")
    return 0


def child(args) -> int:
    """The server process. Holds the uvicorn Server so a watcher thread can ask
    it to exit gracefully -- the same path Ctrl+C takes."""
    import threading

    import uvicorn

    # uvicorn.exe puts the working directory on sys.path; the programmatic
    # Server does not, so "app.main" would not import.
    sys.path.insert(0, str(BACKEND))

    config = uvicorn.Config("app.main:app", host=args.host, port=args.port,
                            log_level="info")
    server = uvicorn.Server(config)

    def _watch() -> None:
        while not STOP_FILE.exists():
            time.sleep(0.5)
        print("serve: stop sentinel seen — shutting down gracefully.", flush=True)
        server.should_exit = True

    threading.Thread(target=_watch, daemon=True).start()
    server.run()
    return 0


def stop(args) -> int:
    pid = _read_pid()
    if not pid:
        print("not running (no live pid recorded).")
        PID_FILE.unlink(missing_ok=True)
        STOP_FILE.unlink(missing_ok=True)
        return 0

    print(f"  asking pid {pid} to stop (graceful; flushes the buffer). "
          f"Waiting up to {getattr(args, 'grace', DEFAULT_GRACE_SECONDS)}s for "
          f"in-flight requests...")
    STOP_FILE.write_text("stop")

    grace = getattr(args, "grace", DEFAULT_GRACE_SECONDS)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not _running(pid):
            print("  stopped gracefully — shutdown ran, buffered samples flushed.")
            PID_FILE.unlink(missing_ok=True)
            STOP_FILE.unlink(missing_ok=True)
            return 0
        time.sleep(0.5)

    print(f"  still alive after {grace}s — forcing.")
    print("  *** WARNING: a forced kill runs no shutdown code. Up to "
          "_FLUSH_EVERY-1 buffered threshold samples were lost. ***")
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    PID_FILE.unlink(missing_ok=True)
    STOP_FILE.unlink(missing_ok=True)
    return 2


def status(args) -> int:
    pid = _read_pid()
    print(f"  {'running, pid ' + str(pid) if pid else 'not running'}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--local-only", action="store_true",
                   help="disable the paid cloud chain entirely")
    s.add_argument("uvicorn_args", nargs="*")
    s.set_defaults(func=start)

    c = sub.add_parser("_child", help=argparse.SUPPRESS)
    c.add_argument("--host", default="127.0.0.1")
    c.add_argument("--port", type=int, default=8000)
    c.set_defaults(func=child)

    st = sub.add_parser("stop")
    st.add_argument("--grace", type=int, default=DEFAULT_GRACE_SECONDS,
                    help="seconds to wait for in-flight requests before forcing")
    st.set_defaults(func=stop)
    sub.add_parser("status").set_defaults(func=status)

    args = p.parse_args()
    sys.exit(args.func(args))
