import base64
import io
import json
from types import SimpleNamespace

from PIL import Image

from kobun import jibo
from kobun.store import Store


def _page(path):
    im = Image.new("RGB", (1200, 900), "#f1e9d6")
    im.save(path, quality=90)
    return path


def _job(n_lines=3, fixed=True):
    lines = [{"id": i, "text": f"行{i}", "confidence": 0.9, "x": 1100 - 60 * i, "y": 100, "w": 40, "h": 700} for i in range(n_lines)]
    job = {"ocr": {"text": "\n".join(f"いま{i}" for i in range(n_lines)), "lines": lines, "width": 1200, "height": 900}}
    if fixed:
        job["annotation"] = {"honkoku": "\n".join(f"今{i}" for i in range(n_lines))}
    return job


def test_crop_and_batches(tmp_path):
    p = _page(tmp_path / "p.jpg")
    with Image.open(p) as im:
        c = jibo.crop_line(im, {"x": 100, "y": 100, "w": 40, "h": 700})
    assert min(c.size) >= jibo.MIN_SHORT and max(c.size) <= jibo.MAX_LONG and c.height > c.width
    job = _job(8)
    batches = jibo.build_batches(job, p, lines_per_call=6)
    assert [len(b) for b in batches] == [6, 2]
    assert batches[0][0]["n"] == 1 and batches[0][0]["text"] == "今0"      # 校訂済み翻刻の行が使われる
    assert len(base64.b64decode(batches[0][0]["b64"])) > 100
    # 校訂翻刻の行数が OCR と違えば OCR 生テキストを使う
    job2 = _job(3); job2["annotation"]["honkoku"] = "一行だけ"
    assert jibo.line_texts(job2) == ["いま0", "いま1", "いま2"]
    # 空行はスキップ
    job3 = _job(3); job3["annotation"]["honkoku"] = "今0\n\n今2"
    assert [it["n"] for it in jibo.build_batches(job3, p)[0]] == [1, 3]


class FakeAnthropic:
    def __init__(self):
        self.messages = self; self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        ns = [b["text"].split("翻刻")[0].replace("行", "").strip() for b in kwargs["messages"][0]["content"] if b["type"] == "text" and b["text"].startswith("行")]
        out = {"lines": [{"n": int(n), "jibo": f"以(い)万(ま){n}"} for n in ns]}

        class Ctx:
            def __enter__(s_):
                return SimpleNamespace(get_final_message=lambda: SimpleNamespace(
                    stop_reason="end_turn", model=kwargs["model"],
                    content=[SimpleNamespace(type="text", text=json.dumps(out, ensure_ascii=False))],
                    usage=SimpleNamespace(input_tokens=7, output_tokens=3)))

            def __exit__(s_, *a):
                return False
        return Ctx()


def test_run_jibo_batches_and_order(tmp_path):
    p = _page(tmp_path / "p.jpg")
    fake = FakeAnthropic()
    job = _job(8)
    text, tin, tout = jibo.run_jibo(job, p, "anthropic", "claude-opus-5-5", "high", "k", client=fake)
    assert len(fake.calls) == 2 and tin == 14 and tout == 6
    content = fake.calls[0]["messages"][0]["content"]
    assert sum(1 for b in content if b["type"] == "image") == 6
    assert "候補表" in fake.calls[0]["system"][0]["text"] and "者 八" in fake.calls[0]["system"][0]["text"]
    assert text.split("\n") == [f"以(い)万(ま){n}" for n in range(1, 9)]


def test_apply_to_job(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    st = Store(tmp_path / "data")
    im = Image.new("RGB", (1200, 900), "white")
    jid = st.create_from_image(im, "t p.1", "g", 1, 1, "d.pdf")
    j = st.load(jid); j.update(_job(2)); j["annotation"].update({"corrections": [], "gendaigo": "", "annotations": [], "uncertain": [], "summary": "", "era_guess": "", "model": "m", "input_tokens": 0, "output_tokens": 0}); st.save(jid, j)
    cfg = {"provider": "anthropic", "model": "claude-opus-5-5", "api_key": "k", "openai_model": "x", "openai_api_key": "", "effort": "high"}
    job = jibo.apply_to_job(st, jid, cfg, client=FakeAnthropic())
    assert job["annotation"]["jibo"].startswith("以(い)万(ま)1") and job["annotation"]["jibo_tokens"] == 10
    assert st.load(jid)["annotation"]["jibo"] == job["annotation"]["jibo"]
