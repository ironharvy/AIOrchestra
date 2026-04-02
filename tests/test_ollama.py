"""Tests for the Ollama local LLM provider."""

import json

from aiorchestra.ai.ollama import invoke_ollama, ollama_available


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


def test_invoke_ollama_success(monkeypatch):
    """Successful generation returns response text."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        captured["timeout"] = timeout
        return FakeResponse(json.dumps({"response": "summary result"}).encode())

    monkeypatch.setattr("aiorchestra.ai.provider.urllib.request.urlopen", fake_urlopen)

    result = invoke_ollama("test prompt", {"model": "phi3", "endpoint": "http://host:11434"})

    assert result == "summary result"
    assert captured["body"]["model"] == "phi3"
    assert captured["body"]["prompt"] == "test prompt"
    assert captured["body"]["stream"] is False


def test_invoke_ollama_with_system_prompt(monkeypatch):
    """System prompt is forwarded in the payload."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return FakeResponse(json.dumps({"response": "ok"}).encode())

    monkeypatch.setattr("aiorchestra.ai.provider.urllib.request.urlopen", fake_urlopen)

    invoke_ollama("prompt", {}, system="You are an analyst")
    assert captured["body"]["system"] == "You are an analyst"


def test_invoke_ollama_network_error(monkeypatch):
    """Network failure returns None gracefully."""
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("aiorchestra.ai.provider.urllib.request.urlopen", fake_urlopen)

    result = invoke_ollama("test", {})
    assert result is None


def test_invoke_ollama_empty_response(monkeypatch):
    """Empty model response returns None."""

    def fake_urlopen(req, timeout=None):
        return FakeResponse(json.dumps({"response": ""}).encode())

    monkeypatch.setattr("aiorchestra.ai.provider.urllib.request.urlopen", fake_urlopen)

    result = invoke_ollama("test", {})
    assert result is None


def test_invoke_ollama_timeout(monkeypatch):
    """Timeout returns None."""

    def fake_urlopen(req, timeout=None):
        raise TimeoutError()

    monkeypatch.setattr("aiorchestra.ai.provider.urllib.request.urlopen", fake_urlopen)

    result = invoke_ollama("test", {"timeout": 5})
    assert result is None


def test_ollama_available_success(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return FakeResponse(b"{}", status=200)

    monkeypatch.setattr("aiorchestra.ai.provider.urllib.request.urlopen", fake_urlopen)
    assert ollama_available({}) is True


def test_ollama_available_failure(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise ConnectionError()

    monkeypatch.setattr("aiorchestra.ai.provider.urllib.request.urlopen", fake_urlopen)
    assert ollama_available({}) is False
