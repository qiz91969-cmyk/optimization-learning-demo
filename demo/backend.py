"""把本地Qwen作为消息服务调用；不需要API密钥，不安装第二份PyTorch。"""
import json
import os
import subprocess
from pathlib import Path


class ModelError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def discover_model():
    """本机默认路径可由环境变量或CLI覆盖；不扫描密钥、不触发下载。"""
    candidates = [
        Path("G:/研究生内容/研0/大模型for OR/调研学习8.26-/模型二工具学习项目_9.10验收/.venv/Scripts/python.exe"),
        Path("F:/研0/大模型for OR/调研学习8.26-/模型二工具学习项目_9.10验收/.venv/Scripts/python.exe"),
    ]
    python = os.environ.get("DEMO_MODEL_PYTHON") or next((str(p) for p in candidates if p.is_file()), "")
    model = os.environ.get("DEMO_MODEL_PATH") or str(
        Path.home()/".cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B-Instruct/snapshots/7ae557604adf67be50417f59c2c2f167def9a775")
    return python, model


class LocalQwen:
    def __init__(self, python=None, model_path=None, timeout=90, max_new_tokens=1000):
        default_python, default_model = discover_model()
        self.python = python or default_python
        self.model_path = model_path or default_model
        self.timeout = timeout
        self.max_new_tokens = max_new_tokens

    def generate(self, messages):
        if not Path(self.python).is_file() or not Path(self.model_path, "model.safetensors").is_file():
            raise ModelError("model_unavailable", "Local interpreter/weights missing. Set DEMO_MODEL_PYTHON and DEMO_MODEL_PATH.")
        request = {"messages": messages, "model_path": self.model_path,
                   "max_new_tokens": self.max_new_tokens, "generation_seconds": 45}
        try:
            process = subprocess.run([self.python, "-B", "-u", str(Path(__file__).with_name("model_worker.py"))],
                                     input=json.dumps(request, ensure_ascii=False), text=True, encoding="utf-8",
                                     capture_output=True, timeout=self.timeout,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        except subprocess.TimeoutExpired as exc:
            raise ModelError("model_timeout", f"Local worker exceeded {self.timeout}s and was terminated.") from exc
        if process.returncode:
            raise ModelError("model_error", process.stderr[-3000:])
        try:
            reply = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise ModelError("model_error", "Worker protocol returned invalid JSON.") from exc
        reply["worker_warnings"] = process.stderr[-3000:]
        return reply
