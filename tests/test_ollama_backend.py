"""Offline adapter tests. These tests never contact the shared server."""
import json
from urllib.error import HTTPError, URLError

import pytest

from demo.backend import ModelError
from demo.ollama_backend import OllamaModel


class Response:
    def __init__(self, value):
        self.body = json.dumps(value).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, *args):
        return self.body


class Opener:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.requests = reply, error, []
    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return Response(self.reply)


def prepared_model(reply):
    model = OllamaModel()
    model.metadata = {"model": model.model, "backend": "ollama", "options": {"temperature": 0, "num_predict": 1400}}
    model.opener = Opener(reply)
    return model


def test_chat_contract_and_no_forced_schema_or_lifetime():
    model = prepared_model({"model": "qwen2.5:14b", "done": True,
                            "message": {"role": "assistant", "content": '{"a": 1}'}, "eval_count": 8})
    messages = [{"role": "user", "content": "public question"}]
    reply = model.generate(messages)
    request = model.opener.requests[0][0]
    body = json.loads(request.data)
    assert request.full_url == "http://127.0.0.1:11435/api/chat"
    assert body["messages"] == messages and body["stream"] is False
    assert "format" not in body and "keep_alive" not in body and "num_ctx" not in body["options"]
    assert reply["raw_text"] == '{"a": 1}' and reply["generated_tokens"] == 8


@pytest.mark.parametrize("reply", [{}, {"error": "bad"}, {"done": False},
    {"model": "other", "done": True, "message": {"role": "assistant", "content": "x"}},
    {"model": "qwen2.5:14b", "done": True, "message": {"role": "assistant", "content": None}}])
def test_invalid_protocol(reply):
    with pytest.raises(ModelError):
        prepared_model(reply).generate([])


@pytest.mark.parametrize("url", ["file:///tmp/x", "http://user:secret@localhost", "http://localhost/v1", "http://localhost?token=x"])
def test_bad_urls(url):
    with pytest.raises(ValueError):
        OllamaModel(url)


@pytest.mark.parametrize("error,status", [(TimeoutError(), "model_timeout"),
    (URLError("refused"), "model_unavailable"),
    (HTTPError("http://localhost", 401, "auth", {}, None), "model_http_error")])
def test_failures_not_automatically_retried(error, status):
    model = prepared_model({})
    model.opener = Opener(error=error)
    with pytest.raises(ModelError) as exc:
        model.generate([])
    assert exc.value.status == status and len(model.opener.requests) == 1


def test_probe_only_metadata_and_missing_model_no_download(monkeypatch):
    model = OllamaModel()
    routes = []
    def request(route, payload=None, timeout=None):
        routes.append(route)
        return {"version": "test"} if route == "/api/version" else {"models": []}
    monkeypatch.setattr(model, "_request", request)
    with pytest.raises(ModelError):
        model.probe()
    assert routes == ["/api/version", "/api/tags"]


def test_cloud_tag_not_allowed():
    with pytest.raises(ValueError):
        OllamaModel(model="example:cloud")
