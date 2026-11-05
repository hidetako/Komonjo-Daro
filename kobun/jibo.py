"""字母（変体仮名のもとの漢字）の判定を、行ごとの切り出し画像で行う第2パス。

NDL-Lite が返す行座標で原寸画像から行を切り出し、数行ずつ AI に渡す。
全体画像（長辺1568px）では 1 文字 40px 程度で字形が潰れるため、行単位（1 文字 100px 以上）で見せる。
各かなに有り得る字母の候補表を渡し、その中から選ばせる（知識で埋める余地を減らす）。
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageOps

from . import llm

LINES_PER_CALL = 6
PAD = 10            # 切り出しの余白(px)
MIN_SHORT = 96      # 短辺（行幅）がこれより小さい行は拡大して渡す（1文字がおよそ100px以上になる）
MAX_LONG = 1500     # 長辺の上限（これ以上は縮小）

# 各かなに有り得る字母（万葉仮名・変体仮名）の候補。先頭が現行平仮名の標準字母。
JIBO_CANDIDATES = {
    "あ": "安 阿 愛 悪", "い": "以 伊 意 移", "う": "宇 有 雲 憂", "え": "衣 江 盈 要", "お": "於 遠 隠",
    "か": "加 可 閑 家 嘉 歌 賀 駕", "き": "幾 起 支 喜 貴 木 期 季", "く": "久 具 九 供 求 倶 君", "け": "計 介 遣 希 気 景 希",
    "こ": "己 古 故 許 期 虚 子", "さ": "左 佐 散 斜 作 沙 差", "し": "之 志 四 事 新 師 思", "す": "寸 春 須 数 寿 受 州",
    "せ": "世 勢 聲 瀬", "そ": "曽 所 楚 処 蘇", "た": "太 多 堂 當 田 達", "ち": "知 千 地 智 遅 致",
    "つ": "川 津 徒 都 鶴 春 門", "て": "天 帝 弖 轉 亭 傳 手", "と": "止 登 東 度 土 斗 都", "な": "奈 那 難 南 菜 名 成",
    "に": "仁 尓 二 爾 丹 耳 児", "ぬ": "奴 怒 努", "ね": "祢 年 子 根 熱", "の": "乃 能 農 濃 野",
    "は": "波 者 八 盤 葉 半 破 者", "ひ": "比 飛 悲 日 非 避 備", "ふ": "不 婦 布 富 風 福 部", "へ": "部 遍 邊 弊 平 閉",
    "ほ": "保 本 報 豊 奉 寶", "ま": "末 満 万 麻 馬 間 真", "み": "美 三 見 身 微 弥", "む": "武 無 牟 舞 無 務",
    "め": "女 免 面 馬 目", "も": "毛 裳 母 茂 持 文", "や": "也 屋 夜 耶 哉 野", "ゆ": "由 遊 游 弓",
    "よ": "与 餘 代 世 夜 用 誉", "ら": "良 羅 等 楽 羅", "り": "利 里 理 李 離 梨", "る": "留 流 類 累 累",
    "れ": "礼 連 麗 例", "ろ": "呂 路 露 楼", "わ": "和 王 若 倭", "ゐ": "為 井 遺 位", "ゑ": "恵 衛 慧", "を": "遠 越 乎 緒 雄", "ん": "无 牟",
}

SYSTEM = """あなたは日本古典籍（版本・写本）の変体仮名を判定する専門家です。
行ごとに切り出した画像と、その行の翻刻（現行の平仮名に正規化済み）が与えられます。
各かなについて、画像の字形から字母（そのかなの元になった漢字）を判定し、「字母(かな)」の形で書き直してください。

規則:
- 字母は与えられた候補表の中から選ぶ。候補のどれとも字形が合わないときは、先頭の標準字母に ? を付ける（例: 可?(か)）。
- 現行の平仮名と同じ字形なら標準字母（候補表の先頭）を使う。
- 漢字はそのまま書く。踊り字（ゝ、〳〵）、濁点、句読点もそのまま。
- 翻刻の文字列を変えない。文字の追加・削除はしない（翻刻の誤りに気づいても、ここでは直さず、そのかなに最も近い字母を当てる）。
- 画像に本文以外（蔵書印、丁付、罫線）しか無い行は jibo を空にする。
- 画像が不鮮明で判定できないかなは標準字母に ? を付ける。推測で珍しい字母を当てない。

字母の候補表（かな: 標準字母 その他の候補）:
""" + "\n".join(f"{k}: {v}" for k, v in JIBO_CANDIDATES.items())

SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "行番号（与えられたもの）"},
                    "jibo": {"type": "string", "description": "字母(かな) 形式。本文でない行は空"},
                },
                "required": ["n", "jibo"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


def crop_line(im: Image.Image, line: dict) -> Image.Image:
    x, y, w, h = int(line["x"]), int(line["y"]), int(line["w"]), int(line["h"])
    box = (max(0, x - PAD), max(0, y - PAD), min(im.width, x + w + PAD), min(im.height, y + h + PAD))
    c = im.crop(box)
    short, long_ = min(c.size), max(c.size)
    if short < MIN_SHORT:
        k = MIN_SHORT / short
        c = c.resize((max(1, round(c.width * k)), max(1, round(c.height * k))), Image.LANCZOS)
    if max(c.size) > MAX_LONG:
        c.thumbnail((MAX_LONG, MAX_LONG))
    return c


def encode(c: Image.Image) -> tuple[str, str]:
    buf = io.BytesIO()
    c.convert("RGB").save(buf, format="JPEG", quality=92)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


def line_texts(job: dict) -> list[str]:
    """各 OCR 行に対応する翻刻文字列。校訂済み翻刻の行数が OCR 行数と一致すればそれを、違えば OCR 生テキストを使う。"""
    ocr = job.get("ocr") or {}
    raw = ocr.get("text", "").split("\n")
    ann = job.get("annotation") or {}
    fixed = (ann.get("honkoku") or "").split("\n") if ann else []
    return fixed if fixed and len(fixed) == len(raw) else raw


def build_batches(job: dict, image_path: str | Path, lines_per_call: int = LINES_PER_CALL) -> list[list[dict]]:
    """[(n, text, crop_b64, media)] を lines_per_call 件ずつにまとめる。"""
    ocr = job.get("ocr") or {}
    lines = ocr.get("lines") or []
    texts = line_texts(job)
    with Image.open(image_path) as src:
        im = ImageOps.exif_transpose(src).convert("RGB")
        items = []
        for i, line in enumerate(lines):
            text = texts[i] if i < len(texts) else ""
            if not text.strip():
                continue
            b64, media = encode(crop_line(im, line))
            items.append({"n": i + 1, "text": text, "b64": b64, "media": media})
    return [items[i:i + lines_per_call] for i in range(0, len(items), lines_per_call)]


def run_jibo(job: dict, image_path: str | Path, provider: str, model: str, effort: str, api_key: str,
             client=None) -> tuple[str, int, int]:
    """字母付き翻刻（全行を改行で結合）と、使用トークン数を返す。"""
    results: dict[int, str] = {}
    tin = tout = 0
    for batch in build_batches(job, image_path):
        parts: list[tuple] = [("text", "以下の各行について、画像の字形から字母を判定してください。")]
        for it in batch:
            parts.append(("text", f"行{it['n']} 翻刻: {it['text']}"))
            parts.append(("image", (it["b64"], it["media"])))
        r = llm.call_parts(provider, model, effort, api_key, SYSTEM, parts, SCHEMA, client=client)
        tin += r.input_tokens
        tout += r.output_tokens
        for ln in json.loads(r.text).get("lines", []):
            results[int(ln["n"])] = ln.get("jibo", "")
    ocr_lines = len((job.get("ocr") or {}).get("lines") or [])
    out = [results.get(n, "") for n in range(1, ocr_lines + 1)]
    return "\n".join(s for s in out if s.strip()), tin, tout


def apply_to_job(store, job_id: str, cfg: dict, client=None) -> dict:
    """保存済みジョブに字母の第2パスを実行して保存する。annotation が無ければ何もしない。"""
    from . import config as _config

    job = store.load(job_id)
    if not job.get("annotation") or not job.get("ocr"):
        return job
    provider, model, key = _config.active(cfg)
    img = store.media_path(job_id, job["original"])
    jibo, tin, tout = run_jibo(job, img, provider, model, cfg.get("effort", "high"), key, client=client)
    job = store.load(job_id)
    job["annotation"]["jibo"] = jibo
    job["annotation"]["jibo_tokens"] = tin + tout
    store.save(job_id, job)
    return job
