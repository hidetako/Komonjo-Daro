"""PDF をページ画像に展開する（pypdfium2。NDL-Lite の依存に含まれるので追加インストール不要）。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from PIL import Image

DEFAULT_DPI = 200          # NDL-Lite の検出器は 1280px 四方なので、A5〜B5 の古典籍なら 200dpi で十分
MAX_PAGES = 200


def page_count(pdf_path: str | Path) -> int:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def parse_page_range(spec: str, total: int) -> list[int]:
    """'1-3,5,8-' のような指定を 1 始まりのページ番号リストにする。空なら全ページ。"""
    spec = (spec or "").strip().replace("，", ",").replace("－", "-").replace("ー", "-")
    if not spec:
        return list(range(1, total + 1))
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)?\s*-\s*(\d+)?", part)
        if m and "-" in part:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else total
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ValueError(f"ページ指定が読めません: {part}")
        for p in range(max(1, a), min(total, b) + 1):
            if p not in pages:
                pages.append(p)
    if not pages:
        raise ValueError("指定範囲にページがありません")
    return pages


def render_pages(pdf_path: str | Path, pages: list[int], dpi: int = DEFAULT_DPI) -> Iterator[tuple[int, Image.Image]]:
    """指定ページを順に (ページ番号, RGB画像) で返す。"""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for p in pages:
            page = pdf[p - 1]
            bitmap = page.render(scale=dpi / 72)
            yield p, bitmap.to_pil().convert("RGB")
            page.close()
    finally:
        pdf.close()
