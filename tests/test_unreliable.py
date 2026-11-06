from kobun.ocr_ndl import looks_unreliable


def test_looks_unreliable():
    assert looks_unreliable("一、、、、、、、、、、\n□□□□□\n四\n計\n○○")
    assert looks_unreliable("")
    assert not looks_unreliable("いまはむかしたけとりのおきなといふ\nものありけり野山にましりてたけ\nをとりつゝよろつの事につかひけり")
    assert not looks_unreliable("い路は二にほへとちり\nぬるをわかよたれそつ\nねならむうゐのおく\n132")


def test_direct_upload_and_button(tmp_path, monkeypatch):
    import io
    from PIL import Image
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NDL_LITE_SRC", "/nonexistent")
    import app as m
    c = m.app.test_client()
    buf = io.BytesIO(); Image.new("RGB", (300, 400), "white").save(buf, "JPEG"); buf.seek(0)
    r = c.post("/ocr", data={"image": (buf, "sho.jpg"), "title": "書作品", "direct": "on"}, content_type="multipart/form-data")
    assert r.status_code == 302 and r.headers["Location"].endswith("/direct")   # OCR を飛ばして直読みページへ
    jid = r.headers["Location"].split("/job/")[1].split("/")[0]
    body = c.get(f"/job/{jid}/direct").get_data(as_text=True)
    assert 'name="from_image" value="on"' in body
    assert "OCR がこの資料を読めていない" in c.get(f"/job/{jid}").get_data(as_text=True)   # 空の OCR は崩れ扱い
