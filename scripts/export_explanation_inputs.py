"""Make documented input snapshots from a saved run; never invoke a model."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from task2.core import CASES, FORMS, digest, read, save


def main():
    source = ROOT / "outputs/ollama14b_comparison"
    destination = ROOT / "docs/examples/task2_v11_inputs"
    instances = read(source / "instances.json")
    results = read(source / "results.json")
    runs = {r["view_id"]: r for r in results["runs"]}
    views = {v["id"]: v for v in instances["views"]}
    records = {r["id"]: r for r in instances["records"]}
    manifest = {"source": "outputs/ollama14b_comparison", "purpose": "reading_snapshots_not_new_training_data",
                "instances_sha256": digest(instances), "results_sha256": digest(results),
                "human_review": "pending", "files": []}
    for case in CASES:
        path = destination / case / "handoff.json"
        save(path, records[case])
        manifest["files"].append({"path": str(path.relative_to(ROOT)).replace("\\", "/"),
                                  "role": "temporary_handoff_contains_hidden_reference_not_whole_model_input",
                                  "sha256": digest(read(path))})
        for form in FORMS:
            key = case + ":" + form
            visible = views[key]["roles"]["input"]
            actual = runs[key]["attempts"][0]["messages"]
            assert len(actual) == 2 and actual[1]["role"] == "user"
            assert json.loads(actual[1]["content"]) == visible, key
            path = destination / case / (form + "_input.json")
            save(path, visible)
            assert read(path) == visible
            manifest["files"].append({"path": str(path.relative_to(ROOT)).replace("\\", "/"),
                                      "view_id": key, "role": "actual_first_user_input",
                                      "sha256": digest(visible), "matches_recorded_request": True})
    save(destination / "manifest.json", manifest)
    print(f"Exported {len(manifest['files'])} snapshots; all 16 visible inputs match saved model requests.")


if __name__ == "__main__":
    main()
