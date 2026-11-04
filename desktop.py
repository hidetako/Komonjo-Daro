"""デスクトップ起動用エントリ（インストーラー版の実行ファイルはこれ）。

- 空きポートで Flask を起動
- Edge / Chrome があれば --app モード（アドレスバーなしの独立ウィンドウ）で開く。無ければ既定ブラウザ
- タスクトレイにアイコンを出し、「開く」「終了」をそこから操作
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from kobun import APP_NAME
from kobun.config import ROOT


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def open_window(url: str) -> None:
    candidates = []
    if sys.platform == "win32":
        pf = [os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("ProgramFiles", r"C:\Program Files"),
              os.environ.get("LOCALAPPDATA", "")]
        for base in pf:
            candidates += [Path(base) / r"Microsoft\Edge\Application\msedge.exe", Path(base) / r"Google\Chrome\Application\chrome.exe"]
    for exe in candidates:
        if exe and Path(exe).exists():
            subprocess.Popen([str(exe), f"--app={url}", "--window-size=1400,900"])
            return
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        if shutil.which(name):
            subprocess.Popen([shutil.which(name), f"--app={url}"])
            return
    webbrowser.open(url)


def wait_ready(port: int, timeout: float = 30) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def run_tray(url: str) -> None:
    try:
        import pystray
        from PIL import Image
    except ImportError:
        return
    icon_path = ROOT / "packaging" / "icon.png"
    image = Image.open(icon_path) if icon_path.exists() else Image.new("RGB", (64, 64), "#7a1f1f")
    menu = pystray.Menu(
        pystray.MenuItem("開く", lambda: open_window(url), default=True),
        pystray.MenuItem("終了", lambda icon: (icon.stop(), os._exit(0))),
    )
    pystray.Icon(APP_NAME, image, APP_NAME, menu).run()


def main() -> None:
    port = int(os.environ.get("KOBUN_PORT") or free_port())
    os.environ["KOBUN_PORT"] = str(port)
    from app import create_app
    flask_app = create_app()
    threading.Thread(target=lambda: flask_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False), daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    if wait_ready(port):
        open_window(url)
    run_tray(url)       # トレイが使えない環境ではすぐ戻るので、その場合はサーバーを待ち続ける
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
