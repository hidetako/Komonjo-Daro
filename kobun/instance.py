"""多重起動の防止。

起動中のアプリは instance.json にポートを記録し、/ping に応答する。
2 つ目の起動は、それを見つけたら新しいサーバーを立てずに、既存のウィンドウを開いて終了する。
Windows では名前付きミューテックスも併用し、同時起動（ダブルクリック連打）でも 1 つに絞る。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from . import APP_NAME

PING_TEXT = "komonjo-daro"
_mutex_handle = None


def instance_file() -> Path:
    if os.environ.get("KOBUN_INSTANCE_FILE"):
        return Path(os.environ["KOBUN_INSTANCE_FILE"])
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME if sys.platform == "win32" else Path.home() / ".cache" / "komonjo-daro"
    return base / "instance.json"


def ping(port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=timeout) as r:
            return r.read().decode("utf-8", "replace").startswith(PING_TEXT)
    except Exception:  # noqa: BLE001
        return False


def running_port() -> int | None:
    """動いている既存インスタンスのポート。無ければ None。"""
    f = instance_file()
    try:
        port = int(json.loads(f.read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return port if ping(port) else None


def write(port: int) -> None:
    f = instance_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"port": port, "pid": os.getpid(), "started": time.time()}), encoding="utf-8")


def clear() -> None:
    try:
        f = instance_file()
        data = json.loads(f.read_text(encoding="utf-8"))
        if int(data.get("pid", -1)) == os.getpid():
            f.unlink()
    except Exception:  # noqa: BLE001
        pass


def acquire_mutex() -> bool:
    """Windows: 名前付きミューテックスを取る。既に他プロセスが持っていれば False。他 OS は常に True。"""
    global _mutex_handle
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        _mutex_handle = kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}-single-instance")
        return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001
        return True


def wait_running_port(timeout: float = 15.0) -> int | None:
    """同時起動で負けた側が、勝った側のサーバーが立つのを待つ。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        port = running_port()
        if port:
            return port
        time.sleep(0.5)
    return None
