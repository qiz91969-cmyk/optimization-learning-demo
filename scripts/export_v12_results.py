"""Publish selected v1.2 results; keep raw prompts, source documents and paths private."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from task2.compare import summarize


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def selected_run(run):
    result = {k: run[k] for k in ("view_id", "case_id", "form", "first_correct", "final_correct", "feedback_repaired")}
    result["attempts"] = len(run["attempts"])
    result["final_online_pass"] = run["attempts"][-1]["online_pass"]
    result["tool_executed"] = any("solver_result" in a for a in run["attempts"])
    evaluation = run["attempts"][-1]["evaluation"]
    result["checks"] = [{k: row[k] for k in ("path", "status", "reason") if k in row}
                        for row in evaluation.get("field_checks", [])]
    result["reason"] = evaluation.get("reason", "independent_result_check")
    result["human_review"] = "pending"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "outputs/task2_v12_local")
    parser.add_argument("--boundary", type=Path, default=ROOT / "outputs/task2_v12_boundaries")
    args = parser.parse_args()
    old_path = ROOT / "outputs/task2_v11/results.json"
    base_path, boundary_path = args.base / "results.json", args.boundary / "results.json"
    old, base, boundary = load(old_path), load(base_path), load(boundary_path)
    if len(base["runs"]) != 16 or len(boundary["runs"]) != 6:
        raise ValueError("Incomplete measurements; do not publish as completed")
    suites = list(ET.parse(args.base / "tests.xml").getroot().iter("testsuite"))
    tests = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    result = {
        "template_version": "1.2", "model": "Qwen2.5-0.5B-Instruct",
        "purpose": "development_template_validation_not_unseen_test",
        "comparison_limit": "Template, knowledge input and checker changed; not a controlled same-input model comparison",
        "sources": [{"file": p.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                    for p in (old_path, base_path, boundary_path)],
        "tests": tests, "previous_v11": summarize(old), "base_v12": summarize(base),
        "instance_checks_passed": base["validation"]["passed"],
        "base_views": [selected_run(r) for r in base["runs"]],
        "boundary_views": [selected_run(r) for r in boundary["runs"]],
        "boundary_target_checks": boundary["validation"],
        "review": "Reference evidence and explanations still pending human review",
    }
    destination = ROOT / "reports/task2-v12-summary.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination.name)


if __name__ == "__main__":
    main()
