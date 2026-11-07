import numpy as np
from PIL import Image, ImageDraw, ImageOps

from kobun import preprocess
from kobun.store import Store


def _shaded_page(path, angle=0.0):
    # 左右で明るさが違う紙地に、縦の文字列（短い線の列）を描く
    w, h = 1000, 700
    im = Image.new("L", (w, h), 255)
    px = np.asarray(im, dtype=np.float32)
    px -= np.linspace(0, 90, w)[None, :]            # 右へ行くほど暗い影
    im = Image.fromarray(px.astype(np.uint8))
    d = ImageDraw.Draw(im)
    for x in range(100, 950, 60):
        for y in range(80, 650, 28):
            d.rectangle([x, y, x + 18, y + 14], fill=20)
    if angle:
        im = im.rotate(angle, resample=Image.BILINEAR, fillcolor=255)
    im.convert("RGB").save(path, quality=95)
    return path


def test_flatten_removes_shading(tmp_path):
    p = _shaded_page(tmp_path / "s.jpg")
    with Image.open(p) as im:
        gray = ImageOps.grayscale(im)
        before = np.asarray(gray, dtype=np.float32)
        after = np.asarray(preprocess.flatten_background(gray), dtype=np.float32)
    # 紙地（文字の無い帯）の左右差が小さくなる
    band = slice(0, 60)
    assert (before[band, :100].mean() - before[band, -100:].mean()) > 60
    assert abs(after[band, :100].mean() - after[band, -100:].mean()) < 15
    assert after.max() > 240 and after.min() < 40   # コントラストは保たれる


def test_deskew_detects_rotation(tmp_path):
    p = _shaded_page(tmp_path / "r.jpg", angle=2.0)
    with Image.open(p) as im:
        a = preprocess.estimate_skew(ImageOps.grayscale(im))
    assert abs(a - (-2.0)) <= 0.5
    p2 = _shaded_page(tmp_path / "n.jpg", angle=0.0)
    with Image.open(p2) as im:
        assert preprocess.estimate_skew(ImageOps.grayscale(im)) == 0.0


def test_store_enhanced(tmp_path):
    st = Store(tmp_path)
    with Image.open(_shaded_page(tmp_path / "x.jpg")) as im:
        jid = st.create_from_image(im, "t", "g", 1, 1, "x.jpg")
    assert st.source_image(jid).name == "original.jpg"
    info = st.make_enhanced(jid)
    assert "angle" in info and (st.job_dir(jid) / "enhanced.jpg").exists()
    assert st.source_image(jid).name == "enhanced.jpg" and st.load(jid)["enhanced"]
