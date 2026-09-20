"""只检查配置和依赖；不安装、不下载、不修改旧环境。"""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

from demo.backend import discover_model


def main():
    python, model = discover_model()
    packages = {}
    for name in ("numpy", "scipy", "jsonschema", "pytest"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    result = {"demo_python": sys.executable, "packages": packages,
              "model_python": python, "model_path": model,
              "model_weights_exist": Path(model, "model.safetensors").is_file()}
    if Path(python).is_file():
        try:
            probe = subprocess.run([python, "-B", "-c",
                "import json,torch,transformers; print(json.dumps({'torch':torch.__version__,'transformers':transformers.__version__,'cuda':torch.cuda.is_available()}))"],
                capture_output=True, text=True, encoding="utf-8", timeout=45)
            result["model_environment"] = json.loads(probe.stdout) if probe.returncode == 0 else probe.stderr[-2000:]
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            result["model_environment"] = str(exc)
    model_env = result.get("model_environment")
    model_ok = (isinstance(model_env, dict) and bool(model_env.get("torch"))
                and bool(model_env.get("transformers")) and model_env.get("cuda") is True)
    ready = all(packages.values()) and result["model_weights_exist"] and model_ok
    result["status"] = "ready" if ready else "unavailable"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
