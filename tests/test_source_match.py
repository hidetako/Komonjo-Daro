import json
from types import SimpleNamespace

from PIL import Image

from kobun import source_match
from kobun.store import Store


class Fake:
    def __init__(self, out):
        self.messages = self; self.out = out; self.calls = []

    def stream(self, **kw):
        self.calls.append(kw)
        out = self.out

        class Ctx:
            def __enter__(s_):
                return SimpleNamespace(get_final_message=lambda: SimpleNamespace(stop_reason="end_turn", model="m",
                    content=[SimpleNamespace(type="text", text=json.dumps(out, ensure_ascii=False))], usage=SimpleNamespace(input_tokens=2, output_tokens=3)))

            def __exit__(s_, *a):
                return False
        return Ctx()


OUT = {"matched": True, "confidence": "high", "title": "古今和歌集 巻一", "author": "紀貫之", "source_text": "袖ひちて…", "reason": "語句が一致", "reread": "そでひちて\nむすびし水の"}


def test_match_builds_prompt(tmp_path):
    img = tmp_path / "a.jpg"; Image.new("RGB", (100, 100), "white").save(img)
    f = Fake(OUT)
    m = source_match.match("そてひちて\nむすひしみつの", img, "書作品", "anthropic", "m", "high", "k", client=f)
    assert m.matched and m.title.startswith("古今") and m.tokens == 5
    content = f.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and "荒い翻刻" in content[1]["text"] and "書作品" in content[1]["text"]
    assert "無理に有名作に当てない" in f.calls[0]["system"][0]["text"]


def test_source_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import app as m
    import kobun.annotate as an
    st = Store(tmp_path / "data")
    jid = st.create_from_image(Image.new("RGB", (100, 100), "white"), "t", "g", 1, 1, "x.jpg")
    j = st.load(jid); j["ocr"] = {"text": "そてひちて\nむすひしみつの", "lines": [], "width": 100, "height": 100}; st.save(jid, j)
    c = m.app.test_client()
    c.post("/settings", data={"api_key": "sk-ant-x", "model": "claude-opus-5-5", "effort": "high", "device": "cpu", "data_dir": str(tmp_path / "data"), "provider": "anthropic", "preprocess": "on"})
    monkeypatch.setattr(m.source_mod, "match", lambda *a, **k: source_match.SourceMatch(**OUT, model="m", tokens=1))
    r = c.post(f"/job/{jid}/source", follow_redirects=True)
    assert "典拠を照合しました" in r.get_data(as_text=True)
    assert st.load(jid)["source_match"]["title"] == "古今和歌集 巻一"
    # 採用 → 確定翻刻として retranslate へ
    monkeypatch.setattr(an, "annotate", lambda text, img, **kw: an.Annotation(honkoku=text, corrections=[], gendaigo="訳", annotations=[], uncertain=[], summary="s", era_guess="e", model="m", input_tokens=1, output_tokens=1))
    r = c.post(f"/job/{jid}/source/apply", follow_redirects=True)
    j = st.load(jid)
    assert j["annotation"]["honkoku"] == "そでひちて\nむすびし水の" and j["honkoku_fixed"] and not j["translation_stale"]
    assert "典拠: 古今和歌集 巻一（紀貫之）" in j["context"]
