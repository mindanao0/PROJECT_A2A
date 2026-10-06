"""Run with `python -m navis`; stdlib only, Python 3.11+."""
import argparse
import os
from pathlib import Path
import stat
import threading
import webbrowser

from .core import Runtime
from .server import ControlServer


def private_dir(path):
    path = path.expanduser()
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise SystemExit("State directory must be owned by this user with permissions 0700")
    return path


def main():
    parser = argparse.ArgumentParser(description="Navis local GUI · simulated agent only")
    parser.add_argument("--port", type=int, default=0, help="Loopback port (default: random free port)")
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "navis")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--real", action="store_true",
                        help="drive the real runtime (sandboxed agents, projects from ~/.config/navis/projects)")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535")
    state_dir = private_dir(args.state_dir)
    # Protect DB, WAL, lock and launch-link files from other local users.
    os.umask(0o077)
    import fcntl
    lock_fd = os.open(state_dir / "runtime.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        raise SystemExit("Another Navis instance is already using this state directory")
    if args.real:
        from .bridge import Bridge
        runtime = Bridge()
    else:
        runtime = Runtime(state_dir / "control.sqlite3")
    server = ControlServer(runtime, args.port)
    stopped = threading.Event()

    def worker():
        while not stopped.wait(0.25):
            runtime.tick()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    launch = server.origin + "/#token=" + server.token
    # Fragment is consumed into browser memory and removed; never sent in HTTP URLs.
    launch_file = state_dir / "launch.url"
    fd = os.open(launch_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(launch + "\n")
    print("Navis · REAL RUNTIME · agents run sandboxed on your projects" if args.real
          else "Navis · SIMULATION ONLY · no provider sessions or workspace writes", flush=True)
    print(f"Open locally: {launch}", flush=True)
    if not args.no_browser:
        webbrowser.open(launch)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        thread.join(timeout=2)
        server.server_close()
        runtime.close()
        launch_file.unlink(missing_ok=True)
        os.close(lock_fd)


if __name__ == "__main__":
    main()
