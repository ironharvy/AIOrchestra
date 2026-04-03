"""Tests for the Ollama local LLM provider."""

import json

from aiorchestra.ai import OllamaProvider, create_provider


class FakeResponse:
    """Minimal fake HTTP response that supports the context manager protocol."""

    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _make_provider(**overrides):
    config = {"provider": "ollama", **overrides}
    return OllamaProvider(config)


def test_invoke_ollama_success(monkeypatch):
    """Successful generation returns response text."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        captured["timeout"] = timeout
        return FakeResponse(json.dumps({"response": "summary result"}).encode())

    monkeypatch.setattr("aiorchestra.ai._ollama.urllib.request.urlopen", fake_urlopen)

    provider = _make_provider(model="phi3", endpoint="http://host:11434")
    result = provider.run("test prompt")

    assert result.success
    assert result.output == "summary result"
    assert captured["body"]["model"] == "phi3"
    assert captured["body"]["prompt"] == "test prompt"
    assert captured["body"]["stream"] is False


def test_invoke_ollama_with_system_prompt(monkeypatch):
    """System prompt is forwarded in the payload."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return FakeResponse(json.dumps({"response": "ok"}).encode())

    monkeypatch.setattr("aiorchestra.ai._ollama.urllib.request.urlopen", fake_urlopen)

    provider = _make_provider()
    provider.run("prompt", system="You are an analyst")
    assert captured["body"]["system"] == "You are an analyst"


def test_invoke_ollama_network_error(monkeypatch):
    """Network failure returns failure result."""
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("aiorchestra.ai._ollama.urllib.request.urlopen", fake_urlopen)

    provider = _make_provider()
    result = provider.run("test")
    assert not result.success


def test_invoke_ollama_empty_response(monkeypatch):
    """Empty model response returns failure."""

    def fake_urlopen(req, timeout=None):
        return FakeResponse(json.dumps({"response": ""}).encode())

    monkeypatch.setattr("aiorchestra.ai._ollama.urllib.request.urlopen", fake_urlopen)

    provider = _make_provider()
    result = provider.run("test")
    assert not result.success


def test_invoke_ollama_timeout(monkeypatch):
    """Timeout returns failure."""

    def fake_urlopen(req, timeout=None):
        raise TimeoutError()

    monkeypatch.setattr("aiorchestra.ai._ollama.urllib.request.urlopen", fake_urlopen)

    provider = _make_provider(timeout=5)
    result = provider.run("test")
    assert not result.success


def test_ollama_available_success(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return FakeResponse(b"{}", status=200)

    monkeypatch.setattr("aiorchestra.ai._ollama.urllib.request.urlopen", fake_urlopen)
    assert _make_provider().available() is True


def test_ollama_available_failure(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise ConnectionError()

    monkeypatch.setattr("aiorchestra.ai._ollama.urllib.request.urlopen", fake_urlopen)
    assert _make_provider().available() is False


def test_create_provider_ollama():
    """Factory creates OllamaProvider for provider='ollama'."""
    provider = create_provider({"provider": "ollama"})
    assert isinstance(provider, OllamaProvider)
