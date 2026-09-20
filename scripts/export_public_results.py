"""Export selected recorded metrics without prompts or connection details."""
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from task2.compare import summarize


def main():
    summary = {"scope": "four development cases, not an unseen benchmark", "models": {}}
    for label, folder in (("0.5B", "task2_v11"), ("14B", "ollama14b_comparison")):
        source = ROOT / "outputs" / folder / "results.json"
        result = json.loads(source.read_text(encoding="utf-8"))
        summary["models"][label] = {
            "source": source.relative_to(ROOT).as_posix(),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "metrics": summarize(result),
            "views": [{k: run[k] for k in ("case_id", "form", "first_correct", "final_correct", "feedback_repaired")}
                      for run in result["runs"]],
        }
    compare = json.loads((ROOT / "outputs/ollama14b_comparison/comparison.json").read_text(encoding="utf-8"))
    summary["comparability"] = {k: compare[k] for k in (
        "same_config_hashes", "all_first_prompts_equal", "same_except_fixture_elapsed", "first_prompt_differences")}
    suites = list(ET.parse(ROOT / "outputs/ollama14b_comparison/tests.xml").getroot().iter("testsuite"))
    summary["recorded_tests"] = {k: sum(int(s.get(k, 0)) for s in suites)
                                 for k in ("tests", "failures", "errors", "skipped")}
    summary["human_review"] = "pending"
    directory = ROOT / "reports"
    directory.mkdir(exist_ok=True)
    (directory / "results-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Exported reports/results-summary.json")


if __name__ == "__main__":
    main()
