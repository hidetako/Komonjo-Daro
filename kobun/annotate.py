"""翻刻テキスト（＋画像）を LLM（Claude / GPT）に渡し、校訂・現代語訳・注釈を構造化JSONで受け取る。"""
from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageOps

from . import config as _config
from . import llm

# 開発時は .env（プロジェクト直下）も読む
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = os.environ.get("KOBUN_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("KOBUN_EFFORT", "high")
MAX_IMAGE_EDGE = 1568  # これ以上大きくしても画像トークンは増えるだけで精度は上がらない

SYSTEM_PROMPT = """あなたは日本古典籍（和古書・写本・版本）の翻刻と注釈を行う専門家です。出力は日本語で書きます。

入力として、OCR（NDL古典籍OCR-Lite）が出力した翻刻テキストと、可能なら元の資料画像が与えられます。
OCRは誤認識を含みます。画像がある場合は必ず画像を一次資料として優先し、OCRテキストは参考にとどめてください。

出力は指定されたJSONスキーマに従ってください。各項目の方針:
- honkoku: 校訂済みの翻刻。原文の行区切りを保ち、仮名・漢字は原文のままにし、濁点・句読点を勝手に補わない。
  判読できない文字は「■」、推定を含む文字は〔 〕で囲む。
- corrections: OCRから変更した箇所。根拠を短く書く。画像で確認できなかった変更はしない。
- gendaigo: 平易で正確な現代語訳。意訳しすぎず、省略された主語は〔 〕で補う。
- annotations: 人名・地名・官職・語彙・典拠・年号など、読解に必要な注。確実でない説明は「推定」と明記する。
- uncertain: 判読・解釈に自信がない箇所を列挙する。不確実な情報を確実なものとして書かない。
- summary: 2〜3文で内容の要約。
- era_guess: 書体・内容から推定される時代。根拠がなければ「不明」。
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "honkoku": {"type": "string", "description": "校訂済み翻刻。原文の改行を保持"},
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer", "description": "1始まりの行番号"},
                    "ocr": {"type": "string"},
                    "fixed": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["line", "ocr", "fixed", "reason"],
                "additionalProperties": False,
            },
        },
        "gendaigo": {"type": "string", "description": "現代語訳"},
        "annotations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["term", "note"],
                "additionalProperties": False,
            },
        },
        "uncertain": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "era_guess": {"type": "string"},
    },
    "required": ["honkoku", "corrections", "gendaigo", "annotations", "uncertain", "summary", "era_guess"],
    "additionalProperties": False,
}


@dataclass
class Annotation:
    honkoku: str
    corrections: list[dict]
    gendaigo: str
    annotations: list[dict]
    uncertain: list[str]
    summary: str
    era_guess: str
    model: str
    input_tokens: int
    output_tokens: int

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    def to_markdown(self) -> str:
        md = ["## 翻刻（校訂済）", "", self.honkoku, "", "## 現代語訳", "", self.gendaigo, ""]
        if self.annotations:
            md += ["## 注釈", ""] + [f"- **{a['term']}**: {a['note']}" for a in self.annotations] + [""]
        if self.corrections:
            md += ["## OCRからの修正", ""] + [
                f"- {c['line']}行目: 「{c['ocr']}」→「{c['fixed']}」（{c['reason']}）" for c in self.corrections
            ] + [""]
        if self.uncertain:
            md += ["## 不確実な箇所", ""] + [f"- {u}" for u in self.uncertain] + [""]
        md += ["## 要約", "", self.summary, "", f"推定時代: {self.era_guess}", ""]
        return "\n".join(md)


def encode_image(image_path: str | Path) -> tuple[str, str]:
    """画像を長辺 MAX_IMAGE_EDGE 以下の JPEG に縮小して base64 で返す。"""
    with Image.open(image_path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


def build_user_text(ocr_text: str, context: str = "") -> str:
    parts = []
    if context.strip():
        parts.append(f"資料についての補足情報:\n{context.strip()}\n")
    parts.append("OCR翻刻テキスト（誤認識を含む）:\n" + ocr_text.strip())
    parts.append("\n上記を校訂し、現代語訳と注釈を作成してください。")
    return "\n".join(parts)


def build_user_content(ocr_text: str, image_path: str | Path | None, context: str = "") -> list[dict]:
    """Anthropic 形式の content（テスト・互換用）。"""
    content: list[dict] = []
    if image_path:
        data, media = encode_image(image_path)
        content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    content.append({"type": "text", "text": build_user_text(ocr_text, context)})
    return content


def annotate(ocr_text: str, image_path: str | Path | None = None, context: str = "", client=None,
             model: str | None = None, effort: str | None = None, api_key: str | None = None,
             provider: str | None = None) -> Annotation:
    """OCRテキストと画像を LLM に送り、構造化された校訂・現代語訳・注釈を返す。

    プロバイダ・モデル・キーは 引数 > 設定ファイル（設定画面） > 環境変数 の順で決まる。
    """
    cfg = _config.load()
    if provider:
        cfg["provider"] = provider
    provider, cfg_model, cfg_key = _config.active(cfg)
    model = model or cfg_model
    effort = effort or cfg.get("effort") or EFFORT
    key = api_key or cfg_key
    if client is None and not key and not (provider == "anthropic" and os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise RuntimeError(
            f"{llm.PROVIDERS[provider]['label']} の API キーが設定されていません。画面右上の「設定」から入力してください。"
        )
    image = encode_image(image_path) if image_path else None
    r = llm.call(provider, model, effort, key, SYSTEM_PROMPT, build_user_text(ocr_text, context), image, OUTPUT_SCHEMA, client=client)
    data = llm.parse_json(r.text)
    return Annotation(**data, model=r.model, input_tokens=r.input_tokens, output_tokens=r.output_tokens)
