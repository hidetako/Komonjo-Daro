"""GitHub Releases を使った自動アップデート。

- 起動時（設定で有効なら）にバックグラウンドで最新版を確認
- 新版があれば画面に通知。「更新」でインストーラーをダウンロードしてサイレント実行し、アプリを終了する
- インストーラー（Inno Setup）は更新後にアプリを再起動する
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import GITHUB_REPO, __version__
from .config import IS_FROZEN

ASSET_NAME = "Komonjo-Daro-Setup.exe"


def log_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Komonjo-Daro" if sys.platform == "win32" else Path.home() / ".cache" / "komonjo-daro"
    base.mkdir(parents=True, exist_ok=True)
    return base


def log(msg: str) -> None:
    """更新の経過を LOCALAPPDATA/Komonjo-Daro/update.log に残す（止まったときの診断用）。"""
    try:
        import time
        with open(log_dir() / "update.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:  # noqa: BLE001
        pass
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


@dataclass
class ReleaseInfo:
    version: str
    url: str          # インストーラーの直リンク（github.com/.../releases/download/...）
    notes: str
    page: str         # リリースページ
    api_url: str = ""  # 同じ資産の API エンドポイント。直リンクが 5xx のときの代替経路


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


RETRY_WAITS = (3.0, 8.0)   # GitHub の一時的な 5xx（504 Gateway Time-out など）に備えて 2 回まで再試行


def _open(req: urllib.request.Request, timeout: float, waits: tuple | None = None):
    """urlopen を 5xx・接続エラー・タイムアウトのときだけ再試行する。4xx はそのまま上げる。"""
    import time
    import urllib.error

    waits = RETRY_WAITS if waits is None else waits
    for i, wait in enumerate((*waits, None)):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code < 500 or wait is None:
                raise
            log(f"HTTP {e.code} ({req.full_url}) を {wait:.0f} 秒後に再試行 ({i + 1}/{len(waits)})")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if wait is None:
                raise
            log(f"{e} ({req.full_url}) を {wait:.0f} 秒後に再試行 ({i + 1}/{len(waits)})")
        time.sleep(wait)
    raise RuntimeError("unreachable")


def fetch_latest(timeout: float = 8.0) -> ReleaseInfo | None:
    req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "Komonjo-Daro"})
    with _open(req, timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET_NAME), None)
    if not asset or not asset.get("browser_download_url"):
        return None
    return ReleaseInfo(version=data.get("tag_name", "").lstrip("v"), url=asset["browser_download_url"],
                       notes=data.get("body", "") or "", page=data.get("html_url", ""), api_url=asset.get("url", "") or "")


def open_asset(info: ReleaseInfo, timeout: float = 60):
    """インストーラーを開く。直リンクが 5xx を返し続けるときは API の資産エンドポイントに切り替える。

    2026-11 に github.com/.../releases/download/ だけが 504 を返し、api.github.com 経由の取得は通る障害があった。
    """
    import urllib.error

    req = urllib.request.Request(info.url, headers={"User-Agent": "Komonjo-Daro"})
    try:
        return _open(req, timeout)
    except urllib.error.HTTPError as e:
        if e.code < 500 or not info.api_url:
            raise
        log(f"直リンクが HTTP {e.code} のため API 経由に切り替え: {info.api_url}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        if not info.api_url:
            raise
        log(f"直リンクが {e} のため API 経由に切り替え: {info.api_url}")
    req = urllib.request.Request(info.api_url, headers={"User-Agent": "Komonjo-Daro", "Accept": "application/octet-stream"})
    return _open(req, timeout)


class UpdateState:
    """アプリ全体で共有する更新状態。"""

    def __init__(self):
        self.latest: ReleaseInfo | None = None
        self.error: str = ""
        self.checked = False
        self.lock = threading.Lock()
        # ダウンロード進捗（画面のバー表示用）
        self.dl_status = "idle"        # idle | downloading | installing | error
        self.dl_done = 0
        self.dl_total = 0
        self.dl_error = ""

    def progress(self) -> dict:
        pct = int(self.dl_done * 100 / self.dl_total) if self.dl_total else 0
        return {"status": self.dl_status, "done": self.dl_done, "total": self.dl_total, "percent": pct, "error": self.dl_error,
                "version": self.latest.version if self.latest else ""}

    def start_update(self) -> None:
        """バックグラウンドでダウンロード→インストーラー起動→アプリ終了。進捗は progress() で見る。"""
        if self.dl_status in ("downloading", "installing"):
            return
        if not self.available:
            raise RuntimeError("新しいバージョンはありません")
        self.dl_status, self.dl_done, self.dl_total, self.dl_error = "downloading", 0, 0, ""

        def work():
            try:
                log(f"update start: {__version__} -> {self.latest.version} ({self.latest.url})")
                download_and_install(self.latest, on_progress=self._on_progress)
                if self.dl_total:
                    self.dl_done = self.dl_total
                self.dl_status = "installing"
                log("installer launched; exiting app")
                exit_app(1.0)
            except Exception as e:  # noqa: BLE001
                log(f"update failed: {e}")
                self.dl_status, self.dl_error = "error", str(e)

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        self.dl_done, self.dl_total = done, total

    @property
    def available(self) -> bool:
        return bool(self.latest and is_newer(self.latest.version))

    def check(self) -> None:
        with self.lock:
            try:
                self.latest = fetch_latest()
                self.error = ""
            except Exception as e:  # noqa: BLE001
                self.error = f"更新確認に失敗: {e}"
            self.checked = True

    def check_async(self) -> None:
        threading.Thread(target=self.check, daemon=True).start()


def download_and_install(info: ReleaseInfo, on_progress=None) -> Path:
    """インストーラーを取得してサイレント実行する。呼び出し側はこの後アプリを終了する。"""
    if not (IS_FROZEN and sys.platform == "win32"):
        raise RuntimeError("自動更新はインストーラー版（Windows）でのみ使えます。開発版は git pull してください。")
    tmp = Path(tempfile.gettempdir()) / f"Komonjo-Daro-Setup-{info.version}.exe"
    with open_asset(info, 60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        if on_progress:
            on_progress(0, total)
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)
    size = tmp.stat().st_size
    if size < 1_000_000:
        raise RuntimeError("ダウンロードしたインストーラーが小さすぎます。手動で更新してください。")
    if total and size != total:
        raise RuntimeError(f"ダウンロードが途中で切れました（{size}/{total} バイト）。もう一度お試しください。")
    log(f"downloaded {size} bytes -> {tmp}")
    # /SILENT: 進捗のみ表示  /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS: 使用中のアプリ（自分）を確実に閉じる
    # /LOG: インストーラー側の記録。再起動はインストーラーの [Run] postinstall に任せる
    install_log = log_dir() / "update-install.log"
    cmd = [str(tmp), "/SILENT", "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS", "/NORESTART", f"/LOG={install_log}"]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, creationflags=flags, close_fds=True)
    return tmp


EXIT_HOOKS: list = []   # 終了前に呼ぶ（トレイアイコンの除去、インスタンス記録の削除など）


def exit_app(delay: float = 1.0) -> None:
    """delay 秒後に終了フックを実行して os._exit する。フックが固まっても 2 秒で必ず終了する。"""
    def _hooks():
        for h in list(EXIT_HOOKS):
            try:
                h()
            except Exception:  # noqa: BLE001
                pass

    def _die():
        import time
        time.sleep(delay)
        t = threading.Thread(target=_hooks, daemon=True)
        t.start()
        t.join(2.0)
        log("app exit")
        os._exit(0)
    threading.Thread(target=_die, daemon=True).start()
