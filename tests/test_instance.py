import json
import socket
import threading
import time

from kobun import instance


def test_no_instance_file(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_INSTANCE_FILE", str(tmp_path / "i.json"))
    assert instance.running_port() is None
    instance.clear()  # 無くてもエラーにならない


def test_stale_file_is_ignored(tmp_path, monkeypatch):
    f = tmp_path / "i.json"
    monkeypatch.setenv("KOBUN_INSTANCE_FILE", str(f))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); dead = s.getsockname()[1]
    f.write_text(json.dumps({"port": dead, "pid": 1}))
    assert instance.running_port() is None


def test_live_instance_detected(tmp_path, monkeypatch):
    f = tmp_path / "i.json"
    monkeypatch.setenv("KOBUN_INSTANCE_FILE", str(f))
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KOBUN_DATA_DIR", str(tmp_path / "data"))
    import app as m
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    threading.Thread(target=lambda: m.app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False), daemon=True).start()
    for _ in range(50):
        if instance.ping(port):
            break
        time.sleep(0.1)
    assert instance.ping(port)
    instance.write(port)
    assert instance.running_port() == port
    assert instance.wait_running_port(timeout=2) == port
    instance.clear()
    assert not f.exists()
    assert instance.acquire_mutex() is True   # Linux では常に True
