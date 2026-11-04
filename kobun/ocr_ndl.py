"""NDL古典籍OCR-Lite のラッパー。

既定ではプロセス内で NDL-Lite のモジュールを読み込んで実行する（インストーラー版でも動く。
モデルは初回読み込み後キャッシュされ、2ページ目以降が速い）。
環境変数 KOBUN_OCR_MODE=subprocess で、従来どおり別プロセス実行にも切り替えられる。

NDL-Lite 本体は改変せず vendor/ndlkotenocr-lite に置く（インストーラー版は同梱）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from argparse import Namespace
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import IS_FROZEN, ROOT

SUPPORTED_EXT = {"jpg", "jpeg", "png", "tif", "tiff", "jp2", "bmp"}
_LOCK = threading.Lock()


class NdlLiteNotFound(RuntimeError):
    pass


def ndl_src_dir() -> Path:
    if os.environ.get("NDL_LITE_SRC"):
        return Path(os.environ["NDL_LITE_SRC"])
    if IS_FROZEN:
        return ROOT / "ndlkotenocr-lite" / "src"
    return ROOT / "vendor" / "ndlkotenocr-lite" / "src"


def work_dir() -> Path:
    """一時作業ディレクトリ。全角文字を含むパス（日本語ユーザー名の Temp 等）を避ける。"""
    if os.environ.get("KOBUN_TMP"):
        return Path(os.environ["KOBUN_TMP"])
    if IS_FROZEN:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Komonjo-Daro" / "tmp"
    else:
        base = ROOT / "data" / "tmp"
    return base


@dataclass
class OcrLine:
    id: int
    text: str
    confidence: float
    x: int
    y: int
    w: int
    h: int

    @property
    def vertical(self) -> bool:
        return self.h > self.w


@dataclass
class OcrResult:
    text: str                      # 読み順に並んだ全文（1行1テキスト行）
    lines: list[OcrLine] = field(default_factory=list)
    width: int = 0
    height: int = 0
    viz_path: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def check_installed() -> Path:
    src = ndl_src_dir()
    if not (src / "ocr.py").exists():
        raise NdlLiteNotFound(
            f"NDL古典籍OCR-Lite が見つかりません: {src}\n"
            "次を実行してください:\n"
            "  git clone https://github.com/ndl-lab/ndlkotenocr-lite vendor/ndlkotenocr-lite\n"
            "または環境変数 NDL_LITE_SRC で src ディレクトリを指定してください。"
        )
    return src


def parse_output(txt: str, js: dict) -> OcrResult:
    """ocr.py の .txt と .json を OcrResult に変換する（純粋関数、テスト対象）。"""
    lines: list[OcrLine] = []
    for page in js.get("contents", []):
        for obj in page:
            bb = obj["boundingBox"]
            xs = [p[0] for p in bb]
            ys = [p[1] for p in bb]
            lines.append(OcrLine(
                id=int(obj.get("id", len(lines))), text=obj.get("text", ""),
                confidence=float(obj.get("confidence") or 0.0),
                x=min(xs), y=min(ys), w=max(xs) - min(xs), h=max(ys) - min(ys),
            ))
    info = js.get("imginfo", {})
    return OcrResult(text=txt.strip("\n"), lines=lines,
                     width=int(info.get("img_width", 0)), height=int(info.get("img_height", 0)))


def _build_args(src: Path, image: Path, out: Path, device: str, viz: bool) -> Namespace:
    return Namespace(
        sourcedir=None, sourceimg=str(image), output=str(out), viz=viz,
        det_weights=str(src / "model" / "rtmdet-s-1280x1280.onnx"),
        det_classes=str(src / "config" / "ndl.yaml"),
        det_score_threshold=0.3, det_conf_threshold=0.3, det_iou_threshold=0.3,
        rec_weights=str(src / "model" / "parseq-ndl-32x384-tiny-10.onnx"),
        rec_classes=str(src / "config" / "NDLmoji.yaml"),
        device=device,
    )


_ndl_module = None


def _load_ndl_module(src: Path):
    """NDL-Lite の ocr.py をモジュールとして読み込む（1回だけ）。"""
    global _ndl_module
    if _ndl_module is None:
        s = str(src)
        if s not in sys.path:
            sys.path.insert(0, s)
        import importlib
        _ndl_module = importlib.import_module("ocr")
    return _ndl_module


def _run_inprocess(src: Path, image: Path, out: Path, device: str, viz: bool) -> None:
    mod = _load_ndl_module(src)
    cwd = os.getcwd()
    try:
        os.chdir(src)  # NDL-Lite 内部の相対パス参照に備える
        mod.process(_build_args(src, image, out, device, viz))
    finally:
        os.chdir(cwd)


def _run_subprocess(src: Path, image: Path, out: Path, device: str, viz: bool, timeout: int) -> None:
    cmd = [sys.executable, "ocr.py", "--sourceimg", str(image), "--output", str(out), "--device", device]
    if viz:
        cmd += ["--viz", "True"]
    proc = subprocess.run(cmd, cwd=src, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"NDL-Lite の実行に失敗しました (code={proc.returncode})\n{proc.stderr[-3000:]}")


def run_ocr(image_path: str | Path, device: str = "cpu", viz: bool = False, timeout: int = 900) -> OcrResult:
    """1枚の画像を OCR する。device は 'cpu' か 'cuda'（onnxruntime-gpu 必須）。"""
    src = check_installed()
    image_path = Path(image_path).resolve()
    ext = image_path.suffix.lstrip(".").lower()
    if ext not in SUPPORTED_EXT:
        raise ValueError(f"未対応の拡張子です: {image_path.suffix}（対応: {sorted(SUPPORTED_EXT)}）")

    wd = work_dir()
    wd.mkdir(parents=True, exist_ok=True)
    job = wd / uuid.uuid4().hex
    job.mkdir()
    try:
        safe_img = job / f"page.{ext}"      # ocr.py はファイル名を最初の '.' で切るので安全な名前にする
        shutil.copyfile(image_path, safe_img)
        out = job / "out"
        out.mkdir()
        mode = os.environ.get("KOBUN_OCR_MODE", "inprocess")
        with _LOCK:
            if mode == "subprocess" and not IS_FROZEN:
                _run_subprocess(src, safe_img, out, device, viz, timeout)
            else:
                _run_inprocess(src, safe_img, out, device, viz)
        txt = (out / "page.txt").read_text(encoding="utf-8")
        js = json.loads((out / "page.json").read_text(encoding="utf-8"))
        result = parse_output(txt, js)
        viz_file = out / f"viz_page.{ext}"
        if viz and viz_file.exists():
            keep = wd / f"viz_{job.name}.{ext}"
            shutil.move(str(viz_file), keep)
            result.viz_path = str(keep)
        return result
    finally:
        shutil.rmtree(job, ignore_errors=True)
