"""翻刻テキスト（＋画像）を Claude に渡し、校訂・現代語訳・注釈を構造化JSONで受け取る。"""
from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from PIL import Image, ImageOps

# CLI から呼ばれたときも .env（プロジェクト直下）を読む
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = os.environ.get("KOBUN_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("KOBUN_EFFORT", "high")
MAX_IMAGE_EDGE = 1568  # これ以上大きくしても画像トークンは増えるだけで精度は上がらない

SYSTEM_PROMPT = """あなたは日本古典籍（和古書・写本・版本）の翻刻と注釈を行う専門家です。

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


def build_user_content(ocr_text: str, image_path: str | Path | None, context: str = "") -> list[dict]:
    content: list[dict] = []
    if image_path:
        data, media = encode_image(image_path)
        content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    parts = []
    if context.strip():
        parts.append(f"資料についての補足情報:\n{context.strip()}\n")
    parts.append("OCR翻刻テキスト（誤認識を含む）:\n" + ocr_text.strip())
    parts.append("\n上記を校訂し、現代語訳と注釈を作成してください。")
    content.append({"type": "text", "text": "\n".join(parts)})
    return content


def annotate(ocr_text: str, image_path: str | Path | None = None, context: str = "", client=None) -> Annotation:
    """OCRテキストと画像を Claude に送り、構造化された校訂・現代語訳・注釈を返す。"""
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY が設定されていません。プロジェクト直下の .env に\n"
                "  ANTHROPIC_API_KEY=sk-ant-...\n"
                "を記入してください（.env.example をコピーして作成）。"
            )
        client = anthropic.Anthropic()
    with client.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": build_user_content(ocr_text, image_path, context)}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        raise RuntimeError(f"モデルが応答を拒否しました: {getattr(detail, 'explanation', '')}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("出力が長すぎて途中で切れました。ページを分割して再実行してください。")

    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return Annotation(
        **data,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
