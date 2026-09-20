"""统一入口：运行两类输入、保存真实轨迹、最后独立评分并生成中文摘要。

用法示例：.venv/Scripts/python.exe run_demo.py --entry both --case printers
退出码0表示已生成报告，不表示模型全部答对；--require-success开启严格验收。
"""
import argparse
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys

from demo.backend import LocalQwen
from demo.evaluation import evaluate_record
from demo.harness import run_online

ROOT = Path(__file__).resolve().parent
CASES = ("printers", "bakery", "advertising", "assignment", "transportation")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def write_summary(folder, records, environment):
    """让初学者先看表格，再按路径看JSON；不把失败藏在平均数里。"""
    lines = ["# 本次运行结果", "", f"运行时间：{environment['started_at']}。这是开发演示，不是未见测试成绩。",
             "", "原生JSON、清理代码框后的JSON、结构合规、程序跑完、答案正确是不同事情。",
             "", "|题目|入口|尝试次数|原生JSON|清理后JSON|最终Schema|在线状态|首轮核验|最终核验|最终工具状态|",
             "|---|---|---:|---|---|---|---|---|---|---|"]
    for r in records:
        a = r["attempts"][-1]
        e = r["evaluation"]
        fmt = lambda x: "不适用" if x is None else ("是" if x else "否")
        lines.append(f"|{r['sample_id']}|{r['mode']}|{len(r['attempts'])}|{fmt(a['raw_json_valid'])}|"
                     f"{fmt(a['normalized_json_valid'])}|{fmt(a['schema_valid'])}|{r['online_status']}|"
                     f"{fmt(e['first_pass_verified'])}|{fmt(e['final_verified'])}|{a.get('solver_result',{}).get('status','未执行')}|")
    lines += ["", "## 怎样读", "", "- json：输入来自已整理的问题文件，没有证明模型读懂自然语言。",
              "- nl：真实本地Qwen输出；没有把参考答案作为输出的后备方案。",
              "- 当前nl采用公开关键词选择一种模板，并给定实体名称；不是自主类别识别或算法选择成绩。",
              "- 首轮和最终对比来自同一轨迹；首轮后只有接口不合规才重试，隐藏答案不会反馈。",
              "- 最终核验要求参考问题对齐、单位标签一致、状态正确；有解时还检查原题约束及目标值。",
              "- infeasible不等于程序失败；广告题正确结果就是无解。",
              "- 同时保留原始模型输出与清理标记，代码框清理不算模型自我修复。",
              "- 所有human_review仍是pending，自动核验不是教师/同学人工认可。", ""]
    for r in records:
        lines += [f"## {r['sample_id']} / {r['mode']}", "",
                  f"详细轨迹：`{r['sample_id']}_{r['mode']}.json`，耗时 {r['elapsed_seconds']} 秒。"]
        for a, e in zip(r["attempts"], r["evaluation"]["attempt_evaluations"]):
            lines.append(f"- 第{a['attempt']+1}次：反馈={a.get('feedback') or '无接口错误'}；参考对齐={e.get('reference_alignment')}；独立核验={e['verified_against_reference']}。")
        if "problem" in r["attempts"][-1]:
            lines += ["", "最后一次结构化问题：", "```json", json.dumps(r["attempts"][-1]["problem"], ensure_ascii=False, indent=2), "```"]
        lines.append("")
    (folder/"SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    write_json(folder/"index.json", {"environment": environment, "results": [
        {"sample_id": r["sample_id"], "mode": r["mode"], "online_status": r["online_status"],
         "first_pass_verified": r["evaluation"]["first_pass_verified"],
         "final_verified": r["evaluation"]["final_verified"], "attempts": len(r["attempts"])} for r in records]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", choices=("json", "nl", "both"), default="json")
    parser.add_argument("--case", choices=(*CASES, "all"), default="all")
    parser.add_argument("--retries", type=int, choices=(0, 1, 2), default=2)
    parser.add_argument("--model-python")
    parser.add_argument("--model-path")
    parser.add_argument("--require-success", action="store_true", help="Return 1 if any selected case is not verified")
    args = parser.parse_args()
    # 所有相对路径相对于项目，不依赖VS Code终端最初打开在哪个目录。
    os.chdir(ROOT)
    sys.stdout.reconfigure(encoding="utf-8")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    folder = ROOT/"outputs"/run_id
    folder.mkdir(parents=True, exist_ok=False)
    environment = {"started_at": datetime.now().astimezone().isoformat(), "python": sys.version,
                   "platform": platform.platform(), "entry": args.entry, "retries": args.retries}
    environment["packages"] = {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "jsonschema", "pytest")}
    backend = LocalQwen(args.model_python, args.model_path)
    cases = CASES if args.case == "all" else (args.case,)
    modes = ("json", "nl") if args.entry == "both" else (args.entry,)
    records = []
    for case in cases:
        public = load(ROOT/"data"/"inputs"/f"{case}.json")
        for mode in modes:
            print(f"Running {case} [{mode}] ...", flush=True)
            # 自然语言入口不接收problem；结构化入口显式读取其问题文件。
            supplied = load(ROOT/"data"/"problems"/f"{case}.json") if mode == "json" else None
            record = run_online(public, mode, supplied, backend=backend, retries=args.retries)
            record["input_sha256"] = digest(public)
            record["public_input"] = public
            write_json(folder/f"{case}_{mode}_online.json", record)
            # 在线环路已结束，才读取参考资料，不会用于纠错。
            reference = load(ROOT/"data"/"problems"/f"{case}.json")
            answer = load(ROOT/"data"/"references"/"answers.json")[case]
            record["reference_sha256"] = digest({"problem": reference, "answer": answer})
            record["evaluation"] = evaluate_record(record, reference, answer)
            write_json(folder/f"{case}_{mode}.json", record)
            records.append(record)
            write_summary(folder, records, environment)
            print(f"  online={record['online_status']} verified={record['evaluation']['final_verified']}", flush=True)
    print(f"REPORT: {folder/'SUMMARY.md'}")
    return int(args.require_success and not all(r["evaluation"]["final_verified"] for r in records))


if __name__ == "__main__":
    raise SystemExit(main())
