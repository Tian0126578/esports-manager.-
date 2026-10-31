# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

HOST = "0.0.0.0"
PORT = 8000
LOCAL_URL = f"http://127.0.0.1:{PORT}"
PUBLIC_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
STARTUP_TIMEOUT_SECONDS = 90


def _port_is_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind((HOST, PORT))
        except OSError:
            return False
    return True


def _read_tunnel_output(
    process: subprocess.Popen[str], output: queue.Queue[str | None]
) -> None:
    if process.stdout is None:
        output.put(None)
        return
    for line in process.stdout:
        print(f"[cloudflared] {line}", end="", flush=True)
        output.put(line)
    output.put(None)


def _server_is_ready() -> bool:
    try:
        with urlopen(f"{LOCAL_URL}/health", timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    cloudflared = shutil.which("cloudflared")
    if cloudflared is None:
        print(
            "cloudflared is required for a public HTTPS tunnel.\n"
            "Windows: winget install --id Cloudflare.cloudflared\n"
            "macOS:   brew install cloudflared\n"
            "Linux:   follow https://developers.cloudflare.com/cloudflare-one/"
            "connections/connect-networks/downloads/",
            file=sys.stderr,
        )
        return 1

    if not _port_is_available():
        print(
            f"Port {PORT} is already in use. Stop the existing game server, "
            "then run this script again.",
            file=sys.stderr,
        )
        return 1

    server: subprocess.Popen[str] | None = None
    tunnel: subprocess.Popen[str] | None = None
    try:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "dev:app",
                "--host",
                HOST,
                "--port",
                str(PORT),
            ],
            text=True,
        )
        tunnel = subprocess.Popen(
            [
                cloudflared,
                "--no-autoupdate",
                "tunnel",
                "--url",
                LOCAL_URL,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        tunnel_output: queue.Queue[str | None] = queue.Queue()
        output_thread = threading.Thread(
            target=_read_tunnel_output,
            args=(tunnel, tunnel_output),
            daemon=True,
        )
        output_thread.start()

        public_url = None
        server_ready = False
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if server.poll() is not None:
                print("The game server exited before becoming ready.", file=sys.stderr)
                return 1
            if tunnel.poll() is not None:
                print("cloudflared exited before creating a public URL.", file=sys.stderr)
                return 1

            try:
                line = tunnel_output.get(timeout=0.25)
            except queue.Empty:
                line = ""
            if line is None:
                print("cloudflared stopped before creating a public URL.", file=sys.stderr)
                return 1
            if line:
                match = PUBLIC_URL_PATTERN.search(line)
                if match:
                    public_url = match.group(0)

            if not server_ready:
                server_ready = _server_is_ready()
            if public_url and server_ready:
                break
        else:
            print(
                f"Startup timed out after {STARTUP_TIMEOUT_SECONDS} seconds.",
                file=sys.stderr,
            )
            return 1

        print()
        print("=" * 60)
        print("🎮 ESPORTS MANAGER HAS BEEN LAUNCHED TO THE INTERNET! 🎮")
        print(f"- Link nội bộ máy này:    http://localhost:{PORT}")
        print(f"- Link chia sẻ INTERNET:  {public_url}")
        print("👉 Chia sẻ link HTTPS để bạn bè truy cập từ mạng khác.")
        print("⚠️ Bất kỳ ai có link đều có thể truy cập. Dừng bằng Ctrl+C.")
        print("=" * 60)

        while server.poll() is None and tunnel.poll() is None:
            time.sleep(0.5)
        if server.poll() is not None:
            print("The game server stopped.", file=sys.stderr)
            return 1
        print("The public tunnel stopped.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopping the public tunnel and game server...")
        return 0
    finally:
        _stop_process(tunnel)
        _stop_process(server)


if __name__ == "__main__":
    raise SystemExit(main())
