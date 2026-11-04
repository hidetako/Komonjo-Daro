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
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


@dataclass
class ReleaseInfo:
    version: str
    url: str          # インストーラーの直リンク
    notes: str
    page: str         # リリースページ


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def fetch_latest(timeout: float = 8.0) -> ReleaseInfo | None:
    req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "Komonjo-Daro"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    url = next((a["browser_download_url"] for a in data.get("assets", []) if a.get("name") == ASSET_NAME), "")
    if not url:
        return None
    return ReleaseInfo(version=data.get("tag_name", "").lstrip("v"), url=url,
                       notes=data.get("body", "") or "", page=data.get("html_url", ""))


class UpdateState:
    """アプリ全体で共有する更新状態。"""

    def __init__(self):
        self.latest: ReleaseInfo | None = None
        self.error: str = ""
        self.checked = False
        self.lock = threading.Lock()

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


def download_and_install(info: ReleaseInfo) -> Path:
    """インストーラーを取得してサイレント実行する。呼び出し側はこの後アプリを終了する。"""
    if not (IS_FROZEN and sys.platform == "win32"):
        raise RuntimeError("自動更新はインストーラー版（Windows）でのみ使えます。開発版は git pull してください。")
    tmp = Path(tempfile.gettempdir()) / f"Komonjo-Daro-Setup-{info.version}.exe"
    req = urllib.request.Request(info.url, headers={"User-Agent": "Komonjo-Daro"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    if tmp.stat().st_size < 1_000_000:
        raise RuntimeError("ダウンロードしたインストーラーが小さすぎます。手動で更新してください。")
    # /SILENT: 進捗のみ表示  /CLOSEAPPLICATIONS: 使用中ファイルを持つアプリを閉じる
    subprocess.Popen([str(tmp), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return tmp


def exit_app(delay: float = 1.0) -> None:
    def _die():
        import time
        time.sleep(delay)
        os._exit(0)
    threading.Thread(target=_die, daemon=True).start()
