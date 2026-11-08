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


OUT = {"matched": True, "confidence": "high", "title": "古今和歌集 巻一", "author": "紀貫之", "source_text": "袖ひちて…", "reason": "語句が一致", "reread": "そでひちて\nむすびし水の",
       "candidates": [{"title": "古今和歌集 巻一", "author": "紀貫之", "source_text": "袖ひちて…", "fit": "断片が同順で一致"}]}


def test_match_builds_prompt(tmp_path):
    img = tmp_path / "a.jpg"; Image.new("RGB", (100, 100), "white").save(img)
    f = Fake(OUT)
    m = source_match.match("そてひちて\nむすひしみつの", img, "書作品", "anthropic", "m", "high", "k", client=f)
    assert m.matched and m.title.startswith("古今") and m.tokens == 5
    content = f.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and "荒い翻刻" in content[1]["text"] and "書作品" in content[1]["text"]
    assert "無理に有名作に当てない" in f.calls[0]["system"][0]["text"]
    assert "AI の読み" in content[1]["text"] and m.candidates[0]["fit"] == "断片が同順で一致"


def test_match_external_ocr_origin(tmp_path):
    f = Fake({**OUT, "matched": False, "candidates": []})
    m = source_match.match("かとほをにほてす", None, "", "anthropic", "m", "high", "k", client=f, loose_lines=True, external="古文書カメラ")
    sent = f.calls[0]["messages"][0]["content"][0]["text"]
    assert "「古文書カメラ」の結果" in sent and "暗唱はしない" in sent and "改行は無いか信頼できません" in sent
    assert not m.matched and m.candidates == []
    f2 = Fake({**OUT, "matched": False, "candidates": []})
    source_match.match("かとほ", None, "", "anthropic", "m", "high", "k", client=f2, external="みを", ai_reading="はなのか")
    sent2 = f2.calls[0]["messages"][0]["content"][0]["text"]
    assert "参考: AI が画像から校訂した翻刻" in sent2 and sent2.index("「みを」の結果") < sent2.index("はなのか")
    # candidates が無い応答でも壊れない
    out = {k: v for k, v in OUT.items() if k != "candidates"}
    assert source_match.match("x", None, "", "anthropic", "m", "high", "k", client=Fake(out)).candidates == []


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
    seen = {}
    monkeypatch.setattr(m.source_mod, "match", lambda *a, **k: (seen.update(k), source_match.SourceMatch(**OUT, model="m", tokens=1))[1])
    j = st.load(jid); j["ocr"]["external"] = "みを"; j["ocr"]["loose_lines"] = True; st.save(jid, j)
    r = c.post(f"/job/{jid}/source", follow_redirects=True)
    assert "典拠を照合しました" in r.get_data(as_text=True)
    assert seen["external"] == "みを" and seen["loose_lines"] is True and seen["ai_reading"] == ""
    assert "検討した候補（1）" in c.get(f"/job/{jid}").get_data(as_text=True)
    # 校訂後でも外部 OCR の生テキストが主入力で、AI の校訂案は参考として添える
    j = st.load(jid); j["annotation"] = {"honkoku": "AI の校訂"}; st.save(jid, j)
    c.post(f"/job/{jid}/source")
    assert seen["external"] == "みを" and seen["ai_reading"] == "AI の校訂"
    # 外部 OCR が無ければ従来どおり AI の翻刻を入力にする
    j = st.load(jid); j["ocr"].pop("external"); st.save(jid, j)
    c.post(f"/job/{jid}/source")
    assert seen["external"] == "" and seen["ai_reading"] == "" and seen["loose_lines"] is False
    assert st.load(jid)["source_match"]["title"] == "古今和歌集 巻一"
    # 採用 → 確定翻刻として retranslate へ
    monkeypatch.setattr(an, "annotate", lambda text, img, **kw: an.Annotation(honkoku=text, corrections=[], gendaigo="訳", annotations=[], uncertain=[], summary="s", era_guess="e", model="m", input_tokens=1, output_tokens=1))
    r = c.post(f"/job/{jid}/source/apply", follow_redirects=True)
    j = st.load(jid)
    assert j["annotation"]["honkoku"] == "そでひちて\nむすびし水の" and j["honkoku_fixed"] and not j["translation_stale"]
    assert "典拠: 古今和歌集 巻一（紀貫之）" in j["context"]


class FakeSearchAnthropic:
    """web_search ツール付き呼び出しの偽クライアント: 1 回目は pause_turn、2 回目に本文と検索結果を返す。"""
    def __init__(self):
        self.messages = self; self.calls = []

    def stream(self, **kw):
        self.calls.append(kw)
        n = len(self.calls)
        if n == 1:
            content = [SimpleNamespace(type="text", text="検索中")]
            stop = "pause_turn"
        else:
            content = [SimpleNamespace(type="server_tool_use", name="web_search"),
                       SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url="https://example.org/a", title="紅梅巻の歌"),
                                                                                SimpleNamespace(url="https://example.org/a", title="重複")]),
                       SimpleNamespace(type="text", text="候補: 源氏物語 紅梅巻「花の香を…」 出典 https://example.org/a")]
            stop = "end_turn"

        class Ctx:
            def __enter__(s_):
                return SimpleNamespace(get_final_message=lambda: SimpleNamespace(stop_reason=stop, model="m", content=content,
                                                                               usage=SimpleNamespace(input_tokens=10, output_tokens=5)))
            def __exit__(s_, *a):
                return False
        return Ctx()


def test_web_lookup_uses_search_tool_and_collects_sources():
    f = FakeSearchAnthropic()
    r = source_match.web_lookup("てほ遠よほとすやとに", "書作品", "anthropic", "m", "high", "k", client=f, external="古文書カメラ")
    assert len(f.calls) == 2 and f.calls[0]["tools"][0]["name"] == "web_search" and f.calls[0]["tools"][0]["max_uses"] == 8
    assert f.calls[0]["tools"][1]["name"] == "web_fetch" and f.calls[0]["tools"][1]["type"].startswith("web_fetch_")
    assert "web_fetch" in f.calls[0]["system"] and "匂はす宿に" in f.calls[0]["system"]
    assert "output_config" in f.calls[0] and "format" not in f.calls[0]["output_config"]   # 検索段は構造化出力なし
    assert "「古文書カメラ」" in f.calls[0]["messages"][0]["content"][0]["text"] and "調査員" in f.calls[0]["system"]
    assert f.calls[1]["messages"][1]["role"] == "assistant"   # pause_turn の続き
    assert "紅梅巻" in r.text and r.sources == [{"url": "https://example.org/a", "title": "紅梅巻の歌"}] and r.input_tokens == 20


def test_match_includes_web_notes():
    f = Fake(OUT)
    source_match.match("かとほ", None, "", "anthropic", "m", "high", "k", client=f, web_notes="候補: 紅梅巻")
    sent = f.calls[0]["messages"][0]["content"][0]["text"]
    assert "ウェブ検索による候補調査の結果" in sent and "候補: 紅梅巻" in sent


def test_source_route_with_web(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import app as m
    from kobun import llm
    st = Store(tmp_path / "data")
    jid = st.create_from_image(Image.new("RGB", (100, 100), "white"), "t", "g", 1, 1, "x.jpg")
    j = st.load(jid); j["ocr"] = {"text": "てほ遠よほとす", "lines": [], "width": 100, "height": 100, "external": "古文書カメラ", "loose_lines": True}; st.save(jid, j)
    c = m.app.test_client()
    c.post("/settings", data={"api_key": "sk-ant-x", "model": "claude-opus-5-5", "effort": "high", "device": "cpu", "data_dir": str(tmp_path / "data"), "provider": "anthropic", "preprocess": "on"})
    seen = {}
    monkeypatch.setattr(m.source_mod, "web_lookup", lambda *a, **k: llm.LlmResult("候補: 紅梅巻 出典 https://example.org/a", "m", 3, 4,
                                                                                   [{"url": "https://example.org/a", "title": "出典"}, {"url": "https://example.org/noise", "title": "無関係"}]))
    monkeypatch.setattr(m.source_mod, "match", lambda *a, **k: (seen.update(k), source_match.SourceMatch(**OUT, model="m", tokens=1))[1])
    c.post(f"/job/{jid}/source", data={"web": "on"})
    assert seen["web_notes"].startswith("候補: 紅梅巻")
    sm = st.load(jid)["source_match"]
    assert sm["web_notes"].startswith("候補: 紅梅巻") and sm["web_sources"][0]["url"] == "https://example.org/a" and sm["tokens"] == 8
    body = c.get(f"/job/{jid}").get_data(as_text=True)
    assert "ウェブ検索の調査メモ" in body and "https://example.org/a" in body
    assert "メモで引用した出典（1）" in body and "検索で当たった他のページ（1）" in body
    # チェックなしなら検索しない
    seen.clear(); c.post(f"/job/{jid}/source")
    assert seen["web_notes"] == ""


def test_low_confidence_match_shows_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import app as m
    st = Store(tmp_path / "data")
    jid = st.create_from_image(Image.new("RGB", (100, 100), "white"), "t", "g", 1, 1, "x.jpg")
    j = st.load(jid); j["ocr"] = {"text": "x", "lines": [], "width": 100, "height": 100}
    j["source_match"] = {**OUT, "confidence": "low"}; st.save(jid, j)
    body = m.app.test_client().get(f"/job/{jid}").get_data(as_text=True)
    assert "確信度 low:" in body and "有名作に寄せた推定" in body
    j["source_match"] = {**OUT, "confidence": "high"}; st.save(jid, j)
    body = m.app.test_client().get(f"/job/{jid}").get_data(as_text=True)
    assert "確信度 low:" not in body
