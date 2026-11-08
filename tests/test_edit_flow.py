import json
from types import SimpleNamespace

from PIL import Image

from kobun.annotate import annotate, build_user_text
from kobun.store import Store

ANN = {"honkoku": "いまはむかし\nものありけり", "corrections": [{"line": 1, "ocr": "x", "fixed": "y", "reason": "r"}], "gendaigo": "今は昔", "annotations": [], "uncertain": [], "summary": "s", "era_guess": "e", "model": "m", "input_tokens": 1, "output_tokens": 1}


class Fake:
    def __init__(self):
        self.messages = self; self.calls = []

    def stream(self, **kw):
        self.calls.append(kw)
        out = dict(ANN); out = {k: out[k] for k in ["honkoku", "corrections", "gendaigo", "annotations", "uncertain", "summary", "era_guess"]}
        out["honkoku"] = "AIが勝手に変えた翻刻"; out["gendaigo"] = "新しい訳"

        class Ctx:
            def __enter__(s_):
                return SimpleNamespace(get_final_message=lambda: SimpleNamespace(stop_reason="end_turn", model="m",
                    content=[SimpleNamespace(type="text", text=json.dumps(out, ensure_ascii=False))], usage=SimpleNamespace(input_tokens=1, output_tokens=1)))

            def __exit__(s_, *a):
                return False
        return Ctx()


def test_fixed_mode_keeps_user_honkoku(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    t = build_user_text("いまはむかし", fixed=True)
    assert "確定翻刻" in t and "1 字も変えず" in t
    a = annotate("いまはむかし\nものありけり", None, client=Fake(), provider="anthropic", model="m", fixed=True)
    assert a.honkoku == "いまはむかし\nものありけり" and a.corrections == [] and a.gendaigo == "新しい訳"


def test_edit_flow_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import app as m
    import kobun.annotate as an
    st = Store(tmp_path / "data")
    jid = st.create_from_image(Image.new("RGB", (100, 100), "white"), "t", "g", 1, 1, "x.jpg")
    j = st.load(jid); j["annotation"] = dict(ANN); j["ocr"] = {"text": "a\nb", "lines": [], "width": 100, "height": 100}; st.save(jid, j)
    c = m.app.test_client()
    # 翻刻だけ保存 → 訳が古い印
    r = c.post(f"/job/{jid}/honkoku", data={"honkoku": "いまはむかし\nものありけり野山に", "then": "save"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "翻刻を保存しました" in body and "翻刻が修正されています" in body
    j = st.load(jid)
    assert j["translation_stale"] and j["honkoku_fixed"] and j["annotation"]["corrections"] == []
    # 作り直し（AI は翻刻を変えない）
    monkeypatch.setattr(m, "annotate", None, raising=False)
    monkeypatch.setattr(an, "annotate", lambda text, img, **kw: (_ for _ in ()).throw(RuntimeError("no key")) if False else an.Annotation(
        honkoku=text, corrections=[], gendaigo="直した訳", annotations=[], uncertain=[], summary="s", era_guess="e", model="m", input_tokens=1, output_tokens=1))
    r = c.post(f"/job/{jid}/retranslate", follow_redirects=True)
    assert "作り直しました" in r.get_data(as_text=True)
    j = st.load(jid)
    assert not j["translation_stale"] and j["annotation"]["honkoku"] == "いまはむかし\nものありけり野山に" and j["annotation"]["gendaigo"] == "直した訳"
    # 訳文の手直し
    c.post(f"/job/{jid}/gendaigo", data={"gendaigo": "手で直した訳"})
    assert st.load(jid)["annotation"]["gendaigo"] == "手で直した訳" and st.load(jid)["gendaigo_edited"]


def test_external_ocr_text_registers_as_loose_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    from PIL import Image
    import app as m
    from kobun.store import Store
    c = m.app.test_client()
    st = Store(tmp_path / "data")
    jid = st.create_from_image(Image.new("RGB", (800, 300), "white"), "t", "g", 1, 1, "x.jpg")
    job = st.load(jid); job["annotation"] = {"honkoku": "旧"}; job["honkoku_fixed"] = True; job["source_match"] = {"matched": False}; st.save(jid, job)
    r = c.post(f"/job/{jid}/ocrtext", data={"text": "かとほをにほてすとにとゆ", "source": "みを", "loose": "on"})
    assert r.status_code == 302
    job = st.load(jid)
    assert job["ocr"]["text"] == "かとほをにほてすとにとゆ" and job["ocr"]["external"] == "みを" and job["ocr"]["loose_lines"] is True
    assert job["ocr"]["width"] == 800 and "annotation" not in job and "honkoku_fixed" not in job and "source_match" not in job
    body = c.get(f"/job/{jid}").get_data(as_text=True)
    assert "みを の結果" in body and "かとほをにほてすとにとゆ" in body
    # 改行付きで loose を外せば行構成を保つ
    c.post(f"/job/{jid}/ocrtext", data={"text": "あ\r\nい", "source": "古文書カメラ"})
    assert st.load(jid)["ocr"]["loose_lines"] is False and st.load(jid)["ocr"]["text"] == "あ\nい"
    assert c.post(f"/job/{jid}/ocrtext", data={"text": "  "}).status_code == 302 and st.load(jid)["ocr"]["text"] == "あ\nい"


def test_loose_lines_prompt_text():
    from kobun.annotate import build_user_text
    from kobun import source_match
    t = build_user_text("かとほをにほてす", loose_lines=True)
    assert "行の区切りが不明" in t and "行数の一致は求めません" in t and "有名な和歌" in t
    assert "行の区切りが不明" not in build_user_text("かとほ\nをにほ")

    class Fake:
        def __init__(self): self.messages = self; self.calls = []
        def stream(self, **kw):
            self.calls.append(kw)
            import json as _j
            from types import SimpleNamespace as NS
            out = {"matched": False, "confidence": "none", "title": "", "author": "", "source_text": "", "reason": "", "reread": ""}
            class Ctx:
                def __enter__(s_): return NS(get_final_message=lambda: NS(stop_reason="end_turn", model=kw["model"], content=[NS(type="text", text=_j.dumps(out))], usage=NS(input_tokens=1, output_tokens=1)))
                def __exit__(s_, *a): return False
            return Ctx()
    f = Fake()
    source_match.match("かとほ", None, "", "anthropic", "claude-opus-5-5", "high", "k", client=f, loose_lines=True)
    sent = "".join(b["text"] for b in f.calls[0]["messages"][0]["content"] if b["type"] == "text")
    assert "改行は無いか信頼できません" in sent
