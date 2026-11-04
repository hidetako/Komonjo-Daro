import json

from PIL import Image

from kobun import config as cfgmod
from kobun.store import Store
from kobun.updater import is_newer, parse_version


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = cfgmod.load()
    assert c["api_key"] == "" and c["data_dir"].endswith("data")
    c["api_key"] = "sk-ant-abcdefghijklmnop"
    c["effort"] = "medium"
    cfgmod.save(c)
    c2 = cfgmod.load()
    assert c2["api_key"] == "sk-ant-abcdefghijklmnop" and c2["effort"] == "medium"
    assert cfgmod.mask_key(c2["api_key"]).startswith("sk-ant-") and "…" in cfgmod.mask_key(c2["api_key"])
    assert json.loads(cfgmod.config_path().read_text(encoding="utf-8"))["model"] == "claude-opus-5-5"


def _img(path, size=(1200, 1600)):
    Image.new("RGB", size, "white").save(path)
    return path


def test_store_create_search_move(tmp_path):
    st = Store(tmp_path / "d1")
    up = _img(tmp_path / "up.tif")
    jid = st.create(up, "竹取物語_上.tif", title="竹取物語 上", context="江戸前期")
    assert not up.exists()  # 原本は移動される
    d = st.job_dir(jid)
    assert (d / "original.tif").exists() and (d / "preview.jpg").exists() and (d / "thumb.jpg").exists()
    with Image.open(d / "thumb.jpg") as th:
        assert max(th.size) <= 320
    job = st.load(jid)
    job["ocr"] = {"text": "いまはむかし", "lines": [], "width": 1200, "height": 1600, "viz_path": None}
    job["annotation"] = {"honkoku": "いまはむかし", "corrections": [], "gendaigo": "今は昔", "annotations": [{"term": "翁", "note": "老人"}],
                         "uncertain": [], "summary": "冒頭", "era_guess": "不明", "model": "m", "input_tokens": 1, "output_tokens": 1}
    st.save(jid, job)
    up2 = _img(tmp_path / "up2.jpg")
    jid2 = st.create(up2, "別の資料.jpg")
    assert len(st.list()) == 2
    assert [j.id for j in st.list("今は昔")] == [jid]
    assert [j.id for j in st.list("翁 江戸")] == [jid]          # AND 検索（注釈・補足も対象）
    assert [j.id for j in st.list(only_annotated=True)] == [jid]
    assert st.list("別の")[0].title == "別の資料"
    assert st.list("存在しない") == []
    moved = st.move_to(tmp_path / "d2")
    assert moved == 2 and (tmp_path / "d2" / "jobs" / jid / "job.json").exists()
    assert len(st.list()) == 2
    st.delete(jid2)
    assert len(st.list()) == 1


def test_version_compare():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert is_newer("0.3.0", "0.2.0") and not is_newer("0.2.0", "0.2.0") and not is_newer("0.1.9", "0.2.0")
