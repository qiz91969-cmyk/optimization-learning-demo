"""Reproducible preparation, instance checks, experiments and chain execution."""
from copy import deepcopy
from datetime import datetime

from demo.evaluation import evaluate_attempt
from demo.validation import ValidationError
from .core import (CASES, FORMS, ROOT, applicable, archive, check_exports, config, digest,
                   export_views, fixture_call, instantiate, messages, read, save)
from .runtime import check_online, run_view
from .tools import solve


def prepare(directory, cases=CASES):
    records, views, fixtures = [], [], []
    for case in cases:
        record = archive(case)
        p = record["unified"]["problem"]
        call = fixture_call(p, applicable(p)[0])
        actual = solve(call)
        check = evaluate_attempt({"problem": p, "solver_result": actual}, p,
                                 record["unified"]["reference_result"])
        if not check["verified_against_reference"]:
            raise ValidationError("Fixture failed independent verification: " + case)
        fixtures.append({"case_id": case, "origin": "verified_handoff_fixture_not_model_call",
                         "call": call, "actual_return": actual, "evaluation": check})
        records.append(record)
        for form in FORMS:
            view = instantiate(record, form, actual_return=actual)
            view["roles"]["evidence"]["result_origin"] = "verified_handoff_fixture_not_model_call" if form == "result" else None
            views.append(view)
    payload = {"created_at": datetime.now().astimezone().isoformat(), "records": records,
               "views": views, "fixtures": fixtures,
               "config_hashes": {n: digest(config(n)) for n in ("mappings", "templates", "methods")}}
    save(directory / "instances.json", payload)
    export_views(views, directory / "exports")
    return payload


def validate(payload, directory):
    checks = []
    def record_check(name, fn):
        try:
            fn()
            checks.append({"name": name, "passed": True})
        except (ValueError, KeyError, TypeError, AssertionError) as exc:
            checks.append({"name": name, "passed": False, "error": str(exc)})
    def check_configs():
        if payload["config_hashes"] != {n: digest(config(n)) for n in ("mappings", "templates", "methods")}:
            raise ValidationError("Configuration changed since instantiation")
    record_check("mapping_template_method_versions", check_configs)
    for view in payload["views"]:
        def check_instance(view=view):
            messages(view)
            target = view["roles"]["target"]
            target = target["example"] if view["form"] == "method" else target
            check_online(view, target)
        record_check(view["id"] + ":target_interface", check_instance)
        def isolation(view=view):
            altered = deepcopy(view)
            for role in ("process", "target", "evidence"):
                altered["roles"][role] = {"canary": "HIDDEN_REFERENCE_DO_NOT_EXPOSE"}
            altered["id"] = "HIDDEN_FILENAME_5050"
            if messages(altered) != messages(view):
                raise ValidationError("Hidden role affects model request")
        record_check(view["id"] + ":role_isolation", isolation)
    record_check("two_export_formats_roundtrip", lambda: check_exports(directory / "exports", payload["views"]))
    def reuse():
        expected = {(r["id"], f) for r in payload["records"] for f in FORMS}
        actual = {(v["case_id"], v["form"]) for v in payload["views"]}
        if actual != expected or len(actual) != len(payload["views"]):
            raise ValidationError("Cross-case/view reuse coverage mismatch")
    record_check("cross_case_and_cross_learning_goal_reuse", reuse)
    return {"passed": all(c["passed"] for c in checks), "checks": checks,
            "instances": len(payload["views"]), "cases": len(payload["records"]),
            "human_review": "pending"}


def fault_checks(payload):
    """Synthetic errors are separate from model measurements."""
    views = {(v["case_id"], v["form"]): v for v in payload["views"]}
    base = views[("assignment", "call")]
    output = deepcopy(base["roles"]["target"])
    variants = []
    bad = deepcopy(output); del bad["arguments"]["units"]
    variants.append(("missing_argument", base, bad))
    bad = deepcopy(output); bad["arguments"]["parameters"]["cost_matrix"][0].pop()
    variants.append(("matrix_dimension", base, bad))
    bad = deepcopy(output); bad["tool_name"] = ["solve_assignment_jv"]
    variants.append(("illegal_tool_type", base, bad))
    bad = deepcopy(output); bad["arguments"]["parameters"]["cost_matrix"].reverse()
    variants.append(("matrix_order_without_entity_order", base, bad))
    view = deepcopy(base); view["roles"]["input"]["context"]["tool_version"] = "unregistered"
    variants.append(("tool_version_mismatch", view, output))
    results = []
    for name, view, value in variants:
        try:
            check_online(view, value)
            results.append({"name": name, "blocked": False})
        except ValidationError as exc:
            results.append({"name": name, "blocked": True, "feedback": str(exc)})
    return {"origin": "synthetic_fault_injection_not_Qwen", "results": results}


def run_chain(record, backend, retries=2):
    steps, problem, method, actual = [], None, None, None
    for index, form in enumerate(FORMS):
        view = instantiate(record, form, actual_return=actual, problem=problem, method_id=method)
        view["roles"]["evidence"]["result_origin"] = "this_chain_actual_model_call" if form == "result" else None
        result = run_view(view, record, backend, retries=retries)
        steps.append(result)
        if not result["final_correct"]:
            return {"case_id": record["id"], "passed": False, "steps": steps,
                    "stopped_at": form, "skipped": list(FORMS[index+1:]),
                    "policy": "Offline evaluation stops the chain but never supplies a reference replacement"}
        output = result["attempts"][-1]["output"]
        if form == "understanding":
            problem = output
        elif form == "method":
            method = output["method_id"]
        elif form == "call":
            actual = result["attempts"][-1].get("solver_result")
    return {"case_id": record["id"], "passed": True, "steps": steps, "skipped": []}
