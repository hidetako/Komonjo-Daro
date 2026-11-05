import json
from types import SimpleNamespace

from kobun.annotate import build_user_text
from kobun.store import Store

SAMPLE = {"honkoku": "x", "corrections": [], "gendaigo": "y", "annotations": [], "uncertain": [], "summary": "s", "era_guess": "e"}


def test_glossary_crud_and_import(tmp_path):
    st = Store(tmp_path)
    assert st.glossary() == []
    assert st.glossary_add("真田昌幸", "さなだまさゆき", "上田城主") is True
    assert st.glossary_add("真田昌幸", "", "信濃上田城主") is False      # 更新
    assert st.glossary_add("   ") is False
    g = st.glossary()
    assert len(g) == 1 and g[0]["reading"] == "さなだまさゆき" and g[0]["note"] == "信濃上田城主"
    st.glossary_delete(g[0]["id"])
    assert st.glossary() == []


def test_prompt_includes_glossary_and_prior_pages(tmp_path):
    st = Store(tmp_path)
    st.glossary_add("海野", "うんの", "滋野氏の一族")
    text = build_user_text("いまはむかし", "", st.glossary(), [{"page": 2, "annotation": {"honkoku": "ものありけり", "annotations": [{"term": "翁"}]}}])
    assert "用語集" in text and "海野（うんの）: 滋野氏の一族" in text
    assert "[p.2] 翻刻:\nものありけり" in text and "注釈語: 翁" in text
    assert text.index("用語集") < text.index("前ページ") < text.index("OCR翻刻テキスト")
    assert "用語集" not in build_user_text("x")


def test_prior_pages_from_group(tmp_path):
    from PIL import Image
    st = Store(tmp_path)
    im = Image.new("RGB", (100, 100), "white")
    ids = [st.create_from_image(im, f"t p.{n}", "g1", n, 5, "d.pdf") for n in range(1, 6)]
    for n, jid in enumerate(ids, 1):
        if n in (1, 2, 3, 5):
            j = st.load(jid); j["annotation"] = dict(SAMPLE, honkoku=f"p{n}"); st.save(jid, j)
    job4 = st.load(ids[3])
    prior = st.prior_pages(job4)
    assert [p["page"] for p in prior] == [1, 2, 3]
    assert st.prior_pages(st.load(ids[0])) == []
    assert st.prior_pages({"id": "x"}) == []


def test_glossary_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import app as m
    c = m.app.test_client()
    assert c.get("/glossary").status_code == 200
    c.post("/glossary/add", data={"term": "上田", "reading": "うえだ", "note": "信濃国小県郡"})
    c.post("/glossary/import", data={"bulk": "真田昌幸,さなだまさゆき,上田城主\n海野（うんの）: 滋野氏の一族\n"})
    body = c.get("/glossary").get_data(as_text=True)
    assert "上田" in body and "真田昌幸" in body and "うんの" in body
    entries = json.loads((tmp_path / "data" / "glossary.json").read_text(encoding="utf-8"))
    assert {e["term"] for e in entries} == {"上田", "真田昌幸", "海野"}
