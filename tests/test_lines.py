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


def test_normalize_boxes_manual_order():
    # 散らし書き: 幾何学的には右→左だが、手で付けた order が優先される
    bx = [{"x": 500, "y": 0, "w": 40, "h": 300, "order": 2}, {"x": 250, "y": 0, "w": 35, "h": 250, "order": 1}, {"x": 10, "y": 5, "w": 30, "h": 200, "order": 3}]
    out = lines.normalize_boxes(bx, 600, 400)
    assert [b["x"] for b in out] == [250, 500, 10] and [b["order"] for b in out] == [1, 2, 3]
    # 一部にしか order が無ければ自動順に戻し、order は残さない
    bx[2].pop("order")
    out = lines.normalize_boxes(bx, 600, 400)
    assert [b["x"] for b in out] == [500, 250, 10] and all("order" not in b for b in out)


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
    texts, tin, tout = lines.ai_read_boxes(p, boxes, "anthropic", "claude-opus-5-5", "high", "k", hints=["候補A"] + [""] * 7, client=fake, context="紅梅巻の歌")
    assert texts == [f"読み{i}" for i in range(1, 9)] and len(fake.calls) == 2
    first = fake.calls[0]["messages"][0]["content"]
    assert any(b["type"] == "text" and "OCR候補: 候補A" in b["text"] for b in first)
    assert "翻刻者" in fake.calls[0]["system"][0]["text"]
    # 全体図が各呼び出しの先頭に付き、行の切り出しはその後に続く（1 回目: 全体図 1 + 行 6）
    imgs = [b for b in first if b["type"] == "image"]
    assert len(imgs) == 7 and first[0]["type"] == "text" and "作品全体" in first[0]["text"] and first[1]["type"] == "image"
    assert any(b["type"] == "text" and "紅梅巻の歌" in b["text"] for b in first)
    assert len([b for b in fake.calls[1]["messages"][0]["content"] if b["type"] == "image"]) == 3


def test_overview_image_marks_boxes():
    im = Image.new("RGB", (800, 600), "white")
    ov = lines.overview_image(im, [{"x": 100, "y": 50, "w": 40, "h": 500}])
    assert ov.size == (800, 600) and ov.getpixel((100, 300)) != (255, 255, 255)   # 枠線が描かれている
    big = lines.overview_image(Image.new("RGB", (4000, 1000), "white"), [])
    assert max(big.size) == lines.OVERVIEW_EDGE


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


def test_save_lines_rescales_from_preview_space(tmp_path, monkeypatch):
    """ocr.width が無い直接翻刻ジョブで、画面が preview（長辺 2000px）の座標で枠を送ってきたら原寸に換算する。"""
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import app as m
    c = m.app.test_client()
    st = Store(tmp_path / "data")
    jid = st.create_from_image(Image.new("RGB", (4000, 1000), "white"), "t", "g", 1, 1, "x.jpg")
    job = st.load(jid); job["ocr"] = {"text": "", "lines": [], "width": 0, "height": 0, "viz_path": None}; st.save(jid, job)
    r = c.post(f"/job/{jid}/lines", json={"lines": [{"x": 1000, "y": 100, "w": 50, "h": 300}], "ref": {"w": 2000, "h": 500}})
    assert r.get_json()["count"] == 1
    b = st.load(jid)["ocr"]["lines"][0]
    assert (b["x"], b["y"], b["w"], b["h"]) == (2000, 200, 100, 600) and st.load(jid)["ocr"]["width"] == 4000
    # 同じ座標系なら無換算
    r = c.post(f"/job/{jid}/lines", json={"lines": [{"x": 1000, "y": 100, "w": 50, "h": 300}], "ref": {"w": 4000, "h": 1000}})
    assert st.load(jid)["ocr"]["lines"][0]["x"] == 1000


def test_direct_job_records_image_size(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import io
    import app as m
    c = m.app.test_client()
    buf = io.BytesIO(); Image.new("RGB", (3000, 800), "white").save(buf, format="JPEG")
    r = c.post("/ocr", data={"image": (io.BytesIO(buf.getvalue()), "w.jpg"), "title": "d", "direct": "on"}, content_type="multipart/form-data")
    assert r.status_code == 302 and "/direct" in r.headers["Location"]
    jid = r.headers["Location"].rstrip("/").split("/")[-2]
    job = Store(tmp_path / "data").load(jid)
    assert job["from_image"] and (job["ocr"]["width"], job["ocr"]["height"]) == (3000, 800)


def test_paste_mode_registers_without_ocr(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import io
    import app as m
    c = m.app.test_client()
    buf = io.BytesIO(); Image.new("RGB", (1200, 400), "white").save(buf, format="JPEG")
    r = c.post("/ocr", data={"image": (io.BytesIO(buf.getvalue()), "w.jpg"), "title": "p", "mode": "paste"}, content_type="multipart/form-data")
    assert r.status_code == 302 and r.headers["Location"].rstrip("/").endswith(tuple("0123456789abcdef")) and "/direct" not in r.headers["Location"]
    jid = r.headers["Location"].rstrip("/").split("/")[-1]
    job = Store(tmp_path / "data").load(jid)
    assert job["ocr"]["text"] == "" and (job["ocr"]["width"], job["ocr"]["height"]) == (1200, 400) and not job.get("from_image")
    body = c.get(f"/job/{jid}").get_data(as_text=True)
    assert "外部の OCR 結果を貼る" in body and "行を手で切る" in body
