"""Ollama adapter: existing service only; no downloads, reload commands or code execution."""
import json
import os
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from .backend import ModelError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OllamaModel:
    def __init__(self, base_url=None, model="qwen2.5:14b", timeout=300, max_new_tokens=1400):
        self.base_url = (base_url or os.environ.get("DEMO_OLLAMA_URL", "http://127.0.0.1:11435")).rstrip("/")
        parsed = urlsplit(self.base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or
                parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("Use a plain Ollama server URL, without credentials or /v1 path")
        if timeout <= 0 or type(max_new_tokens) is not int or max_new_tokens <= 0:
            raise ValueError("Timeout and token limit must be positive")
        if not isinstance(model, str) or not model or model.endswith(":cloud"):
            raise ValueError("Use an explicitly installed server model, not a cloud tag")
        self.model, self.timeout, self.max_new_tokens = model, timeout, max_new_tokens
        # Do not send the private SSH-forwarded request through system HTTP proxies.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.metadata = None

    def _request(self, route, payload=None, timeout=None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = Request(self.base_url + route, data=body, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout or self.timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise ModelError("model_http_error", f"Ollama returned HTTP {exc.code}; check model/access/service. No automatic retry.") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ModelError("model_timeout", "Ollama request timed out; server-side cancellation is not guaranteed. Do not immediately repeat a batch.") from exc
        except URLError as exc:
            raise ModelError("model_unavailable", "Cannot reach Ollama. Keep the SSH tunnel open and check the configured URL.") from exc
        except (ValueError, UnicodeError) as exc:
            raise ModelError("model_protocol_error", "Ollama did not return a valid JSON response") from exc
        if not isinstance(result, dict) or result.get("error"):
            raise ModelError("model_protocol_error", "Ollama returned an error or invalid response object")
        return result

    def probe(self):
        version = self._request("/api/version", timeout=10)
        tags = self._request("/api/tags", timeout=10)
        models = tags.get("models", [])
        if not isinstance(models, list):
            raise ModelError("model_protocol_error", "Invalid model inventory")
        selected = next((m for m in models if isinstance(m, dict) and m.get("name") == self.model), None)
        if selected is None:
            raise ModelError("model_unavailable", "Exact model tag is not installed. No model will be downloaded.")
        running = self._request("/api/ps", timeout=10).get("models", [])
        loaded = next((m for m in running if m.get("name") == self.model), None)
        self.metadata = {"backend": "ollama", "model": self.model, "base_url": self.base_url,
                         "ollama_version": version.get("version"), "model_digest": selected.get("digest"),
                         "details": selected.get("details"), "loaded_at_probe": loaded is not None,
                         "loaded_context_length": loaded.get("context_length") if loaded else None,
                         "output_mode": "plain_text_no_schema_constraint",
                         "options": {"temperature": 0, "num_predict": self.max_new_tokens},
                         "timeout_seconds": self.timeout,
                         "context_policy": "server defaults; num_ctx and keep_alive not overridden"}
        return self.metadata

    def generate(self, messages):
        if self.metadata is None:
            self.probe()
        start = time.perf_counter()
        request = {"model": self.model, "messages": messages, "stream": False,
                   "options": self.metadata["options"]}
        reply = self._request("/api/chat", request)
        message = reply.get("message")
        if (reply.get("done") is not True or not isinstance(message, dict) or
                message.get("role") != "assistant" or not isinstance(message.get("content"), str) or
                reply.get("model") != self.model):
            raise ModelError("model_protocol_error", "Incomplete chat response or unexpected model/message")
        return {"raw_text": message["content"], **self.metadata,
                "elapsed_request_seconds": round(time.perf_counter()-start, 3),
                "done_reason": reply.get("done_reason"),
                "generated_tokens": reply.get("eval_count"), "prompt_tokens": reply.get("prompt_eval_count"),
                "total_duration_ns": reply.get("total_duration"), "load_duration_ns": reply.get("load_duration"),
                "eval_duration_ns": reply.get("eval_duration"),
                "returned_thinking": message.get("thinking"),
                "returned_tool_calls": message.get("tool_calls")}
