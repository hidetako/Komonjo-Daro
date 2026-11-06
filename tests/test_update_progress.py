from kobun import updater


def test_progress_and_start_guard(monkeypatch):
    st = updater.UpdateState()
    assert st.progress()["status"] == "idle" and st.progress()["percent"] == 0
    st._on_progress(50, 200)
    assert st.progress()["percent"] == 25
    # 新版が無ければ開始できない
    try:
        st.start_update()
    except RuntimeError as e:
        assert "新しいバージョン" in str(e)
    else:
        raise AssertionError


def test_start_update_reports_error_on_dev(monkeypatch, tmp_path):
    import time
    st = updater.UpdateState()
    st.latest = updater.ReleaseInfo(version="99.0.0", url="http://127.0.0.1:9/x.exe", notes="", page="")
    st.start_update()
    for _ in range(50):
        if st.dl_status == "error":
            break
        time.sleep(0.05)
    assert st.dl_status == "error" and "インストーラー版" in st.dl_error   # 開発版では実行しない


def test_update_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import app as m
    c = m.app.test_client()
    assert c.get("/update/status").get_json()["status"] == "idle"
    assert c.get("/update/progress").status_code == 200
    r = c.post("/update/apply", follow_redirects=True)
    assert "新しいバージョンはありません" in r.get_data(as_text=True)
