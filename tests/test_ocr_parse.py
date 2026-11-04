import json
from pathlib import Path

from kobun.ocr_ndl import parse_output

SAMPLE_JSON = {
    "contents": [[
        {"boundingBox": [[100, 50], [100, 900], [140, 50], [140, 900]], "id": 0, "isVertical": "true",
         "text": "いまはむかしたけとりのおきなといふ", "isTextline": "true", "confidence": 0.93},
        {"boundingBox": [[60, 50], [60, 880], [98, 50], [98, 880]], "id": 1, "isVertical": "true",
         "text": "ものありけり野山にましりてたけ", "isTextline": "true", "confidence": 0.88},
    ]],
    "imginfo": {"img_width": 1200, "img_height": 1000, "img_path": "x/page.jpg", "img_name": "page.jpg"},
}
SAMPLE_TXT = "いまはむかしたけとりのおきなといふ\nものありけり野山にましりてたけ\n"


def test_parse_output():
    r = parse_output(SAMPLE_TXT, SAMPLE_JSON)
    assert r.width == 1200 and r.height == 1000
    assert len(r.lines) == 2
    assert r.lines[0].x == 100 and r.lines[0].w == 40 and r.lines[0].h == 850
    assert r.lines[0].vertical
    assert r.text.splitlines()[0] == "いまはむかしたけとりのおきなといふ"
    d = r.to_dict()
    json.dumps(d, ensure_ascii=False)  # JSON化できること
