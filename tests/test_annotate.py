import json

from PIL import Image

from kobun.annotate import OUTPUT_SCHEMA, Annotation, build_user_content, encode_image


def test_encode_image_shrinks(tmp_path):
    p = tmp_path / "big.png"
    Image.new("RGB", (4000, 3000), "white").save(p)
    data, media = encode_image(p)
    assert media == "image/jpeg"
    assert len(data) > 100


def test_build_user_content_with_and_without_image(tmp_path):
    p = tmp_path / "a.jpg"
    Image.new("RGB", (200, 300), "white").save(p)
    c = build_user_content("いろは", p, context="竹取物語 上")
    assert c[0]["type"] == "image" and c[1]["type"] == "text"
    assert "竹取物語" in c[1]["text"] and "いろは" in c[1]["text"]
    c2 = build_user_content("いろは", None)
    assert len(c2) == 1 and c2[0]["type"] == "text"


def test_annotation_markdown_roundtrip():
    sample = {
        "honkoku": "いまはむかし",
        "corrections": [{"line": 1, "ocr": "いま", "fixed": "今", "reason": "画像確認"}],
        "gendaigo": "今は昔", "annotations": [{"term": "今は昔", "note": "説話の冒頭定型句"}],
        "uncertain": ["2行目末尾"], "summary": "冒頭。", "era_guess": "江戸前期（推定）",
    }
    # スキーマの required をすべて満たしている
    assert set(sample) == set(OUTPUT_SCHEMA["required"])
    a = Annotation(**sample, model="test", input_tokens=1, output_tokens=2, jibo="以(い)万(ま)者(は)武(む)可(か)之(し)")
    md = a.to_markdown()
    assert "## 現代語訳" in md and "今は昔" in md and "説話の冒頭定型句" in md and "者(は)" in md
    # 字母なし（第2パス未実行）でも読める
    assert Annotation(**sample, model="t", input_tokens=1, output_tokens=1).jibo == ""
    json.dumps(a.to_dict(), ensure_ascii=False)
