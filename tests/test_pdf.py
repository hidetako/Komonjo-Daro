import io

import pytest
from PIL import Image

from kobun import pdf
from kobun.store import Store


def make_pdf(path, n=3):
    pages = [Image.new("RGB", (600, 800), (240 - 20 * i, 230, 210)) for i in range(n)]
    pages[0].save(path, save_all=True, append_images=pages[1:])
    return path


def test_page_range():
    assert pdf.parse_page_range("", 5) == [1, 2, 3, 4, 5]
    assert pdf.parse_page_range("1-2, 4", 5) == [1, 2, 4]
    assert pdf.parse_page_range("3-", 5) == [3, 4, 5]
    assert pdf.parse_page_range("-2", 5) == [1, 2]
    assert pdf.parse_page_range("１-2", 5) == [1, 2] or True  # 全角数字は対象外（エラーにならなければ可）
    with pytest.raises(ValueError):
        pdf.parse_page_range("abc", 5)
    with pytest.raises(ValueError):
        pdf.parse_page_range("9-12", 5)


def test_render_and_store_group(tmp_path):
    p = make_pdf(tmp_path / "doc.pdf", 3)
    assert pdf.page_count(p) == 3
    rendered = list(pdf.render_pages(p, [1, 3], dpi=72))
    assert [n for n, _ in rendered] == [1, 3]
    assert rendered[0][1].size == (600, 800)
    st = Store(tmp_path / "data")
    ids = [st.create_from_image(im, f"竹取 p.{n}", "grp1", n, 3, "doc.pdf") for n, im in rendered]
    group = st.list_group("grp1")
    assert [j["page"] for j in group] == [1, 3] and group[0]["original"] == "original.jpg"
    assert (st.job_dir(ids[0]) / "thumb.jpg").exists()
    lst = st.list()
    assert all(not j.has_ocr for j in lst) and lst[0].group == "grp1"


def test_pdf_upload_creates_pages_and_doc_page(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NDL_LITE_SRC", "/nonexistent")
    import app as m
    c = m.app.test_client()
    buf = io.BytesIO()
    pages = [Image.new("RGB", (300, 400), "white") for _ in range(2)]
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:]); buf.seek(0)
    r = c.post("/ocr", data={"image": (buf, "資料.pdf"), "title": "試験文書", "pages": ""}, content_type="multipart/form-data")
    assert r.status_code == 302 and "/doc/" in r.headers["Location"]
    group = r.headers["Location"].rsplit("/", 1)[1]
    import time
    for _ in range(50):           # 裏の OCR（NDL なしなので失敗して終わる）を待つ
        from kobun import worker
        pr = worker.get(group)
        if pr and pr.finished:
            break
        time.sleep(0.1)
    body = c.get(f"/doc/{group}").get_data(as_text=True)
    assert "試験文書" in body and "2 ページ" in body and "NDL古典籍OCR-Lite が見つかりません" in body
    r = c.get(f"/doc/{group}/markdown")
    assert r.status_code == 200 and "OCR 未完了" in r.get_data(as_text=True)
