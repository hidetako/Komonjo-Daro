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


# ---- 横長・縦長画像の分割検出 ----
SPLIT_RATIO = 1.6      # 長辺/短辺 がこれを超えたら分割
SEG_RATIO = 1.25       # 1 区画の長辺 ≒ 短辺 × これ
OVERLAP_RATIO = 0.18   # 区画の重なり（短辺比）


def plan_segments(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """分割が必要なら区画 (x0, y0, x1, y1) のリスト、不要なら [] を返す。長辺に沿って重なりつきで切る。"""
    long_, short = max(width, height), min(width, height)
    if short <= 0 or long_ / short <= SPLIT_RATIO:
        return []
    seg = int(short * SEG_RATIO)
    ov = int(short * OVERLAP_RATIO)
    step = max(1, seg - ov)
    starts = list(range(0, max(1, long_ - seg) + 1, step))
    if starts[-1] + seg < long_:
        starts.append(long_ - seg)
    segs = []
    for st in starts:
        a, b = st, min(long_, st + seg)
        segs.append((a, 0, b, height) if width >= height else (0, a, width, b))
    return segs


def _overlap_ratio(a: OcrLine, b: OcrLine) -> float:
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = ix * iy
    smaller = max(1, min(a.w * a.h, b.w * b.h))
    return inter / smaller


def merge_segment_results(parts: list[tuple[tuple[int, int, int, int], OcrResult]], width: int, height: int) -> OcrResult:
    """区画ごとの結果を全体座標に直し、重なりの重複を除いて読み順に並べる。"""
    lines: list[OcrLine] = []
    for (x0, y0, _, _), res in parts:
        for ln in res.lines:
            cand = OcrLine(id=0, text=ln.text, confidence=ln.confidence, x=ln.x + x0, y=ln.y + y0, w=ln.w, h=ln.h)
            dup = None
            for i, kept in enumerate(lines):
                if _overlap_ratio(cand, kept) > 0.6:
                    dup = i
                    break
            if dup is None:
                lines.append(cand)
            elif cand.w * cand.h > lines[dup].w * lines[dup].h:   # 境界で切れた方ではなく、大きい方を採る
                lines[dup] = cand
    vertical = sum(1 for l in lines if l.h > l.w) * 2 >= max(1, len(lines))
    # 縦書き: 右の行から左へ（同じ列は上から）。横書き: 上から下（同じ段は左から）
    if vertical:
        lines.sort(key=lambda l: (-(l.x + l.w / 2) // max(1, int(l.w * 0.8) or 1), l.y))
    else:
        lines.sort(key=lambda l: ((l.y + l.h / 2) // max(1, int(l.h * 0.8) or 1), l.x))
    for i, l in enumerate(lines):
        l.id = i
    return OcrResult(text="\n".join(l.text for l in lines), lines=lines, width=width, height=height)


# ---- 分断された行の結合（散らし書き・連綿の切れ目で 1 行が複数に割れたとき） ----
MERGE_ALIGN = 0.5   # 同じ列とみなす中心のずれ（行幅比）
MERGE_GAP = 1.5     # つなぐ最大の隙間（行幅比）


def group_broken_lines(lines: list[OcrLine]) -> list[list[OcrLine]]:
    """縦書き前提で、同じ列に縦に並ぶ断片をグループにする。戻り値は読み順（右→左、列内は上→下）。"""
    vert = [l for l in lines if l.h > l.w]
    if len(vert) * 2 < max(1, len(lines)):
        return [[l] for l in lines]          # 横書き主体なら触らない
    widths = sorted(l.w for l in vert)
    med_w = widths[len(widths) // 2] if widths else 1
    rest = sorted(lines, key=lambda l: -(l.x + l.w / 2))
    groups: list[list[OcrLine]] = []
    for l in rest:
        cx = l.x + l.w / 2
        placed = False
        if l.h > l.w:
            for g in groups:
                gl = g[-1]
                if gl.h <= gl.w:
                    continue
                gcx = gl.x + gl.w / 2
                if abs(cx - gcx) <= MERGE_ALIGN * med_w:
                    # 縦の隙間（どちらが上でも）
                    top, bot = (gl, l) if gl.y <= l.y else (l, gl)
                    gap = bot.y - (top.y + top.h)
                    if gap <= MERGE_GAP * med_w:
                        g.append(l)
                        g.sort(key=lambda z: z.y)
                        placed = True
                        break
        if not placed:
            groups.append([l])
    groups.sort(key=lambda g: -max(z.x + z.w / 2 for z in g))
    return groups


def merge_groups(groups: list[list[OcrLine]], recognize=None) -> list[OcrLine]:
    """グループごとに 1 行にまとめる。recognize(x, y, w, h) -> str があれば結合範囲を読み直す。"""
    out: list[OcrLine] = []
    for i, g in enumerate(groups):
        if len(g) == 1:
            l = g[0]
            out.append(OcrLine(i, l.text, l.confidence, l.x, l.y, l.w, l.h))
            continue
        x0, y0 = min(z.x for z in g), min(z.y for z in g)
        x1, y1 = max(z.x + z.w for z in g), max(z.y + z.h for z in g)
        text = None
        if recognize:
            try:
                text = recognize(x0, y0, x1 - x0, y1 - y0)
            except Exception:  # noqa: BLE001
                text = None
        if not text:
            text = "".join(z.text for z in g)
        out.append(OcrLine(i, text, min(z.confidence for z in g), x0, y0, x1 - x0, y1 - y0))
    return out


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


def run_ocr(image_path: str | Path, device: str = "cpu", viz: bool = False, timeout: int = 900,
            split: bool | None = None, merge_lines: bool = True) -> OcrResult:
    """1枚の画像を OCR する。device は 'cpu' か 'cuda'（onnxruntime-gpu 必須）。

    split: None なら縦横比で自動判定、True で強制分割、False で分割しない。
    """
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
        from PIL import Image, ImageOps

        with Image.open(image_path) as src_im:
            im = ImageOps.exif_transpose(src_im).convert("RGB")
        segs = plan_segments(im.width, im.height) if split is None or split else []
        if not segs:
            safe_img = job / f"page.{ext}"      # ocr.py はファイル名を最初の '.' で切るので安全な名前にする
            shutil.copyfile(image_path, safe_img)
            result = _run_one(src, safe_img, job / "out", device, viz, timeout)
            viz_file = job / "out" / f"viz_page.{ext}"
            if viz and viz_file.exists():
                keep = wd / f"viz_{job.name}.{ext}"
                shutil.move(str(viz_file), keep)
                result.viz_path = str(keep)
        else:
            # 横長・縦長: 区画ごとに検出して結合（検出器は 1280px 四方に縮めるため、そのままだと行が潰れる）
            parts = []
            for i, (x0, y0, x1, y1) in enumerate(segs):
                seg_img = job / f"seg{i}.jpg"
                im.crop((x0, y0, x1, y1)).save(seg_img, quality=95)
                parts.append(((x0, y0, x1, y1), _run_one(src, seg_img, job / f"out{i}", device, False, timeout)))
            result = merge_segment_results(parts, im.width, im.height)
        if merge_lines:
            result = _merge_broken(result, im, src, device)
        return result
    finally:
        shutil.rmtree(job, ignore_errors=True)


def _merge_broken(result: OcrResult, im, src: Path, device: str) -> OcrResult:
    """分断された行を結合し、可能なら結合範囲を認識器で読み直す。"""
    groups = group_broken_lines(result.lines)
    if all(len(g) == 1 for g in groups):
        return result
    recognize = None
    if os.environ.get("KOBUN_OCR_MODE", "inprocess") != "subprocess" or IS_FROZEN:
        try:
            import numpy as np
            mod = _load_ndl_module(src)
            rec = mod.get_recognizer(_build_args(src, Path("x"), Path("y"), device, False))
            arr = np.array(im)

            def recognize(x, y, w, h):
                return rec.read(arr[y:y + h, x:x + w, :])
        except Exception:  # noqa: BLE001
            recognize = None
    with _LOCK:
        lines = merge_groups(groups, recognize)
    return OcrResult(text="\n".join(l.text for l in lines), lines=lines, width=result.width, height=result.height, viz_path=result.viz_path)


def _run_one(src: Path, image: Path, out: Path, device: str, viz: bool, timeout: int) -> OcrResult:
    out.mkdir(parents=True, exist_ok=True)
    mode = os.environ.get("KOBUN_OCR_MODE", "inprocess")
    with _LOCK:
        if mode == "subprocess" and not IS_FROZEN:
            _run_subprocess(src, image, out, device, viz, timeout)
        else:
            _run_inprocess(src, image, out, device, viz)
    stem = image.name.split(".")[0]
    txt = (out / f"{stem}.txt").read_text(encoding="utf-8")
    js = json.loads((out / f"{stem}.json").read_text(encoding="utf-8"))
    return parse_output(txt, js)
