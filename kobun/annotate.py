"""翻刻テキスト（＋画像）を LLM（Claude / GPT）に渡し、校訂・現代語訳・注釈を構造化JSONで受け取る。"""
from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass, field
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
- honkoku: 校訂済みの翻刻。OCR翻刻テキストと同じ行数・同じ順序を必ず保つ（1行目は1行目に対応）。
  行の中の文字だけを直し、行を増減・結合・分割しない。本文でない行（蔵書印・丁付など）は空行にして残す。
  仮名・漢字は原文のままにし、濁点・句読点を勝手に補わない。判読できない文字は「■」、推定を含む文字は〔 〕で囲む。
  〔 〕は、画像の字形から読みをある程度絞り込めるが確信がない場合にだけ使う。字形そのものが読めない文字は 1 字ずつ「■」にする。文脈や和歌らしさから「それらしい語句」を補って〔 〕に入れてはならない（創作された翻刻は ■ より有害）。数文字しか読めない行は、読めた文字と ■ だけで書く。
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
    jibo: str = ""          # 第2パス（kobun/jibo.py: 行切り出し）で付く。無ければ空
    jibo_tokens: int = 0    # 第2パスの使用トークン（入力+出力）
    jibo_lines: list = field(default_factory=list)   # [{"text": 翻刻行, "jibo": 字母付き行}]

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    def to_markdown(self) -> str:
        md = ["## 翻刻（校訂済）", "", self.honkoku, "", "## 現代語訳", "", self.gendaigo, ""]
        if self.jibo_lines:
            md += ["## 字母付き翻刻（変体仮名のもとの漢字）", ""] + [f"{p['text']}\n　{p['jibo']}" for p in self.jibo_lines] + [""]
        elif self.jibo:
            md += ["## 字母付き翻刻（変体仮名のもとの漢字）", "", self.jibo, ""]
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


PRIOR_CHARS = 3000   # 前ページの参考として渡す上限（翻刻＋注釈語）


def build_user_text(ocr_text: str, context: str = "", glossary: list[dict] | None = None,
                    prior_pages: list[dict] | None = None, fixed: bool = False) -> str:
    parts = []
    if context.strip():
        parts.append(f"資料についての補足情報:\n{context.strip()}\n")
    if glossary:
        lines = []
        for g in glossary:
            line = f"- {g.get('term', '')}"
            if g.get("reading"):
                line += f"（{g['reading']}）"
            if g.get("note"):
                line += f": {g['note']}"
            lines.append(line)
        parts.append("用語集（利用者が確定した表記・読み・注。翻刻・現代語訳・注釈ではこれに従い、同じ語に別の表記を当てない）:\n" + "\n".join(lines) + "\n")
    if prior_pages:
        buf, used = [], 0
        for pg in prior_pages:
            ann = pg.get("annotation") or {}
            terms = "、".join(a.get("term", "") for a in ann.get("annotations", []) if a.get("term"))
            block = f"[p.{pg.get('page')}] 翻刻:\n{ann.get('honkoku', '')}\n注釈語: {terms}\n"
            if used + len(block) > PRIOR_CHARS:
                block = block[: max(0, PRIOR_CHARS - used)]
            buf.append(block)
            used += len(block)
            if used >= PRIOR_CHARS:
                break
        parts.append("同じ文書の前ページ（確定済み。人名・地名・用語の表記と仮名遣いを揃え、文脈の続きとして読む）:\n" + "\n".join(buf))
    if fixed and ocr_text.strip():
        parts.append("確定翻刻（利用者が校訂済み。これが正本）:\n" + ocr_text.strip())
        parts.append("\n翻刻は確定しています。honkoku にはこの文字列をそのまま（行構成も含めて 1 字も変えずに）返し、corrections は空にしてください。"
                     "画像は語の解釈や判読の参考にのみ使い、翻刻を直さないでください。現代語訳・注釈・不確実な箇所・要約・推定時代を作成してください。")
    elif ocr_text.strip():
        parts.append("OCR翻刻テキスト（誤認識を含む）:\n" + ocr_text.strip())
        parts.append("\n上記を校訂し、現代語訳と注釈を作成してください。")
    else:
        parts.append("OCR の結果はありません（散らし書き・写真などで OCR が機能しなかった資料です）。"
                     "画像から直接、行ごとに翻刻してください。corrections は空でよい。行の切れ目は画像の行に合わせ、"
                     "散らし書きで行頭の高さが違っても 1 行は 1 行として書く。読めない文字は ■ とし、推測で語句を作らない。有名な和歌・詩文の本文を思い出して書かない。")
        parts.append("\n画像を翻刻し、現代語訳と注釈を作成してください。")
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
             provider: str | None = None, glossary: list[dict] | None = None,
             prior_pages: list[dict] | None = None, fixed: bool = False) -> Annotation:
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
    r = llm.call(provider, model, effort, key, SYSTEM_PROMPT, build_user_text(ocr_text, context, glossary, prior_pages, fixed), image, OUTPUT_SCHEMA, client=client)
    data = llm.parse_json(r.text)
    if fixed:
        # 確定翻刻は AI の返答にかかわらず利用者の文字列を正本にする
        data["honkoku"] = ocr_text.strip("\n")
        data["corrections"] = []
    return Annotation(**data, model=r.model, input_tokens=r.input_tokens, output_tokens=r.output_tokens)
