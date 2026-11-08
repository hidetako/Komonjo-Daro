"""LLM プロバイダ抽象層: Anthropic（Claude）と OpenAI（GPT）を同じ呼び出しで使う。

どちらも「システム指示 + 画像（任意）+ テキスト」を渡し、JSON スキーマに従った文字列を返す。
モデル一覧は各社の API から取得できる（設定画面の「一覧を取得」）。CURATED は取得できないときの既定候補。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

PROVIDERS = {
    "anthropic": {"label": "Anthropic（Claude）", "key_prefix": "sk-ant-", "console": "https://console.anthropic.com/settings/keys"},
    "openai": {"label": "OpenAI（GPT）", "key_prefix": "sk-", "console": "https://platform.openai.com/api-keys"},
}

# (model_id, 表示名)。先頭が既定。OpenAI の ID は 2026-11 時点の公開ライフサイクル情報に基づく。
# 実際に使えるモデルは契約により異なるので、設定画面の「一覧を取得」で確認する。
CURATED = {
    "anthropic": [
        ("claude-opus-5-5", "Claude Opus 5.5（推奨）"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5（速い・安い）"),
        ("claude-haiku-5-5", "Claude Haiku 5.5（最安）"),
        ("claude-fable-5-1", "Claude Fable 5.1（最上位・高価）"),
    ],
    "openai": [
        # 説明と価格（$ 入力/出力 per 1M tokens）は developers.openai.com/api/docs/models の 2026-11 時点の記載
        ("gpt-6.1-sol", "GPT-6.1 Sol（推奨。Astra に近い性能で $2/$10）"),
        ("gpt-6-astra", "GPT-6 Astra（最上位 $10/$50）"),
        ("gpt-6.1-terra", "GPT-6.1 Terra（速い・画像に強い $1/$5）"),
        ("gpt-6-luna", "GPT-6 Luna（最安 $0.1/$0.5）"),
        ("gpt-5.5", "GPT-5.5（$5/$30）"),
        ("gpt-5.5-pro", "GPT-5.5 Pro（最も精密・遅い $30/$180）"),
        ("gpt-5.4", "GPT-5.4（$2.5/$15）"),
    ],
}

DEFAULT_MODEL = {"anthropic": "claude-opus-5-5", "openai": "gpt-6.1-sol"}


@dataclass
class LlmResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    sources: list = field(default_factory=list)   # ウェブ検索を使った場合の出典 [{"url","title"}]


# ---------- 共通 ----------
def openai_effort(effort: str, model: str = "") -> str:
    """Anthropic 流の low/medium/high/xhigh/max を OpenAI の reasoning.effort に寄せる。

    GPT-6 系は max まで、GPT-5.5 系は xhigh まで、それ以前は high までを想定。
    """
    m = model.lower()
    if effort in ("low", "medium", "high"):
        return effort
    if effort == "max" and m.startswith("gpt-6"):
        return "max"
    if effort in ("xhigh", "max") and (m.startswith("gpt-6") or m.startswith("gpt-5.5") or m.startswith("gpt-5.4")):
        return "xhigh"
    return "high"


def openai_supports_reasoning(model: str) -> bool:
    m = model.lower()
    if "chat-latest" in m or m.startswith(("gpt-4", "chat")):
        return False
    return m.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


def _filter_openai_models(ids: list[str]) -> list[str]:
    bad = ("realtime", "audio", "transcribe", "tts", "image", "embedding", "moderation", "whisper", "sora", "search", "codex", "oss", "live", "dall-e", "babbage", "davinci", "instruct")
    keep = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4", "chat")) and not any(b in i for b in bad)]
    return sorted(set(keep), reverse=True)


# ---------- モデル一覧 ----------
def list_models(provider: str, api_key: str) -> list[str]:
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        return [m.id for m in client.models.list(limit=100)]
    if provider == "openai":
        import openai
        client = openai.OpenAI(api_key=api_key)
        return _filter_openai_models([m.id for m in client.models.list()])
    raise ValueError(provider)


def test_key(provider: str, api_key: str) -> tuple[bool, str]:
    try:
        n = len(list_models(provider, api_key))
        return True, f"有効なキーです（モデル {n} 件）"
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__
        if "Authentication" in name or "401" in str(e):
            return False, "キーが無効です"
        return False, f"確認できませんでした: {e}"


# ---------- 呼び出し ----------
def call(provider: str, model: str, effort: str, api_key: str, system: str, text: str,
         image: tuple[str, str] | None, schema: dict, client=None) -> LlmResult:
    """image は (base64, media_type)。schema に従う JSON 文字列を返す。"""
    parts: list[tuple] = []
    if image:
        parts.append(("image", image))
    parts.append(("text", text))
    return call_parts(provider, model, effort, api_key, system, parts, schema, client)


def call_parts(provider: str, model: str, effort: str, api_key: str, system: str, parts: list[tuple],
               schema: dict, client=None) -> LlmResult:
    """parts は ("text", str) と ("image", (base64, media_type)) の列。順序どおりに渡す。"""
    if provider == "anthropic":
        return _call_anthropic(model, effort, api_key, system, parts, schema, client)
    if provider == "openai":
        return _call_openai(model, effort, api_key, system, parts, schema, client)
    raise ValueError(f"未対応のプロバイダ: {provider}")


def _call_anthropic(model, effort, api_key, system, parts, schema, client=None) -> LlmResult:
    import anthropic

    client = client or (anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic())
    content = []
    for kind, v in parts:
        if kind == "image":
            content.append({"type": "image", "source": {"type": "base64", "media_type": v[1], "data": v[0]}})
        else:
            content.append({"type": "text", "text": v})
    with client.messages.stream(
        model=model,
        max_tokens=32000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    ) as stream:
        r = stream.get_final_message()
    if r.stop_reason == "refusal":
        d = getattr(r, "stop_details", None)
        raise RuntimeError(f"モデルが応答を拒否しました: {getattr(d, 'explanation', '')}")
    if r.stop_reason == "max_tokens":
        raise RuntimeError("出力が長すぎて途中で切れました。ページを分割して再実行してください。")
    out = next(b.text for b in r.content if b.type == "text")
    return LlmResult(out, r.model, r.usage.input_tokens, r.usage.output_tokens)


def _call_openai(model, effort, api_key, system, parts, schema, client=None) -> LlmResult:
    import openai

    client = client or openai.OpenAI(api_key=api_key)
    content = []
    for kind, v in parts:
        if kind == "image":
            content.append({"type": "input_image", "image_url": f"data:{v[1]};base64,{v[0]}", "detail": "high"})
        else:
            content.append({"type": "input_text", "text": v})
    kwargs = dict(
        model=model,
        instructions=system,
        input=[{"role": "user", "content": content}],
        text={"format": {"type": "json_schema", "name": "kobun_annotation", "schema": schema, "strict": True}},
        max_output_tokens=32000,
    )
    if openai_supports_reasoning(model):
        kwargs["reasoning"] = {"effort": openai_effort(effort, model)}
    r = client.responses.create(**kwargs)
    if getattr(r, "status", "completed") == "incomplete":
        reason = getattr(getattr(r, "incomplete_details", None), "reason", "")
        raise RuntimeError(f"出力が完了しませんでした（{reason}）。ページを分割して再実行してください。")
    out = r.output_text
    if not out:
        raise RuntimeError("モデルから本文が返りませんでした（拒否または空応答）。")
    usage = getattr(r, "usage", None)
    return LlmResult(out, getattr(r, "model", model), getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)


def search_text(provider: str, model: str, effort: str, api_key: str, system: str, text: str,
                client=None, max_uses: int = 8) -> LlmResult:
    """ウェブ検索ツール付きの自由文呼び出し（構造化出力なし）。候補の調査など、検索結果を文章で返させる用途。

    Anthropic は web_search と web_fetch（検索で見つけたページの全文を読む）、OpenAI は Responses API の
    web_search（search_context_size=high）。検索は 1 回あたり課金される。
    """
    if provider == "anthropic":
        return _search_anthropic(model, effort, api_key, system, text, client, max_uses)
    if provider == "openai":
        return _search_openai(model, effort, api_key, system, text, client)
    raise ValueError(f"未対応のプロバイダ: {provider}")


def _search_anthropic(model, effort, api_key, system, text, client=None, max_uses=8) -> LlmResult:
    import anthropic

    client = client or (anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic())
    messages = [{"role": "user", "content": [{"type": "text", "text": text}]}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses},
             {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 4, "max_content_tokens": 60000}]
    tin = tout = 0
    for _ in range(4):   # pause_turn で中断されたら、応答をそのまま返して続きを頼む
        with client.messages.stream(model=model, max_tokens=16000, system=system, messages=messages, tools=tools,
                                    output_config={"effort": effort}) as stream:
            r = stream.get_final_message()
        tin += r.usage.input_tokens
        tout += r.usage.output_tokens
        if r.stop_reason == "refusal":
            d = getattr(r, "stop_details", None)
            raise RuntimeError(f"モデルが応答を拒否しました: {getattr(d, 'explanation', '')}")
        if r.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": r.content})
            continue
        break
    texts, sources, seen = [], [], set()
    for b in r.content:
        if b.type == "text":
            texts.append(b.text)
        elif b.type == "web_search_tool_result" and isinstance(b.content, list):
            for res in b.content:
                url = getattr(res, "url", "")
                if url and url not in seen:
                    seen.add(url)
                    sources.append({"url": url, "title": getattr(res, "title", "") or ""})
    return LlmResult("".join(texts).strip(), r.model, tin, tout, sources)


def _search_openai(model, effort, api_key, system, text, client=None) -> LlmResult:
    import openai

    client = client or openai.OpenAI(api_key=api_key)
    kwargs = dict(model=model, instructions=system, input=[{"role": "user", "content": [{"type": "input_text", "text": text}]}],
                  tools=[{"type": "web_search", "search_context_size": "high"}], max_output_tokens=16000)
    if openai_supports_reasoning(model):
        kwargs["reasoning"] = {"effort": openai_effort(effort, model)}
    r = client.responses.create(**kwargs)
    sources, seen = [], set()
    for item in getattr(r, "output", None) or []:
        for c in getattr(item, "content", None) or []:
            for a in getattr(c, "annotations", None) or []:
                url = getattr(a, "url", "")
                if getattr(a, "type", "") == "url_citation" and url and url not in seen:
                    seen.add(url)
                    sources.append({"url": url, "title": getattr(a, "title", "") or ""})
    usage = getattr(r, "usage", None)
    return LlmResult((r.output_text or "").strip(), getattr(r, "model", model), getattr(usage, "input_tokens", 0) or 0,
                     getattr(usage, "output_tokens", 0) or 0, sources)


def parse_json(text: str) -> dict:
    return json.loads(text)
