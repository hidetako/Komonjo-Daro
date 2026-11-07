"""行の手動分割と、行ごとの読み取り（AI / OCR / 両方）。

書作品・散らし書きは行検出が前提から外れるので、枠は人が決め、文字の読み取りだけ機械に任せる。
枠ごとに原寸で切り出し（字母パスと同じ切り出し）、AI には数行ずつ渡す。OCR は NDL-Lite の認識器だけを枠に当てる。
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from . import llm
from .jibo import LINES_PER_CALL, crop_line, encode

OVERVIEW_EDGE = 1568   # 全体図の長辺上限

SYSTEM = """あなたは日本の古典籍・古文書・書作品（仮名書道、散らし書き、連綿体）の翻刻者です。
最初に作品全体の画像（赤枠と番号が各行の位置）、続いて行ごとに切り出した画像が与えられます。
各行の文字を、原文どおりに翻刻してください。全体図は、行の前後関係・散らし書きの続き具合・
作品全体が何の文章かを把握するための参考です。文脈が分かっても、各行の切り出し画像で字形が
確認できる文字だけを書いてください。

規則:
- 変体仮名は現行の平仮名に直す。漢字はそのまま。踊り字（ゝ、〳〵）はそのまま書く。
- 濁点・句読点を勝手に補わない。改行は 1 行＝1 要素で、行の中では改行しない。
- 判読できない文字は「■」、推定を含む文字は〔 〕で囲む。
  〔 〕は、画像の字形から読みをある程度絞り込めるが確信がない場合にだけ使う。字形そのものが読めない文字は 1 字ずつ「■」にする。文脈や和歌らしさから「それらしい語句」を補って〔 〕に入れてはならない（創作された翻刻は ■ より有害）。数文字しか読めない行は、読めた文字と ■ だけで書く。
- 「OCR候補」が添えられている場合は参考にしてよいが、誤りが多いので画像を優先する。
- 文字が無い行（落款・印・余白）は text を空にする。
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"n": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["n", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


def normalize_boxes(boxes: list[dict], width: int, height: int) -> list[dict]:
    """画面から来た枠を整数・画像内に丸め、読み順（縦書き: 右→左、横書き: 上→下）に並べる。"""
    out = []
    for b in boxes:
        x, y = max(0, int(round(float(b.get("x", 0))))), max(0, int(round(float(b.get("y", 0)))))
        w, h = int(round(float(b.get("w", 0)))), int(round(float(b.get("h", 0))))
        if width:
            w = min(w, width - x)
        if height:
            h = min(h, height - y)
        if w >= 4 and h >= 4:
            out.append({"x": x, "y": y, "w": w, "h": h, "text": str(b.get("text", "") or "")})
    vertical = sum(1 for b in out if b["h"] > b["w"]) * 2 >= max(1, len(out))
    out.sort(key=(lambda b: -(b["x"] + b["w"] / 2)) if vertical else (lambda b: b["y"] + b["h"] / 2))
    for i, b in enumerate(out):
        b["id"] = i
        b["confidence"] = 1.0
    return out


def ocr_read_boxes(image_path: str | Path, boxes: list[dict], device: str = "cpu") -> list[str]:
    """NDL-Lite の認識器だけを各枠に当てる（検出は使わない）。使えなければ空文字列。"""
    from . import ocr_ndl

    try:
        import numpy as np
        src = ocr_ndl.check_installed()
        mod = ocr_ndl._load_ndl_module(src)
        rec = mod.get_recognizer(ocr_ndl._build_args(src, Path("x"), Path("y"), device, False))
    except Exception:  # noqa: BLE001
        return ["" for _ in boxes]
    with Image.open(image_path) as im:
        arr = np.array(ImageOps.exif_transpose(im).convert("RGB"))
    out = []
    for b in boxes:
        try:
            out.append(rec.read(arr[b["y"]:b["y"] + b["h"], b["x"]:b["x"] + b["w"], :]))
        except Exception:  # noqa: BLE001
            out.append("")
    return out


def overview_image(im: Image.Image, boxes: list[dict]) -> Image.Image:
    """全体図: 長辺 OVERVIEW_EDGE 以下に縮小し、各枠を赤線と番号で描き込む（番号は縮小後の大きさで描く）。"""
    from PIL import ImageFont

    ov = im.copy()
    ov.thumbnail((OVERVIEW_EDGE, OVERVIEW_EDGE))
    k = ov.width / im.width
    d = ImageDraw.Draw(ov)
    lw = max(2, min(ov.size) // 250)
    fs = max(16, min(ov.size) // 20)
    try:
        font = ImageFont.load_default(size=fs)
    except Exception:  # noqa: BLE001  古い Pillow
        font = ImageFont.load_default()
    for i, b in enumerate(boxes):
        x0, y0, x1, y1 = b["x"] * k, b["y"] * k, (b["x"] + b["w"]) * k, (b["y"] + b["h"]) * k
        d.rectangle([x0, y0, x1, y1], outline=(200, 30, 30), width=lw)
        tag = str(i + 1)
        tx0, ty0, tx1, ty1 = d.textbbox((0, 0), tag, font=font)
        tw, th = tx1 - tx0 + lw * 2, ty1 - ty0 + lw * 2
        ly = y0 - th if y0 - th >= 0 else y0
        d.rectangle([x0, ly, x0 + tw, ly + th], fill=(200, 30, 30))
        d.text((x0 + lw - tx0, ly + lw - ty0), tag, fill=(255, 255, 255), font=font)
    return ov


def ai_read_boxes(image_path: str | Path, boxes: list[dict], provider: str, model: str, effort: str, api_key: str,
                  hints: list[str] | None = None, client=None, context: str = "") -> tuple[list[str], int, int]:
    """各枠の切り出しを数行ずつ AI に渡して翻刻する。全体図を毎回添える。hints は OCR 候補（任意）。"""
    with Image.open(image_path) as src:
        im = ImageOps.exif_transpose(src).convert("RGB")
        ov_b64, ov_media = encode(overview_image(im, boxes))
        items = []
        for i, b in enumerate(boxes):
            b64, media = encode(crop_line(im, b))
            items.append((i + 1, b64, media, (hints[i] if hints and i < len(hints) else "")))
    results: dict[int, str] = {}
    tin = tout = 0
    for s in range(0, len(items), LINES_PER_CALL):
        batch = items[s:s + LINES_PER_CALL]
        parts: list[tuple] = [("text", f"作品全体（赤枠と番号は各行の位置。全 {len(items)} 行）:"), ("image", (ov_b64, ov_media))]
        if context.strip():
            parts.append(("text", "資料についての情報（利用者による）: " + context.strip()))
        parts.append(("text", "以下の各行の画像を翻刻してください。"))
        for n, b64, media, hint in batch:
            parts.append(("text", f"行{n}" + (f"（OCR候補: {hint}）" if hint else "")))
            parts.append(("image", (b64, media)))
        r = llm.call_parts(provider, model, effort, api_key, SYSTEM, parts, SCHEMA, client=client)
        tin += r.input_tokens
        tout += r.output_tokens
        for ln in json.loads(r.text).get("lines", []):
            results[int(ln["n"])] = ln.get("text", "")
    return [results.get(i + 1, "") for i in range(len(boxes))], tin, tout
