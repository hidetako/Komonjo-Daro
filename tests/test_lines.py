import json
from types import SimpleNamespace

from PIL import Image

from kobun import lines
from kobun.store import Store


def test_normalize_boxes_orders_right_to_left():
    bx = [{"x": 10, "y": 5, "w": 30, "h": 200, "text": "左"}, {"x": 500.4, "y": 0, "w": 40, "h": 300}, {"x": 250, "y": 0, "w": 35, "h": 250}, {"x": 1, "y": 1, "w": 2, "h": 2}]
    out = lines.normalize_boxes(bx, 600, 400)
    assert [b["x"] for b in out] == [500, 250, 10] and out[2]["text"] == "左" and [b["id"] for b in out] == [0, 1, 2]
    assert lines.normalize_boxes([{"x": 590, "y": 0, "w": 100, "h": 50}], 600, 400)[0]["w"] == 10   # 画像内に丸める


class FakeAnthropic:
    def __init__(self):
        self.messages = self; self.calls = []

    def stream(self, **kw):
        self.calls.append(kw)
        ns = [int(b["text"][1:].split("（")[0]) for b in kw["messages"][0]["content"] if b["type"] == "text" and b["text"].startswith("行")]
        out = {"lines": [{"n": n, "text": f"読み{n}"} for n in ns]}

        class Ctx:
            def __enter__(s_):
                return SimpleNamespace(get_final_message=lambda: SimpleNamespace(stop_reason="end_turn", model=kw["model"],
                    content=[SimpleNamespace(type="text", text=json.dumps(out, ensure_ascii=False))], usage=SimpleNamespace(input_tokens=1, output_tokens=1)))

            def __exit__(s_, *a):
                return False
        return Ctx()


def test_ai_read_boxes_with_hints(tmp_path):
    p = tmp_path / "p.jpg"; Image.new("RGB", (800, 600), "white").save(p)
    boxes = [{"x": 700 - 60 * i, "y": 50, "w": 40, "h": 500} for i in range(8)]
    fake = FakeAnthropic()
    texts, tin, tout = lines.ai_read_boxes(p, boxes, "anthropic", "claude-opus-5-5", "high", "k", hints=["候補A"] + [""] * 7, client=fake)
    assert texts == [f"読み{i}" for i in range(1, 9)] and len(fake.calls) == 2
    first = fake.calls[0]["messages"][0]["content"]
    assert any(b["type"] == "text" and "OCR候補: 候補A" in b["text"] for b in first)
    assert "翻刻者" in fake.calls[0]["system"][0]["text"]


def test_save_lines_route(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import app as m
    c = m.app.test_client()
    st = Store(tmp_path / "data")
    jid = st.create_from_image(Image.new("RGB", (400, 300), "white"), "t", "g", 1, 1, "x.jpg")
    r = c.post(f"/job/{jid}/lines", json={"lines": [{"x": 300, "y": 10, "w": 30, "h": 200}, {"x": 100, "y": 10, "w": 30, "h": 200}]})
    assert r.get_json() == {"ok": True, "count": 2}
    job = st.load(jid)
    assert job["manual_lines"] and job["ocr"]["width"] == 400 and [b["x"] for b in job["ocr"]["lines"]] == [300, 100]
    body = c.get(f"/job/{jid}").get_data(as_text=True)
    assert "行を手で切る" in body and "行ごとに読む" in body and "（手動）" in body
