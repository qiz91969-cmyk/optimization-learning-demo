"""Compare recorded runs, not remembered scores; no model requests are made."""
import argparse
import html
import json
from pathlib import Path

from .core import CASES, FORMS, ROOT, read, save

CASE_NAMES = {"assignment": "工人分配", "printers": "打印机", "bakery": "面包房", "advertising": "广告预算"}
FORM_NAMES = {"understanding": "问题理解", "method": "方法选择", "call": "调用构造", "result": "返回解读"}


def differences(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [p for k in sorted(set(a) | set(b)) for p in
                ([path+"."+k] if k not in a or k not in b else differences(a[k], b[k], path+"."+k))]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [path+".length"]
        return [p for i, (x, y) in enumerate(zip(a, b)) for p in differences(x, y, path+f"[{i}]")]
    return [] if a == b else [path]


def message_differences(a, b):
    def expand(messages):
        result = []
        for message in messages:
            item = dict(message)
            if item.get("role") == "user":
                try:
                    item["content"] = json.loads(item["content"])
                except (ValueError, TypeError):
                    pass
            result.append(item)
        return result
    return differences(expand(a), expand(b), "messages")


def summarize(result):
    runs = result.get("runs", [])
    return {"views": len(runs), "first_correct": sum(r["first_correct"] for r in runs),
            "final_correct": sum(r["final_correct"] for r in runs),
            "feedback_repaired": sum(r["feedback_repaired"] for r in runs),
            "attempts": sum(len(r["attempts"]) for r in runs),
            "elapsed_seconds": round(sum(r["elapsed_seconds"] for r in runs), 3),
            "first_raw_json": sum(r["attempts"][0]["raw_json_compliant"] for r in runs),
            "first_online_pass": sum(r["attempts"][0]["online_pass"] for r in runs),
            "tool_executions": sum("solver_result" in a for r in runs for a in r["attempts"]),
            "chain_passed": result.get("chain", {}).get("passed") if result.get("chain") else None}


def comparison(left, right):
    a = {r["view_id"]: r for r in left.get("runs", [])}
    b = {r["view_id"]: r for r in right.get("runs", [])}
    expected = {c+":"+f for c in CASES for f in FORMS}
    common = sorted(set(a) & set(b))
    prompt_checks = {k: a[k]["attempts"][0]["messages"] == b[k]["attempts"][0]["messages"] for k in common}
    diffs = {k: message_differences(a[k]["attempts"][0]["messages"], b[k]["attempts"][0]["messages"]) for k in common}
    return {"left": summarize(left), "right": summarize(right),
            "complete_16_each": set(a) == set(b) == expected,
            "same_config_hashes": bool(left.get("config_hashes")) and left.get("config_hashes") == right.get("config_hashes"),
            "first_prompt_equal": prompt_checks,
            "first_prompt_differences": diffs,
            "same_except_fixture_elapsed": len(common) == 16 and all(
                all(p == "messages[1].content.actual_return.elapsed_seconds" for p in paths) for paths in diffs.values()),
            "all_first_prompts_equal": len(common) == 16 and all(prompt_checks.values()),
            "improved": [k for k in common if not a[k]["final_correct"] and b[k]["final_correct"]],
            "regressed": [k for k in common if a[k]["final_correct"] and not b[k]["final_correct"]]}


def generate(left_path, right_path, directory):
    left, right = read(left_path), read(right_path)
    data = comparison(left, right)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data["sources"] = {"left": str(Path(left_path).resolve()), "right": str(Path(right_path).resolve())}
    data["right_model_config"] = right.get("model_config", {})
    save(directory / "comparison.json", data)
    a = {r["view_id"]: r for r in left.get("runs", [])}
    b = {r["view_id"]: r for r in right.get("runs", [])}
    lines = ["# 本地0.5B与服务器14B：任务二Demo对比", "",
             "本报告由两份真实results.json生成，不重新调用模型，不修改原始成绩。题目均为公开民用开发题，不能据此推断总体能力。", "",
             "## 1. 先看结论", "",
             f"完整规则核验通过数：0.5B为{data['left']['final_correct']}/{data['left']['views']}，14B为{data['right']['final_correct']}/{data['right']['views']}。"
             + ("14B的工人分配四步串联已跑通。" if data['right']['chain_passed'] else "14B串联尚未通过或尚未运行。"),
             f"两侧是否各完成16视图：{'是' if data['complete_16_each'] else '否，属于不完整对比'}；"
             f"模板/方法/映射配置哈希是否一致：{'是' if data['same_config_hashes'] else '否'}。",
             "", "| 指标 | 本地Qwen2.5-0.5B | 服务器qwen2.5:14b |", "|---|---:|---:|"]
    fields = [("独立视图数", "views"), ("首轮完整规则核验通过", "first_correct"),
              ("最终完整规则核验通过", "final_correct"), ("同次反馈后通过", "feedback_repaired"),
              ("首轮原生JSON可解析", "first_raw_json"), ("首轮在线接口检查通过", "first_online_pass"),
              ("总尝试轮数", "attempts"), ("调用视图中的真实工具执行数", "tool_executions"),
              ("16视图累计墙钟秒数（含重试）", "elapsed_seconds")]
    lines += [f"| {label} | {data['left'][key]} | {data['right'][key]} |" for label, key in fields]
    lines += ["", "原生JSON可解析不代表Schema或题意正确；完整规则通过也不等于开放解释已经人工验收。累计耗时包含请求、模型加载/等待和必要的本地求解，不是纯token生成速度。", "",
              f"首轮消息逐字相同：{sum(data['first_prompt_equal'].values())}/16。除实际基准求解耗时外是否一致：{'是' if data['same_except_fixture_elapsed'] else '否或资料不完整'}。",
              ("四个返回解读视图因重新求解而带有不同耗时，其余内容一致；详细差异见comparison.json。" if data['same_except_fixture_elapsed'] and not data['all_first_prompts_equal'] else "详细提示差异见comparison.json。"),
              f"最终结果由未通过变为通过的视图：{len(data['improved'])}；由通过变为未通过：{len(data['regressed'])}。",
              "", "## 2. 每道题、每个模板发生了什么", "",
              "| 案例 | 模板视图 | 0.5B首轮→最终 | 14B首轮→最终 | 0.5B/14B尝试数 |", "|---|---|---|---|---|"]
    def state(run):
        if run is None:
            return "未运行"
        return ("通过" if run["first_correct"] else "失败") + " → " + ("通过" if run["final_correct"] else "失败")
    for case in CASES:
        for form in FORMS:
            key = case+":"+form
            x, y = a.get(key), b.get(key)
            count = f"{len(x['attempts']) if x else 0}/{len(y['attempts']) if y else 0}"
            lines.append(f"| {CASE_NAMES[case]} | {FORM_NAMES[form]} | {state(x)} | {state(y)} | {count} |")
    lines += ["", "三个线性案例的方法候选均只有MILP，因此方法选择通过不代表复杂算法决策；工人分配允许专用指派和MILP。独立返回解读的结果来自已核验输入的真实求解，不代表同一次模型调用成功。", "",
              "## 3. 具体变化，不只看总分", ""]
    def short(value, limit=500):
        return str(value).replace("\n", " ").replace("|", "/")[:limit]
    for key in ("assignment:call", "printers:result", "printers:understanding", "advertising:call"):
        x, y = a.get(key), b.get(key)
        if not x or not y:
            continue
        case, form = key.split(":")
        lines += [f"### {CASE_NAMES[case]} · {FORM_NAMES[form]}", "",
                  "0.5B首轮检查：" + short(x["attempts"][0].get("error", "在线检查通过")),
                  "14B首轮检查：" + short(y["attempts"][0].get("error", "在线检查通过")),
                  "14B最终结果：" + ("完整规则核验通过。" if y["final_correct"] else "未通过，不能用参考答案替换。")]
        last = y["attempts"][-1]
        if key == "printers:understanding" and last.get("output", {}).get("parameters", {}).get("variable_type") == "continuous":
            lines += ["具体未通过点：14B把variable_type写成continuous，而公开补充说明明确要求非负整数。利润系数和产能约束基本正确，但变量类型与Demo约定不一致。",
                      "它把单项上限放进constraints、upper_bounds写成null，这种表达本身允许；本次不能将这处合法的表示差异误当作失败原因。即使本题LP松弛恰好也得到5050，仍不表示它遵守了整数建模要求。",
                      "为什么只有一轮？在线接口认为continuous是合法类型，结构通过便结束；隐藏参考对齐在事后才评分，没有把参考答案反馈给模型。失败不是重试次数耗尽。"]
        if "solver_result" in last:
            result = last["solver_result"]
            lines.append(f"14B产生调用后的实际求解：状态{result['status']}，目标值{result.get('objective_value')}；方案{result.get('values')}。")
        if form == "result" and "output" in y["attempts"][0]:
            first = y["attempts"][0]["output"]
            lines.append(f"14B首轮输出状态={first.get('status')}，next_action={first.get('next_action')}，目标值={first.get('objective_value')}。")
        lines += ["", "14B最终回答节选（截短仅用于展示，完整原文见源记录）：", "", "```text",
                  last.get("raw_text", "无回答")[:900], "```", ""]
    lines += ["## 4. 串联是否真正跑通", ""]
    for label, result in (("0.5B", left), ("14B", right)):
        chain = result.get("chain")
        if not chain:
            lines.append(f"- {label}：未运行串联。")
        elif chain["passed"]:
            lines.append(f"- {label}：工人分配的理解→方法→调用→返回四步通过；只使用本次各步实际输出，没有参考替换。")
        else:
            lines.append(f"- {label}：在{FORM_NAMES[chain['stopped_at']]}停止；下游未执行：" + "、".join(FORM_NAMES[f] for f in chain["skipped"]) + "。")
        if chain:
            for step in chain["steps"]:
                last = step["attempts"][-1]
                lines.append(f"  {FORM_NAMES[step['form']]}：{state(step)}；{len(step['attempts'])}轮；{step['elapsed_seconds']}秒。")
                if not step["final_correct"]:
                    lines.append("  原因：" + short(last.get("error") or last["evaluation"]))
    lines += ["", "## 5. 这次比较能说明什么，不能说明什么", "",
              "两组首轮输入和配置的一致性已逐项检查，具体差异见上文。返回解读材料来自各自真实求解，运行耗时可能不同；不能宣称16份提示逐字完全一致，也没有重新运行来抹掉这一差异。后续严格对照可复用冻结的同一份实例材料。反馈消息会随各自错误而变化，不能要求后续消息也相同。",
              "服务器模型为qwen2.5:14b，实际量化等信息见comparison.json的right_model_config。本地0.5B用Transformers，服务器14B用Ollama；量化、硬件、上下文默认设置、请求时限、服务排队都不同，不能归因于参数量这一个变量。",
              "双方均未新增JSON/Schema强制解码；服务器设置temperature=0、num_predict=1400，不覆盖共享服务的num_ctx和keep_alive。首轮通过增加是换后端后的新实验，不是原0.5B自己纠错成功。",
              "同次反馈后通过只统计各自同一视图内部的修复；失败保持原样。模型返回的开放解释仍待人工复核，方法编号正确并不证明解释句句正确。",
              "这些题已经用于开发，不是未见测试集。本轮不能证明微调效果、全项目验收完成，也不表示所有任务都适合14B。", "",
              "## 6. 接入与证据", "",
              "接入链路：本机Demo → 本机11435 → 用户维持的SSH隧道 → 服务器11434 → Ollama → 本机Harness和SciPy求解器。",
              "没有新增模型下载，没有停止已有服务，没有读取密码，没有上传私有合同或想定。SSH隧道终端关闭后，本机将不能通过该地址访问服务器。",
              "旧记录：outputs/task2_v11/results.json；新记录：" + str(Path(right_path).parent.name) + "/results.json。",
              "comparison.json保存统计、逐视图首轮消息对比、模型标识与两份源文件位置。运行命令见docs/Ollama服务器接入说明.md。"]
    (directory / "模型对比报告.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    # Escape all generated content; snippets must never become executable HTML.
    blocks, table, code = [], False, False
    for line in lines:
        if line.startswith("```"):
            blocks.append("</code></pre>" if code else "<pre><code>")
            code = not code
            continue
        if code:
            blocks.append(html.escape(line)+"\n")
            continue
        if line.startswith("|"):
            if line.startswith("|---"):
                continue
            if not table:
                blocks.append('<div class="scroll"><table>'); table = True
            blocks.append("<tr>"+"".join("<td>"+html.escape(c.strip())+"</td>" for c in line.strip("|").split("|"))+"</tr>")
            continue
        if table:
            blocks.append("</table></div>"); table = False
        if line.startswith("#"):
            level = len(line)-len(line.lstrip("#"))
            blocks.append(f"<h{level}>"+html.escape(line[level:].strip())+f"</h{level}>")
        elif line:
            blocks.append("<p>"+html.escape(line)+"</p>")
    css = "body{margin:0;color:#242c30;background:white;font:15px/1.85 'Microsoft YaHei',sans-serif;letter-spacing:0}main{max-width:1050px;margin:auto;padding:28px 24px 60px}h1{font-size:26px}h2{font-size:21px;margin-top:36px;padding-top:14px;border-top:2px solid #28786e}h3{font-size:18px}p{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;font-size:14px}td{padding:9px 12px;border:1px solid #d9e0e2;min-width:80px}tr:first-child{background:#edf5f2;font-weight:bold}tr:nth-child(even){background:#f7f9fa}.scroll{overflow-x:auto}pre{background:#f3f6f7;padding:16px;border-left:3px solid #28786e;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}@media(max-width:600px){main{padding:16px 12px}h1{font-size:23px}}"
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>任务二模型对比报告</title><style>'+css+'</style><main>'+"".join(blocks)+"</main></html>"
    (directory / "模型对比报告.html").write_text(document, encoding="utf-8")
    return directory / "模型对比报告.html"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, default=ROOT / "outputs/task2_v11/results.json")
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    print(generate(args.left, args.right, args.directory))
