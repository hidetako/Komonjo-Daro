"""NDL古典籍OCR-Lite を外部プロセスとして呼び出す薄いラッパー。

NDL-Lite 本体は改変せず vendor/ndlkotenocr-lite に置く（README参照）。
ocr.py は出力先に <画像名>.txt / .json / .xml を書くので、それを読み取って返す。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NDL_SRC = Path(os.environ.get("NDL_LITE_SRC", ROOT / "vendor" / "ndlkotenocr-lite" / "src"))
# 全角文字を含むパス（Windowsの日本語ユーザー名の Temp 等）を避けるため、
# 作業ディレクトリはプロジェクト内に置く。
WORK_DIR = Path(os.environ.get("KOBUN_TMP", ROOT / "data" / "tmp"))

SUPPORTED_EXT = {"jpg", "jpeg", "png", "tif", "tiff", "jp2", "bmp"}


class NdlLiteNotFound(RuntimeError):
    pass


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
    viz_path: str | None = None    # --viz 指定時の検出枠つき画像

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def check_installed() -> Path:
    if not (NDL_SRC / "ocr.py").exists():
        raise NdlLiteNotFound(
            f"NDL古典籍OCR-Lite が見つかりません: {NDL_SRC}\n"
            "次を実行してください:\n"
            "  git clone https://github.com/ndl-lab/ndlkotenocr-lite vendor/ndlkotenocr-lite\n"
            "または環境変数 NDL_LITE_SRC で src ディレクトリを指定してください。"
        )
    return NDL_SRC


def parse_output(txt: str, js: dict) -> OcrResult:
    """ocr.py の .txt と .json を OcrResult に変換する（純粋関数、テスト対象）。"""
    lines: list[OcrLine] = []
    for page in js.get("contents", []):
        for obj in page:
            bb = obj["boundingBox"]  # [[x,y],[x,y+h],[x+w,y],[x+w,y+h]]
            xs = [p[0] for p in bb]
            ys = [p[1] for p in bb]
            lines.append(
                OcrLine(
                    id=int(obj.get("id", len(lines))),
                    text=obj.get("text", ""),
                    confidence=float(obj.get("confidence") or 0.0),
                    x=min(xs),
                    y=min(ys),
                    w=max(xs) - min(xs),
                    h=max(ys) - min(ys),
                )
            )
    info = js.get("imginfo", {})
    return OcrResult(
        text=txt.strip("\n"),
        lines=lines,
        width=int(info.get("img_width", 0)),
        height=int(info.get("img_height", 0)),
    )


def run_ocr(image_path: str | Path, device: str = "cpu", viz: bool = False, timeout: int = 900) -> OcrResult:
    """1枚の画像を OCR する。device は 'cpu' か 'cuda'（onnxruntime-gpu 必須）。"""
    src = check_installed()
    image_path = Path(image_path).resolve()
    ext = image_path.suffix.lstrip(".").lower()
    if ext not in SUPPORTED_EXT:
        raise ValueError(f"未対応の拡張子です: {image_path.suffix}（対応: {sorted(SUPPORTED_EXT)}）")

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    job = WORK_DIR / uuid.uuid4().hex
    job.mkdir()
    try:
        # ocr.py はファイル名を最初の '.' で切るので、安全な名前にコピーしてから渡す
        safe_img = job / f"page.{ext}"
        shutil.copyfile(image_path, safe_img)
        out = job / "out"
        out.mkdir()
        cmd = [sys.executable, "ocr.py", "--sourceimg", str(safe_img), "--output", str(out), "--device", device]
        if viz:
            cmd += ["--viz", "True"]
        proc = subprocess.run(
            cmd, cwd=src, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
        if proc.returncode != 0:
            raise RuntimeError(f"NDL-Lite の実行に失敗しました (code={proc.returncode})\n{proc.stderr[-3000:]}")
        txt = (out / "page.txt").read_text(encoding="utf-8")
        js = json.loads((out / "page.json").read_text(encoding="utf-8"))
        result = parse_output(txt, js)
        viz_file = out / f"viz_page.{ext}"
        if viz and viz_file.exists():
            keep = WORK_DIR / f"viz_{job.name}.{ext}"
            shutil.move(str(viz_file), keep)
            result.viz_path = str(keep)
        return result
    finally:
        shutil.rmtree(job, ignore_errors=True)
