"""画像の前処理（写真の影・傾き・薄さの補正）。OCR と AI の両方に渡す「補正画像」を作る。

控えめに:
- 紙地の明るさムラを平らにする（大きなぼかしで背景を推定して割る）
- コントラストを百分位で正規化（二値化はしない。墨の濃淡は残す）
- 傾きは、投影の分散が最大になる角度を探し、十分な差があるときだけ回す
原本は残し、補正画像は別ファイル（enhanced.jpg）として保存する。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

MAX_WORK = 1600          # 傾き推定は縮小画像で行う
ANGLES = np.arange(-3.0, 3.01, 0.5)
MIN_ANGLE = 0.3          # これ未満の傾きは触らない
MIN_GAIN = 1.30          # 分散がこの倍率以上良くならなければ回さない（書作品など不揃いな資料で誤回転しないため）


def estimate_background(gray: Image.Image) -> np.ndarray:
    """紙地の明るさ分布を推定する。縮小 → 最大値フィルタで墨を消す → ぼかし → 元の大きさへ。"""
    small = gray.copy()
    small.thumbnail((400, 400))
    k = max(5, (min(small.size) // 40) * 2 + 1)        # 墨の太さより大きい奇数
    bg = small.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.GaussianBlur(k))
    bg = bg.resize(gray.size, Image.BILINEAR)
    return np.asarray(bg, dtype=np.float32)


def flatten_background(gray: Image.Image) -> Image.Image:
    """紙地の明るさムラを取り除く。墨を消した背景で割って平らにする（光輪を出さない）。"""
    g = np.asarray(gray, dtype=np.float32)
    bg = estimate_background(gray)
    flat = np.clip(g / np.maximum(bg, 1.0), 0, 1.0)
    # 紙地を白に、墨を黒に寄せる（百分位で正規化。二値化はしない）
    lo, hi = np.percentile(flat, 0.5), np.percentile(flat, 90)
    out = (flat - lo) / max(hi - lo, 1e-3)
    return Image.fromarray(np.clip(out * 255, 0, 255).astype(np.uint8), "L")


def _binarize(gray: Image.Image) -> np.ndarray:
    g = np.asarray(gray, dtype=np.float32)
    thr = (np.percentile(g, 5) + np.percentile(g, 60)) / 2
    return (g < thr).astype(np.float32)


def estimate_skew(gray: Image.Image) -> float:
    """文字列の向きが縦横どちらでも効くよう、行・列両方の投影の分散の和が最大になる角度を探す。"""
    small = gray.copy()
    small.thumbnail((MAX_WORK, MAX_WORK))
    best_angle, best_score, base = 0.0, -1.0, None
    for a in ANGLES:
        rot = small.rotate(float(a), resample=Image.BILINEAR, fillcolor=255)
        b = _binarize(rot)
        score = float(np.var(b.sum(axis=0)) + np.var(b.sum(axis=1)))
        if abs(a) < 1e-6:
            base = score
        if score > best_score:
            best_angle, best_score = float(a), score
    if base is None or base <= 0 or abs(best_angle) < MIN_ANGLE or best_score < base * MIN_GAIN:
        return 0.0
    if abs(best_angle) >= ANGLES[-1] - 1e-6:       # 範囲の端に張り付くのは推定が効いていない
        return 0.0
    return best_angle


def enhance(src: str | Path, dst: str | Path, deskew: bool = True) -> dict:
    """補正画像を dst に書き出す。戻り値は {"angle": 回した角度}。"""
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        gray = ImageOps.grayscale(im)
        angle = estimate_skew(gray) if deskew else 0.0
        if angle:
            im = im.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
            gray = ImageOps.grayscale(im)
        flat = flatten_background(gray)
        # 墨の色味は要らないので補正画像はグレーのまま RGB に（OCR・AI とも扱いやすい）
        flat.convert("RGB").save(dst, quality=92)
    return {"angle": angle}
