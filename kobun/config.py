"""ユーザー設定（APIキー・保存先・モデル等）。

設定ファイルの場所:
  Windows: %APPDATA%\\Komonjo-Daro\\config.json
  その他  : ~/.config/komonjo-daro/config.json
保存先データの既定: ~/Documents/Komonjo-Daro
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import APP_NAME

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))  # PyInstaller 対応
IS_FROZEN = getattr(sys, "frozen", False)

DEFAULTS = {
    "api_key": "",
    "model": "claude-opus-5-5",
    "effort": "high",
    "device": "cpu",
    "data_dir": "",
    "send_image": True,
    "auto_check_updates": True,
}


def config_dir() -> Path:
    if os.environ.get("KOBUN_CONFIG_DIR"):
        return Path(os.environ["KOBUN_CONFIG_DIR"])
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    return Path.home() / ".config" / "komonjo-daro"


def config_path() -> Path:
    return config_dir() / "config.json"


def default_data_dir() -> Path:
    if os.environ.get("KOBUN_DATA_DIR"):
        return Path(os.environ["KOBUN_DATA_DIR"])
    docs = Path.home() / "Documents"
    if sys.platform == "win32":
        # OneDrive 配下の「ドキュメント」は避ける（同期で壊れやすい）
        up = os.environ.get("USERPROFILE")
        if up:
            docs = Path(up) / "Documents"
    return docs / APP_NAME


def load() -> dict:
    cfg = dict(DEFAULTS)
    p = config_path()
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    if not cfg.get("data_dir"):
        cfg["data_dir"] = str(default_data_dir())
    # 環境変数・.env はフォールバック（開発時用）
    if not cfg.get("api_key") and os.environ.get("ANTHROPIC_API_KEY"):
        cfg["api_key"] = os.environ["ANTHROPIC_API_KEY"]
    return cfg


def save(cfg: dict) -> None:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    data = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 12:
        return "*" * len(key)
    return key[:7] + "…" + key[-4:]
