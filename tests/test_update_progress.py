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


def test_open_retries_on_5xx_only(monkeypatch):
    import io
    import urllib.error
    import urllib.request
    from kobun import updater

    monkeypatch.setattr(updater, "RETRY_WAITS", (0.0, 0.0))
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def flaky(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 504, "Gateway Time-out", {}, io.BytesIO(b""))
        return io.BytesIO(b"ok")

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    req = urllib.request.Request("https://example.org/x")
    assert updater._open(req, 1).read() == b"ok" and calls["n"] == 3

    # 4xx は再試行しない
    calls["n"] = 0

    def notfound(req, timeout=0):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", notfound)
    import pytest
    with pytest.raises(urllib.error.HTTPError):
        updater._open(req, 1)
    assert calls["n"] == 1

    # 5xx が続けば 3 回で諦める
    calls["n"] = 0

    def always(req, timeout=0):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", always)
    with pytest.raises(urllib.error.HTTPError):
        updater._open(req, 1)
    assert calls["n"] == 3


def test_open_asset_falls_back_to_api_on_5xx(monkeypatch):
    import io
    import urllib.error
    import urllib.request
    from kobun import updater

    monkeypatch.setattr(updater, "RETRY_WAITS", (0.0,))
    monkeypatch.setattr("time.sleep", lambda s: None)
    seen = []

    def fake(req, timeout=0):
        seen.append((req.full_url, req.get_header("Accept")))
        if "github.com/x/releases/download" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 504, "Gateway Time-out", {}, io.BytesIO(b""))
        return io.BytesIO(b"exe")

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    info = updater.ReleaseInfo(version="1", url="https://github.com/x/releases/download/v1/a.exe", notes="", page="",
                               api_url="https://api.github.com/repos/x/releases/assets/1")
    assert updater.open_asset(info, 1).read() == b"exe"
    assert [u for u, _ in seen] == [info.url, info.url, info.api_url] and seen[-1][1] == "application/octet-stream"
    # 代替経路が無ければそのまま失敗
    import pytest
    with pytest.raises(urllib.error.HTTPError):
        updater.open_asset(updater.ReleaseInfo(version="1", url=info.url, notes="", page=""), 1)


def test_fetch_latest_keeps_api_url(monkeypatch):
    import io, json
    import urllib.request
    from kobun import updater

    data = {"tag_name": "v9.9.9", "body": "n", "html_url": "p",
            "assets": [{"name": "Komonjo-Daro-Setup.exe", "browser_download_url": "https://github.com/d", "url": "https://api.github.com/a"}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: io.BytesIO(json.dumps(data).encode()))
    info = updater.fetch_latest()
    assert info.version == "9.9.9" and info.url == "https://github.com/d" and info.api_url == "https://api.github.com/a"
