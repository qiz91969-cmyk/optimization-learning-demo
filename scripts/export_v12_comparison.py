"""Export fixed-input base/boundary comparison from saved runs only."""
import hashlib
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from task2.core import read, save
from task2.compare import comparison, summarize


def paired(left, right, count):
    a = {r["view_id"]: r for r in left["runs"]}
    b = {r["view_id"]: r for r in right["runs"]}
    if set(a) != set(b) or len(a) != count:
        raise ValueError("Incomplete or mismatched recorded views")
    rows = []
    for key in a:
        equal = a[key]["attempts"][0]["messages"] == b[key]["attempts"][0]["messages"]
        if not equal:
            raise ValueError("First request differs: " + key)
        row = {"view_id": key, "first_request_equal": equal}
        for label, value in (("local", a[key]), ("server", b[key])):
            last = value["attempts"][-1]
            row[label] = {k: value[k] for k in ("first_correct", "final_correct", "feedback_repaired")}
            row[label]["attempts"] = len(value["attempts"])
            row[label]["field_checks"] = [{k: c[k] for k in ("path", "status", "reason") if k in c}
                                          for c in last["evaluation"].get("field_checks", [])]
        rows.append(row)
    return {"local": summarize(left), "server": summarize(right), "views": rows,
            "all_first_requests_equal": True}


def main():
    folders = ["task2_v12_local", "task2_v12_14b", "task2_v12_boundaries", "task2_v12_14b_boundaries"]
    paths = [ROOT / "outputs" / f / "results.json" for f in folders]
    local, server, bounds_local, bounds_server = [read(p) for p in paths]
    meta = server["model_config"]
    suites = list(ET.parse(ROOT / "outputs/task2_v12_14b/tests.xml").getroot().iter("testsuite"))
    result = {"template_version": "1.2", "scope": "development_views_not_unseen_test",
              "base": paired(local, server, 16), "boundaries": paired(bounds_local, bounds_server, 6),
              "same_base_config_hashes": comparison(local, server)["same_config_hashes"],
              "server_model": {k: meta[k] for k in ("model", "model_digest", "ollama_version", "details", "options")},
              "tests": {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")},
              "sources": [{"file": p.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
              "limitations": ["Different hardware, quantization and runtime; not a pure parameter-size experiment",
                              "Only initial independent-view requests are identical; feedback and chained outputs may differ",
                              "Open explanations and field evidence require human review"]}
    save(ROOT / "reports/task2-v12-model-comparison.json", result)
    lines = ["# v1.2固定输入模型对比", "", "16个基础视图与6个边界视图的首轮请求逐项相同。反馈轨迹和串联中间结果可不同。均为开发材料，不是独立测试集。", "",
             "| 分组 | 0.5B首轮/最终 | 14B首轮/最终 |", "|---|---|---|"]
    for label, key in (("基础视图", "base"), ("边界视图", "boundaries")):
        a,b = result[key]["local"], result[key]["server"]
        lines.append(f"| {label} | {a['first_correct']}/{a['views']}、{a['final_correct']}/{a['views']} | {b['first_correct']}/{b['views']}、{b['final_correct']}/{b['views']} |")
    for label,key in (("基础逐项", "base"), ("边界逐项", "boundaries")):
        lines += ["", "## " + label, "", "| 视图 | 0.5B最终 | 14B最终 | 14B尝试次数 |", "|---|---|---|---|"]
        for row in result[key]["views"]:
            lines.append(f"| {row['view_id']} | {'通过' if row['local']['final_correct'] else '未通过'} | {'通过' if row['server']['final_correct'] else '未通过'} | {row['server']['attempts']} |")
    lines += ["", "## 本次待修问题", "",
              "14B打印机题将整数写成连续变量。广告题的数学对齐通过，但显式次数边界的ads单位被仅含dollars的参考约束单位集合拦截，属于检查过窄的待修问题；原始14/16保留，不追改成绩。",
              "缺矩阵理解视图识别出了缺失项，却保留空矩阵；模板保持exact keys与省略缺字段的要求存在歧义，需要统一后另起版本复测。本次五个其他边界视图首轮通过，无真实反馈修复成功。",
              "", "## 边界与证据", "", "两组模型的硬件、量化与推理环境不同，不将耗时直接解释为模型速度差异。文字依据、来源语义仍待人工复核。", "",
              "逐项检查、来源哈希与模型标识见task2-v12-model-comparison.json。完整轨迹保留在本机outputs，不把原始请求或服务器信息复制到公开摘要。", ""]
    (ROOT / "reports/task2-v12-model-comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print("Exported fixed-input v1.2 comparison")


if __name__ == "__main__":
    main()
