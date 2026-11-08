"""典拠の照合: 荒い翻刻から既知の和歌・漢詩・文章を当て、原典を手がかりに読み直す。

書作品の多くは有名な和歌・詩文なので、原典が分かれば読みが大きく安定する。
ただし AI が「それらしい有名作」に寄せる危険があるため、結果は利用者が確認して採用する。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import llm
from .annotate import encode_image

SYSTEM = """あなたは日本古典文学・漢詩文に通じた翻刻の専門家です。出力はすべて日本語で書きます。
書作品や古典籍の画像と、荒い翻刻（誤読を含む）が与えられます。荒い翻刻の出どころ（AI の読みか、専用のくずし字 OCR か）は
ユーザーメッセージに書いてあります。専用 OCR の結果は、誤読は多いが有名作を暗唱することはなく、文字の並びは画像の読み順です。
その場合は断片（例: 「にほはす」「人のた」）を積極的に検索の手がかりにしてください。

0. まず、荒い翻刻の断片と画像から思い当たる作品の候補を最大 5 つ挙げてください（candidates）。それぞれ原典本文と、
   断片・画像とどの程度合うか（fit）を短く書く。候補を挙げるときは、断片が「同じ作品の同じ順序」で現れるかを重視する。
   1 つも思い当たらなければ candidates は空でよい。
1. 候補を画像の各行と照合し、この文章が既知の作品（和歌・連歌・俳諧・漢詩・物語・仏典・書簡の定型句など）に当たるかを判定してください。
   - 一致すると考える場合: 出典（歌集名・巻・番号、作者、作品名）と、その原典本文を示してください。
     原典本文は定本の表記（歴史的仮名遣い、漢字仮名交じり）で。確信度 high / medium / low と根拠（どの語句が一致したか）。
   - 物語・日記中の歌（源氏物語の巻中の贈答歌など）は、作品名・巻名・詠者・場面まで示してください。
   - 書作品には複数首（贈歌と返歌、連作など）が書かれることが多く、原典とは順序が入れ替わっていることもあります。
     その場合は source_text に画像に書かれた順で全首を示し、reason でどの首がどの行に当たるかを書いてください。
   - 荒い翻刻が AI の読みである場合は、有名作を暗唱して書かれている可能性があります。その場合、一致の判定は画像の字形との
     照合を根拠にし、翻刻テキストが有名作と一致するだけでは high にしないでください。
   - 荒い翻刻が専用 OCR の結果である場合は、複数の断片が候補作品の同じ順序で現れ、画像の行の長さ・配置と矛盾しなければ
     medium 以上としてよい。画像だけで字形を確定できなくても、断片の一致は根拠に数えてよい。
   - 一致しない、または判断できない場合: matched を false にし、無理に有名作に当てないでください。
2. 一致する場合は、原典を手がかりに画像の各行を読み直した翻刻（reread）を作ってください。
   - 行構成は与えられた翻刻と同じ行数・順序を保つ。
   - 表記は画像のとおり（変体仮名は現行平仮名に、漢字は画像の漢字のまま）。原典と画像が明らかに違う箇所は画像を優先し、〔 〕で示す。
   - 書作品では一部の語が省かれたり、順序が変わることがある。画像に無い語を補わない。
3. 一致しない場合、reread は空にしてください。
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "matched": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low", "none"]},
        "title": {"type": "string", "description": "作品名・歌集名など"},
        "author": {"type": "string"},
        "source_text": {"type": "string", "description": "原典本文（定本の表記）"},
        "reason": {"type": "string", "description": "一致と判断した根拠"},
        "reread": {"type": "string", "description": "原典を手がかりに読み直した翻刻。行構成は元と同じ"},
        "candidates": {
            "type": "array",
            "description": "思い当たった作品の候補（最大 5 つ）。一致しなかった場合も残す",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "source_text": {"type": "string"},
                    "fit": {"type": "string", "description": "断片・画像とどう合う／合わないか"},
                },
                "required": ["title", "author", "source_text", "fit"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["matched", "confidence", "title", "author", "source_text", "reason", "reread", "candidates"],
    "additionalProperties": False,
}


@dataclass
class SourceMatch:
    matched: bool
    confidence: str
    title: str
    author: str
    source_text: str
    reason: str
    reread: str
    candidates: list = field(default_factory=list)
    model: str = ""
    tokens: int = 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def match(honkoku: str, image_path: str | Path | None, context: str, provider: str, model: str, effort: str,
          api_key: str, client=None, loose_lines: bool = False, external: str = "") -> SourceMatch:
    """external は荒い翻刻の出どころ（「みを」「古文書カメラ」など専用 OCR の名前）。空なら AI の読みとして扱う。"""
    parts: list[tuple] = []
    if image_path:
        parts.append(("image", encode_image(image_path)))
    text = ""
    if context.strip():
        text += f"資料についての補足情報:\n{context.strip()}\n\n"
    origin = (f"専用のくずし字 OCR アプリ「{external}」の結果。誤読は多いが有名作の暗唱はしない。文字の並びは画像の読み順"
              if external else "AI の読み。読めない箇所を有名作で埋めている可能性がある")
    text += f"荒い翻刻（誤読を含む。出どころ: {origin}）:\n" + honkoku.strip() + "\n\nまず候補を挙げ、この文章の典拠を判定し、一致すれば原典を手がかりに読み直してください。"
    if loose_lines:
        text += ("\n注意: この翻刻は外部のくずし字認識アプリの結果で、改行は無いか信頼できません。文字の順序はおおむね画像の読み順です。"
                 "reread は与えられた行構成に合わせず、画像の行に合わせて改行してください。")
    parts.append(("text", text))
    r = llm.call_parts(provider, model, effort, api_key, SYSTEM, parts, SCHEMA, client=client)
    data = json.loads(r.text)
    data.setdefault("candidates", [])
    return SourceMatch(**data, model=r.model, tokens=r.input_tokens + r.output_tokens)
