import io

import pytest
from PIL import Image


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import app as m
    m.app.config["TESTING"] = True
    return m.app.test_client()


def test_pages_render(client):
    assert client.get("/").status_code == 200
    assert "API キーが未設定" in client.get("/").get_data(as_text=True)
    assert client.get("/jobs").status_code == 200
    r = client.get("/settings")
    assert r.status_code == 200 and "保存フォルダ" in r.get_data(as_text=True)
    assert client.get("/job/000000000000").status_code == 404
    assert client.get("/media/000000000000/thumb.jpg").status_code == 404


def test_settings_save_and_move(client, tmp_path):
    r = client.post("/settings", data={"api_key": "sk-ant-test-1234567890", "model": "claude-opus-5-5", "effort": "medium",
                                       "device": "cpu", "send_image": "on", "data_dir": str(tmp_path / "newdata"), "move_data": "on"},
                    follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "保存しました" in body and "sk-ant-" in body and "1234567890" not in body  # マスク表示
    assert (tmp_path / "newdata" / "jobs").exists()
    # キーを空で再保存しても消えない
    client.post("/settings", data={"api_key": "", "model": "claude-opus-5-5", "effort": "medium", "device": "cpu", "data_dir": str(tmp_path / "newdata")})
    from kobun import config as c
    assert c.load()["api_key"] == "sk-ant-test-1234567890"


def test_ocr_upload_without_ndl_shows_error(client, monkeypatch):
    monkeypatch.setenv("NDL_LITE_SRC", "/nonexistent")
    buf = io.BytesIO(); Image.new("RGB", (300, 400), "white").save(buf, "JPEG"); buf.seek(0)
    r = client.post("/ocr", data={"image": (buf, "test.jpg"), "title": "t"}, content_type="multipart/form-data")
    assert r.status_code == 500 and "NDL古典籍OCR-Lite が見つかりません" in r.get_data(as_text=True)
