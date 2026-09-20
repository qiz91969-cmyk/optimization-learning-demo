"""明确标为人工注入的失败/修复演示，与Qwen实测成绩完全分开。"""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import sys

from demo.harness import run_online
from demo.validation import build_call, validate_call, ValidationError

ROOT = Path(__file__).resolve().parent


class SyntheticBackend:
    def __init__(self, values):
        self.values = iter(values)

    def generate(self, messages):
        return {"raw_text": next(self.values), "model": "SYNTHETIC_TEST_FIXTURE_NOT_QWEN"}


def main():
    os.chdir(ROOT)
    public = json.loads((ROOT/"data/inputs/printers.json").read_text(encoding="utf-8"))
    correct = json.loads((ROOT/"data/problems/printers.json").read_text(encoding="utf-8"))
    missing = deepcopy(correct); del missing["objective"]
    dimension = deepcopy(correct); dimension["parameters"]["constraints"][0]["coefficients"] = [1]
    records = []
    for name, bad in (("missing_field", missing), ("wrong_dimensions", dimension)):
        fixture = SyntheticBackend([json.dumps(bad), json.dumps(correct)])
        record = run_online(public, "nl", backend=fixture)
        record["record_type"] = "synthetic_fault_injection"
        record["test_name"] = name
        record["warning"] = "The repaired output is a fixture, NOT a real LLM response or evidence of model improvement."
        records.append(record)
    call = build_call(correct); call["tool_name"] = "execute_python"
    try:
        validate_call(call)
    except ValidationError as exc:
        records.append({"record_type":"synthetic_fault_injection", "test_name":"illegal_tool", "injected_call":call, "blocked":True,"feedback":str(exc)})
    folder = ROOT/"outputs"/("faults_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
    folder.mkdir(parents=True)
    (folder/"faults.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
    (folder/"README.md").write_text("# 人工故障测试\n\n此目录不是Qwen成绩。缺字段与维度错误被阻止后，测试夹具返回合法记录；非法工具在调用前被阻止。完整输入/错误/修复见faults.json。\n",encoding="utf-8")
    print(folder)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
