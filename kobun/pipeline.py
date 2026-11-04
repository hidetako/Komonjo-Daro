"""CLI: 画像 → OCR → （任意で）Claude 校訂・現代語訳・注釈 → JSON / Markdown 保存。

使い方:
  python -m kobun.pipeline 画像.jpg                 # OCR + Claude
  python -m kobun.pipeline 画像.jpg --no-llm        # OCRのみ（APIキー不要）
  python -m kobun.pipeline 画像.jpg --device cuda   # GPU（onnxruntime-gpu 導入時）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ocr_ndl import run_ocr


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="古典籍画像を翻刻・現代語訳する")
    p.add_argument("image", help="画像ファイル (jpg/png/tif/jp2/bmp)")
    p.add_argument("--out", default="data/results", help="出力ディレクトリ")
    p.add_argument("--device", default=None, choices=["cpu", "cuda"], help="既定は設定ファイルの値")
    p.add_argument("--no-llm", action="store_true", help="OCRのみ実行")
    p.add_argument("--no-image", action="store_true", help="Claude に画像を送らずテキストのみで処理（通信量削減）")
    p.add_argument("--context", default="", help="資料名・巻数など補足情報")
    p.add_argument("--viz", action="store_true", help="検出枠つき画像も保存")
    args = p.parse_args(argv)

    from . import config as _config
    device = args.device or _config.load().get("device", "cpu")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.image).stem

    print(f"[1/2] OCR (device={device}) ...", file=sys.stderr)
    ocr = run_ocr(args.image, device=device, viz=args.viz)
    print(f"      {len(ocr.lines)} 行を認識", file=sys.stderr)
    result = {"image": str(Path(args.image).resolve()), "ocr": ocr.to_dict()}

    if not args.no_llm:
        from .annotate import annotate

        print("[2/2] Claude で校訂・現代語訳・注釈 ...", file=sys.stderr)
        ann = annotate(ocr.text, None if args.no_image else args.image, context=args.context)
        result["annotation"] = ann.to_dict()
        (out / f"{stem}.md").write_text(ann.to_markdown(), encoding="utf-8")
        print(f"      tokens in={ann.input_tokens} out={ann.output_tokens}", file=sys.stderr)
    else:
        (out / f"{stem}.md").write_text("## 翻刻（OCR生）\n\n" + ocr.text + "\n", encoding="utf-8")

    (out / f"{stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"保存: {out / (stem + '.json')} / {out / (stem + '.md')}", file=sys.stderr)
    print(ocr.text if args.no_llm else result["annotation"]["honkoku"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
