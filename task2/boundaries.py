"""Six controlled development views, never presented as an unseen test set."""
import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from demo.backend import LocalQwen
from demo.ollama_backend import OllamaModel
from .core import ROOT, archive, config, instantiate, messages, read, save
from .runtime import check_online, run_view


def cases():
    entries = []

    def add(name, record, form):
        view = instantiate(record, form)
        view["id"] = name + ":" + form
        view["roles"]["evidence"]["boundary_origin"] = "controlled_development_variant"
        entries.append({"name": name, "origin": "controlled_development_variant",
                        "record": record, "view": view})
        return view

    base = archive("assignment")
    public = read(ROOT / "data/inputs/assignment.json")
    partial = deepcopy(base["unified"]["problem"])
    del partial["parameters"]["cost_matrix"]
    public["description_en"] = (
        "Assign four workshop tasks T0,T1,T2,T3 to five workers W0,W1,W2,W3,W4. "
        "Each task must be assigned to exactly one worker. Each worker can perform at most one task. "
        "Minimize total assignment cost. The cost matrix has not been provided.")
    public["description_zh"] = "人工开发变体：未提供费用矩阵，不得求解。"
    public["source"]["derivation"] = "Controlled missing-matrix variant of the attributed assignment tutorial"
    incomplete = archive("assignment", public=public, problem=partial)
    add("missing_matrix_understanding", incomplete, "understanding")
    add("missing_matrix_call", incomplete, "call")

    # 原文仍有费用；只有之前的提取结果漏掉它，不能请求用户补充原文已有信息。
    view = add("extraction_omission", base, "understanding")
    draft = deepcopy(partial)
    draft["missing_information"] = ["parameters.cost_matrix"]
    view["roles"]["input"]["task_text"] += (
        "\nA prior extraction draft omitted a field. Correct the draft using the full statement above; "
        "do not treat a supplied value as missing. Draft: " + json.dumps(draft))

    add("multiple_legal_methods", base, "method")
    view = add("inapplicable_candidate", archive("printers"), "method")
    # 加入已登记但不适用于本题的真实知识卡，不伪造方法知识，也不在输入标注答案。
    card = deepcopy(next(m for m in config("methods")["methods"] if m["method_id"] == "assignment_jv"))
    keys = list(view["roles"]["input"]["candidates"][0])
    view["roles"]["input"]["candidates"].append({k: card[k] for k in keys})

    permuted = deepcopy(base)
    p = permuted["unified"]["problem"]
    p["entities"].reverse()
    p["parameters"]["cost_matrix"].reverse()
    permuted["unified"]["entities"] = deepcopy(p["entities"])
    permuted["unified"]["parameters"] = deepcopy(p["parameters"])
    permuted["unified"]["entity_order"] = deepcopy(p["entities"])
    permuted["evidence"]["field_evidence"] = {}
    permuted["evidence"]["transformation"] = "Reversed worker order and corresponding cost rows; task order unchanged"
    add("consistent_permutation", permuted, "call")
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--instances", type=Path, help="Reuse saved boundary instances instead of rebuilding")
    parser.add_argument("--backend", choices=("local", "ollama"), default="local")
    parser.add_argument("--model", default="qwen2.5:14b")
    parser.add_argument("--ollama-url")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory.exists():
        parser.error("Choose a new boundary output directory; history is never overwritten")
    entries = read(args.instances) if args.instances else cases()
    checks = []
    for entry in entries:
        view = entry["view"]
        messages(view)
        target = view["roles"]["target"]
        check_online(view, target["example"] if view["form"] == "method" else target)
        checks.append({"name": entry["name"], "target_interface_passed": True})
    save(directory / "instances.json", entries)
    save(directory / "validation.json", checks)
    if args.validate_only:
        print("Six boundary templates instantiated and checked; no model invoked")
        return
    results = {"created_at": datetime.now().astimezone().isoformat(), "template_version": config("templates")["version"],
               "origin": "controlled_development_variants_not_unseen_test", "validation": checks, "runs": []}
    backend = (OllamaModel(args.ollama_url, args.model) if args.backend == "ollama"
               else LocalQwen(max_new_tokens=1400))
    results["model_config"] = (backend.probe() if args.backend == "ollama"
                               else {"backend": "local", "model": "Qwen2.5-0.5B-Instruct"})
    for entry in entries:
        print("Running boundary " + entry["name"], flush=True)
        result = run_view(entry["view"], entry["record"], backend, retries=2)
        result["boundary_name"] = entry["name"]
        results["runs"].append(result)
        save(directory / "results.json", results)
        print(f"  first={result['first_correct']} final={result['final_correct']} attempts={len(result['attempts'])}", flush=True)


if __name__ == "__main__":
    main()
