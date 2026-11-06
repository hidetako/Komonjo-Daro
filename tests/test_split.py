from kobun.ocr_ndl import OcrLine, OcrResult, merge_segment_results, plan_segments


def test_plan_segments():
    assert plan_segments(1000, 1400) == []                 # 比 1.4 → 分割しない
    segs = plan_segments(3237, 841)                        # 横長写真
    assert len(segs) >= 3 and segs[0][0] == 0 and segs[-1][2] == 3237
    for (x0, y0, x1, y1) in segs:
        assert y0 == 0 and y1 == 841 and x1 - x0 <= int(841 * 1.25) + 1
    for a, b in zip(segs, segs[1:]):                       # 重なりがある
        assert b[0] < a[2]
    tall = plan_segments(800, 3000)
    assert all(s[0] == 0 and s[2] == 800 for s in tall) and tall[-1][3] == 3000


def _res(lines):
    return OcrResult(text="\n".join(l.text for l in lines), lines=lines, width=0, height=0)


def test_merge_dedup_and_order_vertical():
    # 区画A (x 0-1000) と 区画B (x 800-1800)。x=900 付近の行は両方に出る（Bでは左端で切れて細い）
    a = _res([OcrLine(0, "三行目", 0.9, 100, 50, 40, 600), OcrLine(1, "二行目", 0.9, 500, 50, 40, 600), OcrLine(2, "一行目", 0.9, 900, 50, 40, 600)])
    b = _res([OcrLine(0, "一行目(切れ)", 0.8, 100, 50, 20, 600), OcrLine(1, "零行目", 0.9, 700, 50, 40, 600)])
    m = merge_segment_results([((0, 0, 1000, 700), a), ((800, 0, 1800, 700), b)], 1800, 700)
    assert [l.text for l in m.lines] == ["零行目", "一行目", "二行目", "三行目"]   # 右から左
    assert m.text.split("\n")[0] == "零行目" and m.lines[1].x == 900 and m.width == 1800
    assert [l.id for l in m.lines] == [0, 1, 2, 3]


def test_merge_order_horizontal():
    a = _res([OcrLine(0, "下段", 0.9, 50, 400, 600, 40), OcrLine(1, "上段", 0.9, 50, 100, 600, 40)])
    m = merge_segment_results([((0, 0, 700, 500), a)], 700, 500)
    assert [l.text for l in m.lines] == ["上段", "下段"]
