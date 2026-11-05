import json
from types import SimpleNamespace

from PIL import Image

from kobun import llm
from kobun.annotate import OUTPUT_SCHEMA, annotate

SAMPLE = {"honkoku": "いまはむかし", "corrections": [], "gendaigo": "今は昔", "annotations": [], "uncertain": [], "summary": "冒頭", "era_guess": "不明"}


def test_effort_and_reasoning_detection():
    assert llm.openai_effort("low", "gpt-5") == "low" and llm.openai_effort("???", "gpt-6-astra") == "high"
    assert llm.openai_effort("xhigh", "gpt-5.2") == "high" and llm.openai_effort("xhigh", "gpt-5.5") == "xhigh"
    assert llm.openai_effort("max", "gpt-5.5") == "xhigh" and llm.openai_effort("max", "gpt-6.1-sol") == "max"
    assert llm.openai_supports_reasoning("gpt-5.5") and llm.openai_supports_reasoning("gpt-6.1-sol") and llm.openai_supports_reasoning("o3")
    assert not llm.openai_supports_reasoning("gpt-4.1") and not llm.openai_supports_reasoning("gpt-5.2-chat-latest")


def test_filter_openai_models():
    ids = ["gpt-5.5", "gpt-realtime-2", "gpt-image-2", "text-embedding-3-large", "gpt-5.3-codex", "o3", "gpt-4o-transcribe", "gpt-6-luna"]
    assert llm._filter_openai_models(ids) == ["o3", "gpt-6-luna", "gpt-5.5"]


class FakeOpenAI:
    def __init__(self):
        self.responses = self
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(status="completed", output_text=json.dumps(SAMPLE, ensure_ascii=False), model=kwargs["model"],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=20))


def test_openai_call_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    img = tmp_path / "a.jpg"; Image.new("RGB", (100, 150), "white").save(img)
    fake = FakeOpenAI()
    a = annotate("いまはむかし", img, context="竹取", client=fake, provider="openai", model="gpt-5.5", effort="xhigh")
    k = fake.kwargs
    assert k["model"] == "gpt-5.5" and k["reasoning"] == {"effort": "xhigh"}
    assert k["text"]["format"]["type"] == "json_schema" and k["text"]["format"]["strict"] is True and k["text"]["format"]["schema"] == OUTPUT_SCHEMA
    content = k["input"][0]["content"]
    assert content[0]["type"] == "input_image" and content[0]["image_url"].startswith("data:image/jpeg;base64,")
    assert content[1]["type"] == "input_text" and "竹取" in content[1]["text"] and "いまはむかし" in content[1]["text"]
    assert "日本語" in k["instructions"]
    assert a.gendaigo == "今は昔" and a.model == "gpt-5.5" and a.input_tokens == 10


def test_openai_without_reasoning_for_gpt4(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    fake = FakeOpenAI()
    annotate("x", None, client=fake, provider="openai", model="gpt-4.1")
    assert "reasoning" not in fake.kwargs and len(fake.kwargs["input"][0]["content"]) == 1


class FakeAnthropic:
    def __init__(self):
        self.messages = self
        self.kwargs = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        outer = self

        class Ctx:
            def __enter__(self_inner):
                return SimpleNamespace(get_final_message=lambda: SimpleNamespace(
                    stop_reason="end_turn", model=kwargs["model"],
                    content=[SimpleNamespace(type="text", text=json.dumps(SAMPLE, ensure_ascii=False))],
                    usage=SimpleNamespace(input_tokens=5, output_tokens=6)))

            def __exit__(self_inner, *a):
                return False
        return Ctx()


def test_anthropic_call_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    fake = FakeAnthropic()
    a = annotate("x", None, client=fake, provider="anthropic", model="claude-opus-5-5", effort="medium")
    k = fake.kwargs
    assert k["model"] == "claude-opus-5-5" and k["output_config"]["effort"] == "medium"
    assert k["output_config"]["format"]["schema"] == OUTPUT_SCHEMA and k["messages"][0]["content"][0]["type"] == "text"
    assert a.model == "claude-opus-5-5" and a.output_tokens == 6


def test_missing_key_message(tmp_path, monkeypatch):
    monkeypatch.setenv("KOBUN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    try:
        annotate("x", None, provider="openai")
    except RuntimeError as e:
        assert "OpenAI" in str(e) and "設定" in str(e)
    else:
        raise AssertionError("no error")
