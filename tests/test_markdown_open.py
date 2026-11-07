from PIL import Image

from kobun.store import Store

ANN = {"honkoku": "いまはむかし", "corrections": [], "gendaigo": "今は昔", "annotations": [], "uncertain": [], "summary": "s", "era_guess": "e", "model": "m", "input_tokens": 1, "output_tokens": 1}


def test_export_markdown_sanitizes_name(tmp_path):
    st = Store(tmp_path)
    p = st.export_markdown('竹取物語 上 2丁表: "a/b?"', "# x")
    assert p.parent == tmp_path / "exports" and p.name == "竹取物語 上 2丁表_ _a_b_.md" and p.read_text(encoding="utf-8") == "# x"


def test_markdown_open_route(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import app as m
    opened = []
    monkeypatch.setattr(m, "open_with_default_app", lambda path: opened.append(path))
    st = Store(tmp_path / "data")
    jid = st.create_from_image(Image.new("RGB", (100, 100), "white"), "竹取 p.1", "g", 1, 1, "x.jpg")
    j = st.load(jid); j["annotation"] = ANN; st.save(jid, j)
    c = m.app.test_client()
    r = c.post(f"/job/{jid}/markdown/open", follow_redirects=True)
    assert "Markdown を保存して開きました" in r.get_data(as_text=True)
    assert len(opened) == 1 and opened[0].name == "竹取 p.1.md" and "今は昔" in opened[0].read_text(encoding="utf-8")
    r = c.post("/doc/g/markdown/open", follow_redirects=True)
    assert len(opened) == 2 and opened[1].name == "竹取.md" and "## p.1" in opened[1].read_text(encoding="utf-8")
    r = c.get(f"/job/{jid}/markdown")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
