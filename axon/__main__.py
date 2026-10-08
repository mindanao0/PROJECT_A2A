"""`axon` / `python -m axon`: the GUI when run alone, otherwise the command line (axon.cli). Stdlib only, Python 3.11+."""
import argparse
import os
from pathlib import Path
import signal
import stat
import sys
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


def gui_args(parser):
    parser.add_argument("--port", type=int, help="loopback port (default: [server] port in config.toml, 8765; 0 = any free port)")
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "axon")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--sim", action="store_true", help="simulation only: a fake agent, no repositories, no sandbox")
    parser.add_argument("--real", action="store_true", help=argparse.SUPPRESS)  # the default now; kept for old scripts
    parser.add_argument("--no-runner", action="store_true", help="GUI only; run the agents with `axon run` in a terminal")


def run_gui(args):
    from . import runtime as real
    cfg = real.load_config()["server"] if not args.sim else {"port": 0, "hosts": []}
    port = cfg["port"] if args.port is None else args.port
    if not 0 <= port <= 65535:
        raise SystemExit("Port must be between 0 and 65535")
    state_dir = private_dir(args.state_dir)
    # Protect DB, WAL, lock and launch-link files from other local users.
    os.umask(0o077)
    import fcntl
    lock_fd = os.open(state_dir / "runtime.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    launch_file = state_dir / "launch.url"
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        try:  # already running (e.g. the service): open that one
            launch = launch_file.read_text().strip()
        except OSError:
            raise SystemExit("Another Axon instance is already using this state directory")
        print(f"Axon is already running: {launch}", file=sys.stderr)
        if not args.no_browser:
            webbrowser.open(launch)
        return 0
    if args.sim:
        runtime = Runtime(state_dir / "control.sqlite3")
    else:
        from .bridge import Bridge
        runtime = Bridge(runner=not args.no_runner)
    try:
        server = ControlServer(runtime, port, hosts=cfg["hosts"], password_file=None if args.sim else real.config_dir() / "password")
    except OSError as e:
        runtime.close()
        raise SystemExit(f"Cannot listen on 127.0.0.1:{port} ({e.strerror}); pick another with --port")
    stopped = threading.Event()

    def worker():
        while not stopped.wait(0.25):
            runtime.tick()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    launch = server.origin + "/#token=" + server.token
    # Fragment is consumed into browser memory and removed; never sent in HTTP URLs.
    fd = os.open(launch_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(launch + "\n")
    print("Axon · SIMULATION ONLY · no provider sessions or workspace writes" if args.sim
          else "Axon · agents run sandboxed on your projects", flush=True)
    print(f"Open locally: {launch}", flush=True)
    for host in cfg["hosts"]:
        print(f"Remote: https://{host} (password sign-in)", flush=True)
    if not args.no_browser:
        webbrowser.open(launch)
    signal.signal(signal.SIGTERM, signal.default_int_handler)  # systemctl stop: shut down like Ctrl-C
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


def main(argv=None):
    from . import cli
    return cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
