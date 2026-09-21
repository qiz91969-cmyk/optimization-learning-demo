"""Prepare frozen v1.3 cases, then run bounded, same-input model comparisons."""
import argparse
import math
from copy import deepcopy
from datetime import datetime
from itertools import permutations
from pathlib import Path
import time

from demo.backend import LocalQwen, ModelError, discover_model
from demo.ollama_backend import OllamaModel
from demo.validation import ValidationError
from .core import ROOT, archive, digest, messages, read, save
from .handoff import validate_partial
from .runtime import run_view
from .workflow import prepare, validate


DATA = ROOT / "data/task2_v13"


def certificates():
    """Independent statement arithmetic, not solver matrices or model answers."""
    glass = [(8*r + 10*t, r, t) for r in range(101) for t in range(61)
             if 3*r + 5*t <= 300 and 5*r + 8*t <= 300]
    costs = ((9, 2, 7), (6, 4, 3), (5, 8, 1), (7, 6, 9))
    assignments = [(sum(costs[w][j] for j, w in enumerate(ws)), ws)
                   for ws in permutations(range(4), 3)]
    return {
        "glass": {"status": "optimal", "objective_value": max(glass)[0],
                  "method": "statement_integer_enumeration", "candidates_checked": 101*61,
                  "witness": list(max(glass)[1:])},
        "library_assignment": {"status": "optimal", "objective_value": min(assignments)[0],
                               "method": "statement_injective_assignment_enumeration",
                               "candidates_checked": len(assignments), "workers_by_task": list(min(assignments)[1])},
        "book_budget": {"status": "infeasible", "objective_value": None,
                        "method": "positive_cost_lower_bound", "minimum_cost": 30*3+50*4,
                        "budget": 250, "contradiction": 30*3+50*4 > 250},
        "repair_missing": {"status": "needs_information", "objective_value": None,
                           "method": "explicit_absence_in_statement", "missing_fields": ["parameters.cost_matrix"]},
    }


def load_records():
    catalog = read(DATA / "catalog.json")
    questions = {q["id"]: q for q in catalog["questions"]}
    certs, records = certificates(), []
    for item in read(DATA / "handoffs.json")["records"]:
        q, cert = questions[item["id"]], certs[item["id"]]
        for key in ("status", "objective_value"):
            if item["answer"][key] != cert[key]:
                raise ValidationError("Independent certificate mismatch: " + item["id"])
        validate_partial(item["problem"])
        public = {k: deepcopy(q[k]) for k in (
            "description_en", "description_zh", "modeling_notes_en", "entity_order")}
        public["source"] = {"origin": q["origin"], "source_key": q["source_key"],
                            "source_id": q.get("source_id"),
                            "details": catalog["source_review"][q["source_key"]]}
        record = archive(item["id"], public, item["problem"], item["answer"])
        record["evidence"]["certificate"] = {**cert, "explanation": item["certificate"],
                                               "human_review": "pending"}
        # Whole-source anchors avoid pretending that generated offsets prove semantic alignment.
        anchors = [{"source_field": key, "start": 0, "end": len(public[key]),
                    "quote": public[key], "origin": origin, "human_review": "pending"}
                   for key, origin in (("description_en", q["origin"]),
                                       ("modeling_notes_en", "demo_supplement"))]
        fields = list(item["problem"]) + ["parameters." + k for k in item["problem"]["parameters"]]
        record["evidence"]["field_evidence"] = {k: deepcopy(anchors) for k in fields}
        record["evidence"]["field_provenance"]["problem"] = "data/task2_v13/handoffs.json; curated mapping, whole-source anchors only; human review pending"
        records.append(record)
    return records


class BudgetedBackend:
    def __init__(self, backend, deadline):
        self.backend, self.deadline = backend, deadline

    def generate(self, prompt):
        if time.monotonic() >= self.deadline:
            raise ModelError("budget_exhausted", "Shared experiment deadline reached; no new request sent")
        return self.backend.generate(prompt)


def run_models(payload, directory, names=("local", "ollama"), minutes=60, factories=None):
    if (not math.isfinite(minutes) or minutes <= 0 or not names or
            len(set(names)) != len(names) or not set(names) <= {"local", "ollama"}):
        raise ValueError("Positive budget and distinct supported backends required")
    if (directory / "results.json").exists():
        raise ValueError("Results already exist; use a new directory")
    factories = factories or {"local": lambda: LocalQwen(max_new_tokens=1400), "ollama": OllamaModel}
    deadline = time.monotonic() + minutes*60
    result = {"created_at": datetime.now().astimezone().isoformat(), "template_version": "1.3",
              "input_hashes": {v["id"]: digest(messages(v)) for v in payload["views"]},
              "instances_hash": digest(payload), "budget_minutes": minutes,
              "models": {}, "usage": "frozen_before_run_development_cases; not_population_accuracy"}
    records = {r["id"]: r for r in payload["records"]}
    for name in names:
        state = {"runs": [], "not_run": [], "metadata": {}, "status": "running"}
        result["models"][name] = state
        try:
            if time.monotonic() >= deadline:
                raise ModelError("budget_exhausted", "Shared experiment deadline reached")
            backend = factories[name]()
            if name == "ollama":
                state["metadata"] = backend.probe()
            else:
                if factories.get(name) and not isinstance(backend, LocalQwen):
                    state["metadata"] = {"backend": "synthetic_unit_test"}
                else:
                    python, model = discover_model()
                    if not Path(python).is_file() or not Path(model, "model.safetensors").is_file():
                        raise ModelError("model_unavailable", "Local interpreter/weights unavailable; no download")
                    state["metadata"] = {"backend": "local", "model": "Qwen2.5-0.5B-Instruct",
                                         "max_new_tokens": 1400, "timeout_seconds": 90}
            wrapped = BudgetedBackend(backend, deadline)
            for index, view in enumerate(payload["views"]):
                if time.monotonic() >= deadline:
                    state["status"] = "budget_exhausted"
                    break
                print(f"{name} {view['id']}", flush=True)
                run = run_view(view, records[view["case_id"]], wrapped, retries=2)
                run["first_request_hash"] = digest(run["attempts"][0]["messages"])
                if run["first_request_hash"] != result["input_hashes"][view["id"]]:
                    raise ValidationError("Frozen input changed")
                state["runs"].append(run)
                save(directory / "results.json", result)
                print(f"  first={run['first_correct']} final={run['final_correct']} attempts={len(run['attempts'])}", flush=True)
                terminal = run["attempts"][-1].get("status")
                if terminal and terminal != "validation_failed":
                    state["status"] = terminal
                    break
            else:
                state["status"] = "completed"
        except ModelError as exc:
            state["status"], state["error"] = exc.status, str(exc)
        ran = {r["view_id"] for r in state["runs"]}
        state["not_run"] = [{"view_id": v["id"], "reason": state["status"]}
                            for v in payload["views"] if v["id"] not in ran]
        save(directory / "results.json", result)
    return result


def public_summary(payload, validation, results):
    """Explicit public projection: no raw prompts, local paths, service addresses or errors."""
    if results["instances_hash"] != digest(payload):
        raise ValidationError("Frozen instances changed")
    expected_hashes = {v["id"]: digest(messages(v)) for v in payload["views"]}
    if results["input_hashes"] != expected_hashes:
        raise ValidationError("Frozen requests changed")
    summary = {"template_version": "1.3", "candidate_questions": 12, "verified_cases": 4,
               "applicable_views": len(payload["views"]), "not_applicable": payload["unavailable_views"],
               "engineering_passed": validation["passed"], "engineering_checks": len(validation["checks"]),
               "human_review": "pending", "models": {}, "input_hashes": results["input_hashes"],
               "same_frozen_inputs": True, "usage": results["usage"]}
    for name, state in results["models"].items():
        runs = state["runs"]
        for run in runs:
            if (run["first_request_hash"] != results["input_hashes"][run["view_id"]] or
                    digest(run["attempts"][0]["messages"]) != run["first_request_hash"]):
                raise ValidationError("Comparison input mismatch")
        rows = []
        for run in runs:
            attempt = run["attempts"][-1]
            evaluation = attempt["evaluation"]
            rows.append({k: run[k] for k in ("view_id", "first_correct", "final_correct", "feedback_repaired", "elapsed_seconds")})
            rows[-1].update(attempts=len(run["attempts"]),
                            failure_paths=[c["path"] for c in evaluation.get("field_checks", []) if c["status"] != "pass"],
                            reason=evaluation.get("reason"), last_status=attempt.get("status", "online_pass"))
        meta = state["metadata"]
        summary["models"][name] = {
            "status": state["status"], "model": meta.get("model"), "model_digest": meta.get("model_digest"),
            "completed_views": len(runs), "first_correct": sum(r["first_correct"] for r in runs),
            "final_correct": sum(r["final_correct"] for r in runs),
            "feedback_repaired": sum(r["feedback_repaired"] for r in runs),
            "attempts": sum(len(r["attempts"]) for r in runs),
            "first_raw_json": sum(r["attempts"][0]["raw_json_compliant"] for r in runs),
            "first_normalized_json": sum(r["attempts"][0]["normalized_json_compliant"] for r in runs),
            "first_online_pass": sum(r["attempts"][0]["online_pass"] for r in runs),
            "tool_executions": sum("solver_result" in a for r in runs for a in r["attempts"]),
            "elapsed_seconds": round(sum(r["elapsed_seconds"] for r in runs), 3),
            "rows": rows, "not_run": state["not_run"],
        }
    sets = [{r["view_id"] for r in results["models"].get(name, {}).get("runs", [])}
            for name in ("local", "ollama")]
    summary["matched_pair_views"] = len(sets[0] & sets[1])
    summary["comparison_complete"] = all(s == set(expected_hashes) for s in sets)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--models", nargs="+", choices=("local", "ollama"), default=["local", "ollama"])
    parser.add_argument("--minutes", type=float, default=60)
    parser.add_argument("--public-summary", type=Path)
    args = parser.parse_args()
    if args.directory.exists():
        parser.error("Use a new output directory; history is never overwritten")
    payload = prepare(args.directory, records=load_records())
    validation = validate(payload, args.directory)
    save(args.directory / "validation.json", validation)
    if not validation["passed"]:
        raise ValidationError("Engineering checks failed; models not invoked")
    print(f"Prepared {len(payload['views'])} views; all engineering checks passed", flush=True)
    if args.validate_only:
        return
    results = run_models(payload, args.directory, tuple(args.models), args.minutes)
    summary = public_summary(payload, validation, results)
    save(args.directory / "summary.json", summary)
    if args.public_summary:
        save(args.public_summary, summary)


if __name__ == "__main__":
    main()
