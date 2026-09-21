"""HTML and Markdown are two renderings of one measured result file."""
import html
from pathlib import Path

from .core import FORMS, save

LABELS = {"understanding": "问题理解", "method": "方法选择", "call": "工具使用·调用构造", "result": "工具使用·返回解读"}
GAPS = ["本轮仅4道公开民用开发题；未覆盖正式方案8类场景、至少5类问题、3类算法骨架。",
        "任务一正式元模型、场景分类、版本化交接接口尚未接入；当前是显式标注的临时档案。",
        "未开展任务三批量扩充或微调；两种JSONL只是模板交付示例，不是人工验收训练集。",
        "所有案例的来源到逐字段语义、开放文字依据仍待人工复核；程序检查不能替代这项工作。",
        "固定开发题上的结果不能推断总体正确率，也没有验证自由算法搜索或性能优劣。"]


def render(results, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    runs = results.get("runs", [])
    validation = results.get("validation", {})
    template_version = results.get("template_version", "1.0")
    model_name = results.get("model_config", {}).get("model", "本地Qwen2.5-0.5B-Instruct")
    engineering = "已实现并验证" if validation.get("passed") else "尚未通过工程检查"
    requirements = [
        ("1 训练要素提取与统一表达", engineering, "mappings.json；来源路径、类型、单位、转换记录；临时档案"),
        ("2 输入、过程、目标分层", engineering, "四角色白名单；隐藏角色变更检查；参考评价不进入反馈"),
        ("3 三类学习目标配置", engineering, f"同一档案形成4种视图；{validation.get('instances', 0)}个实例；工具使用含两个子形式"),
        ("4 复用、扩展与实例化", engineering, "跨案例/跨目标复用；双格式往返；版本检查；人工变体单列")]
    lines = ["# 任务二训练模板Demo进度总览", "",
             "本报告由 results.json 自动生成。工程检查、模型正确性、工具求解与人工复核分别统计。",
             "", f"运行时间：{results.get('created_at', '未知')}；模板版本：{template_version}；模型：{model_name}。",
             f"独立视图已运行：{len(runs)}/16；首轮规则核验通过：{sum(r['first_correct'] for r in runs)}；最终通过：{sum(r['final_correct'] for r in runs)}。",
             "这些数只表示本次开发题实测，不是正式项目完成率。", "", "## 四项要求", "",
             "| 要求 | 工程状态 | 可检查的实现证据 |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in requirements]
    lines += ["", "## 三类模板实测矩阵", "",
              "“通过”仅指配置规则与独立参考核验，开放解释仍待人工复核。缺少记录显示未运行。",
              "", "| 案例 | 视图 | 首轮 | 最终 | 尝试数 | 真实工具状态 | 秒 |", "|---|---|---|---|---:|---|---:|"]
    indexed = {(r["case_id"], r["form"]): r for r in runs}
    for case in results.get("cases", []):
        for form in FORMS:
            r = indexed.get((case, form))
            if not r:
                lines.append(f"| {case} | {LABELS[form]} | 未运行 | 未运行 | 0 | 未执行 | - |")
                continue
            first = "通过" if r["first_correct"] else "未通过"
            final = "通过" if r["final_correct"] else "模型验证失败"
            tool = r["attempts"][-1].get("solver_result", {}).get("status", "不适用")
            if form == "result":
                tool = "独立已核验输入求解（非模型调用）"
            lines.append(f"| {case} | {LABELS[form]} | {first} | {final} | {len(r['attempts'])} | {tool} | {r['elapsed_seconds']} |")
    lines += ["", "## 真实流程与反馈", ""]
    chain = results.get("chain")
    if chain:
        lines.append("工人分配串联：" + ("四步全部通过。" if chain["passed"] else f"在 {LABELS[chain['stopped_at']]} 停止；下游未执行：" + "、".join(LABELS[x] for x in chain["skipped"])))
        for step in chain["steps"]:
            a = step["attempts"][-1]
            lines.append(f"- {LABELS[step['form']]}：{'通过' if step['final_correct'] else '失败'}；" +
                         (a.get("error") or a["evaluation"].get("reason", "独立参考核验"))[:450])
    else:
        lines.append("串联流程尚未运行。")
    repairs = sum(r["feedback_repaired"] for r in runs)
    lines += [f"独立视图中，同一次运行反馈后通过：{repairs}。这与修改提示后另起运行不同；不能据此声称普遍提升。"]
    successful_call = next((r for r in runs if r["form"] == "call" and r["final_correct"]
                            and "solver_result" in r["attempts"][-1]), None)
    if successful_call:
        attempt = successful_call["attempts"][-1]
        call, actual = attempt["output"], attempt["solver_result"]
        lines += ["", "### 一个真实调用成功实例", "",
                  f"案例 {successful_call['case_id']}：已核验问题作为输入 → Qwen生成 {call['tool_name']} 与arguments → Harness检查 → 真实工具执行 → 独立参考核验。",
                  f"实体次序：{call['arguments']['entities']}；实际方案：{actual['values']}；实际目标值：{actual['objective_value']}；状态：{actual['status']}。",
                  "这证明该独立调用视图成功，不等于它的问题理解视图或整条串联成功。"]
    for r in runs:
        if not r["final_correct"]:
            last = r["attempts"][-1]
            lines.append(f"- 失败定位 {r['view_id']}：" + (last.get("error") or str(last["evaluation"]))[:350].replace("\n", " "))
    lines += ["", "## 实际求解与质量记录", "",
              "| 案例 | 已核验输入的真实求解 | 参考核验 | 人工复核 |", "|---|---|---|---|"]
    for fixture in results.get("fixtures", []):
        a = fixture["actual_return"]
        lines.append(f"| {fixture['case_id']} | {a['status']} / {a.get('objective_value')} | {'通过' if fixture['evaluation']['verified_against_reference'] else '失败'} | 待复核 |")
    attempts = [a for r in runs for a in r["attempts"]]
    lines += ["", f"全部独立视图尝试共{len(attempts)}轮：原生JSON {sum(a['raw_json_compliant'] for a in attempts)}轮；"
              f"去单层代码框后可解析JSON {sum(a['normalized_json_compliant'] for a in attempts)}轮；"
              f"接口检查通过 {sum(a['online_pass'] for a in attempts)}轮。",
              "原生JSON可解析不等于满足Schema，更不等于题意正确。每轮原文、提示、反馈、模型版本和耗时保存在results.json。",
              "", "## 人工故障与回归测试", ""]
    for fault in results.get("faults", {}).get("results", []):
        lines.append(f"- 人工注入 {fault['name']}：{'已阻止' if fault['blocked'] else '未阻止'}。")
    tests = results.get("tests")
    lines.append("自动化回归：" + (f"{tests['tests']}项，失败{tests['failures']}，错误{tests['errors']}，跳过{tests['skipped']}；见tests.xml。" if tests else "尚未附加本轮测试记录。"))
    lines += ["超时单元测试为模拟分支覆盖，不冒充真实模型/求解器超时实验。", "", "## 完整方案覆盖缺口", ""]
    lines += ["- " + gap for gap in GAPS]
    lines += ["", "## 文件入口", "", "- results.json：本次实测，含串联记录与每轮消息。",
              "- instances.json：临时档案、四角色视图、来源和实际基准求解。",
              "- exports/instruction.jsonl 与 exports/messages.jsonl：两种示例，人工复核状态均为pending。",
              "- validation.json：逐实例、隔离、版本和格式往返检查。",
              "- ../../docs/任务二学习说明.md：从临时交接到模板检查的阅读顺序。"]
    markdown = "\n".join(lines) + "\n"
    (directory / "任务二进度总览.md").write_text(markdown, encoding="utf-8")
    # Render a deliberately small Markdown subset; escape all model-derived text.
    fragments, table = [], False
    for line in lines:
        if line.startswith("|"):
            if line.startswith("|---"):
                continue
            if not table:
                fragments.append('<div class="table-scroll"><table>'); table = True
            fragments.append("<tr>" + "".join("<td>" + html.escape(x.strip()) + "</td>" for x in line.strip("|").split("|")) + "</tr>")
            continue
        if table:
            fragments.append("</table></div>"); table = False
        if line.startswith("# "):
            fragments.append("<h1>" + html.escape(line[2:]) + "</h1>")
        elif line.startswith("### "):
            fragments.append("<h3>" + html.escape(line[4:]) + "</h3>")
        elif line.startswith("## "):
            fragments.append("<h2>" + html.escape(line[3:]) + "</h2>")
        elif line:
            fragments.append("<p>" + html.escape(line) + "</p>")
    if table:
        fragments.append("</table></div>")
    cards = f'<section class="metrics"><div><b>{len(runs)}/16</b>独立视图已实测</div><div><b>{sum(r["final_correct"] for r in runs)}</b>最终规则核验通过</div><div><b>{repairs}</b>同次反馈后通过</div><div><b>待复核</b>开放解释与来源语义</div></section>'
    stylesheet = """body{margin:0;background:#fff;color:#20262a;font:15px/1.65 'Microsoft YaHei',sans-serif;letter-spacing:0}main{max-width:1200px;margin:auto;padding:28px 24px 64px}h1{font-size:25px;margin:0 0 16px}h2{font-size:19px;border-bottom:2px solid #248578;padding-bottom:8px;margin-top:32px}p{margin:9px 0;overflow-wrap:anywhere}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;border-top:4px solid #248578;border-bottom:1px solid #cbd2d5;padding:18px 0;margin:20px 0}.metrics div{font-size:13px}.metrics b{display:block;font-size:26px;color:#176b61}.metrics div:last-child b{color:#915b0b;font-size:23px}table{border-collapse:collapse;width:100%;font-size:13px}td{padding:10px 12px;border:1px solid #d9e0e3;vertical-align:top;min-width:65px;overflow-wrap:anywhere}tr:first-child{font-weight:bold;background:#eef4f3}tr:nth-child(even){background:#f7f9fa}.table-scroll{overflow-x:auto}header{color:#626b70;font-size:12px;margin-bottom:10px}@media(max-width:650px){main{padding:18px 12px}h1{font-size:21px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}td{padding:8px}}@media print{main{max-width:none}.table-scroll{overflow:visible}h2{break-after:avoid}tr{break-inside:avoid}}"""
    def status_cell(run):
        if run is None:
            return '<td class="pending">未运行</td>'
        return '<td class="good">通过</td>' if run["final_correct"] else '<td class="bad">未通过</td>'
    compact = '<table><tr><td>案例</td><td>问题理解</td><td>方法选择</td><td>调用构造</td><td>返回解读</td></tr>'
    for case in results.get("cases", []):
        compact += '<tr><td>' + html.escape(case) + '</td>' + ''.join(status_cell(indexed.get((case, f))) for f in FORMS) + '</tr>'
    compact += '</table>'
    evidence_table = '<table><tr><td>任务二要求</td><td>实现证据</td></tr>'
    for label, state, evidence in requirements:
        evidence_table += '<tr><td>' + html.escape(label) + '<br><strong>' + html.escape(state) + '</strong></td><td>' + html.escape(evidence) + '</td></tr>'
    evidence_table += '</table>'
    chain_steps = {s["form"]: s for s in chain["steps"]} if chain else {}
    flow = '<div class="flow">'
    for i, form in enumerate(FORMS):
        step = chain_steps.get(form)
        state = '通过' if step and step["final_correct"] else '停止：验证失败' if step else '未执行'
        css = 'good' if step and step["final_correct"] else 'bad' if step else 'pending'
        flow += '<div class="' + css + '"><span>' + str(i+1) + '. ' + LABELS[form] + '</span><b>' + state + '</b></div>'
    flow += '</div>'
    overview = '<h1>任务二训练模板：本轮实测进度</h1><p>实际模型：<strong>' + html.escape(model_name) + '</strong>。模板工程与模型能力分开验收。仅4道公开民用开发题；未训练模型，人工语义复核尚未完成。</p>' + cards
    overview += '<div class="overview-grid"><section><h2>四项要求 · 工程证据</h2><div class="table-scroll">' + evidence_table + '</div></section><section><h2>三类模板 · 最终规则核验</h2><div class="table-scroll">' + compact + '</div><p class="small">后两列同属工具使用。独立视图使用各自已核验输入，不是从头串联成绩；开放文字仍待复核。</p></section></div>'
    overview += '<h2>工人分配 · 实际串联</h2>' + flow
    overview += '<p class="gap"><strong>正式方案尚未覆盖：</strong>8类场景、至少5类问题及3类算法骨架的完整覆盖；任务一正式交接；人工验收与后续训练。本轮无整体完成百分比。</p><p class="small">下方为逐轮统计、失败定位与完整证据目录。数据唯一来源：results.json。</p>'
    stylesheet += '.overview-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px}.overview-grid section{min-width:0}.overview-grid h2{margin-top:8px}.overview-grid td{font-size:12px;padding:8px}.good{color:#176b61;background:#eef8f3}.bad{color:#a22b35;background:#fff2f2}.pending{color:#6c7378;background:#f3f5f6}.flow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.flow div{border-top:3px solid currentColor;padding:10px 12px}.flow span,.flow b{display:block}.flow b{font-size:15px}.small{font-size:12px;color:#626b70}.gap{padding:10px 14px;border-left:4px solid #b57b23;background:#fff8eb;font-size:13px}.details{border-top:1px solid #cbd2d5;margin-top:36px;padding-top:28px}@media(max-width:850px){.overview-grid{grid-template-columns:minmax(0,1fr)}.flow{grid-template-columns:repeat(2,minmax(0,1fr))}}'
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>任务二进度总览</title><style>' + stylesheet + '</style><main><header>PUBLIC CIVILIAN DEMO / TASK 2 / TEMPLATE v' + html.escape(template_version) + '</header>' + overview + '<div class="details">' + "".join(fragments) + "</div></main></html>"
    (directory / "任务二进度总览.html").write_text(document, encoding="utf-8")
    return directory / "任务二进度总览.html"
