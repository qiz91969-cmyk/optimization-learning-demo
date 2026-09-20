"""Task-two boundaries, genuine tools, and explicitly synthetic failure tests."""
import json
import subprocess
from copy import deepcopy

import pytest

from demo.backend import ModelError
from demo.evaluation import evaluate_attempt
from demo.validation import ValidationError
from task2.core import (CASES, FORMS, applicable, archive, check_exports, context, export_views,
                        fixture_call, instantiate, interpretation, map_fields, messages)
from task2.runtime import check_online, run_view
from task2.tools import call_problem, solve, solve_direct
from task2.workflow import fault_checks, prepare, run_chain, validate


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    directory = tmp_path_factory.mktemp("task2")
    return prepare(directory), directory


@pytest.fixture
def assignment(prepared):
    payload, _ = prepared
    record = next(x for x in payload["records"] if x["id"] == "assignment")
    views = {x["form"]: deepcopy(x) for x in payload["views"] if x["case_id"] == "assignment"}
    return record, views


class FakeModel:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []

    def generate(self, messages):
        self.requests.append(deepcopy(messages))
        value = self.outputs[min(len(self.requests)-1, len(self.outputs)-1)]
        if isinstance(value, Exception):
            raise value
        return {"raw_text": value if isinstance(value, str) else json.dumps(value), "model": "synthetic_test_only"}


def test_16_views_and_four_roles(prepared):
    payload, directory = prepared
    assert len(payload["views"]) == 16
    assert validate(payload, directory)["passed"]
    assert len({x["category"] for x in payload["views"]}) == 3
    assert all(set(x["roles"]) == {"input", "process", "target", "evidence"} for x in payload["views"])


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("form", FORMS)
def test_targets_and_hidden_roles(prepared, case, form):
    view = next(x for x in prepared[0]["views"] if x["case_id"] == case and x["form"] == form)
    target = view["roles"]["target"]
    check_online(view, target["example"] if form == "method" else target)
    altered = deepcopy(view)
    altered["id"] = "HIDDEN_ANSWER_999999"
    for role in ("target", "process", "evidence"):
        altered["roles"][role] = {"secret": "HIDDEN_ANSWER_999999"}
    assert messages(view) == messages(altered)
    assert "HIDDEN_ANSWER_999999" not in json.dumps(messages(altered))


def test_mapping_missing_and_wrong_types():
    with pytest.raises(ValidationError, match="Missing handoff"):
        map_fields({})
    with pytest.raises(ValidationError, match="Wrong handoff"):
        map_fields({"public": {"description_en": []}})


@pytest.mark.parametrize("key", ["method_version", "tool_version"])
def test_context_version_fail_closed(key):
    with pytest.raises(ValidationError, match="version"):
        context("assignment_jv", "assignment", **{key: "999"})


def test_context_no_current_case_data():
    text = json.dumps(context("assignment_jv", "assignment"))
    for forbidden in ("265", "W0", "reference_result", "reference_call", "witness"):
        assert forbidden not in text


def test_both_assignment_methods_are_accepted(assignment):
    record, views = assignment
    assert applicable(record["unified"]["problem"]) == ["assignment_jv", "highs_milp"]
    for method in applicable(record["unified"]["problem"]):
        card = context(method, "assignment")["method"]
        check_online(views["method"], {"method_id": method, "condition_ids": card["condition_ids"], "explanation": "Fits conditions"})


def test_jv_rejected_for_production(prepared):
    view = next(x for x in prepared[0]["views"] if x["id"] == "printers:method")
    with pytest.raises(ValidationError):
        check_online(view, {"method_id": "assignment_jv", "condition_ids": ["assignment_one_to_one"], "explanation": "bad"})


@pytest.mark.parametrize("name", [[], {}, True, None, "execute_python"])
def test_illegal_tools(assignment, name):
    call = deepcopy(assignment[1]["call"]["roles"]["target"])
    call["tool_name"] = name
    with pytest.raises(ValidationError):
        call_problem(call)


def test_missing_information_prevents_call(assignment):
    _, views = assignment
    view = views["call"]
    view["roles"]["input"]["problem"]["missing_information"] = ["cost_matrix"]
    del view["roles"]["input"]["problem"]["parameters"]["cost_matrix"]
    assert check_online(view, {"missing_fields": ["cost_matrix"]})["state"] == "needs_information"
    with pytest.raises(ValidationError):
        check_online(view, view["roles"]["target"])


def test_matrix_order_and_version_faults(prepared):
    faults = fault_checks(prepared[0])
    assert len(faults["results"]) == 5
    assert all(x["blocked"] for x in faults["results"])


def test_consistent_matrix_permutation_works(assignment):
    record, _ = assignment
    p = deepcopy(record["unified"]["problem"])
    p["entities"].reverse()
    p["parameters"]["cost_matrix"].reverse()
    view = instantiate(record, "call", problem=p)
    call = view["roles"]["target"]
    check_online(view, call)
    assert solve_direct(call)["objective_value"] == 265


def test_rectangular_assignment_insufficient_workers(assignment):
    record, _ = assignment
    p = deepcopy(record["unified"]["problem"])
    p["entities"] = p["entities"][:2]
    p["parameters"]["cost_matrix"] = p["parameters"]["cost_matrix"][:2]
    assert solve_direct(fixture_call(p, "assignment_jv"))["status"] == "infeasible"


@pytest.mark.parametrize("method", ["assignment_jv", "highs_milp"])
def test_two_real_assignment_backends(assignment, method):
    p = assignment[0]["unified"]["problem"]
    result = solve(fixture_call(p, method))
    assert result["status"] == "optimal" and result["objective_value"] == 265


@pytest.mark.parametrize("value", [True, float("nan"), float("inf")])
def test_result_invalid_numbers(assignment, value):
    view = assignment[1]["result"]
    output = deepcopy(view["roles"]["target"])
    output["objective_value"] = value
    with pytest.raises(ValidationError):
        check_online(view, output)


@pytest.mark.parametrize("status,has_solution", [("limit_reached", False), ("limit_reached", True),
                                                ("solver_timeout", False), ("infeasible", False)])
def test_termination_semantics(assignment, status, has_solution):
    view = assignment[1]["result"]
    result = view["roles"]["input"]["actual_return"]
    result["status"] = status
    if not has_solution:
        result["values"], result["objective_value"] = None, None
    output = interpretation(result)
    assert output["optimality_proven"] is False
    check_online(view, output)
    output["optimality_proven"] = True
    with pytest.raises(ValidationError):
        check_online(view, output)


def test_solver_timeout_simulated(assignment, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("synthetic", 0.1)
    monkeypatch.setattr("task2.tools.subprocess.run", timeout)
    result = solve(assignment[1]["call"]["roles"]["target"])
    assert result["status"] == "solver_timeout" and result["values"] is None


def test_roundtrip_tampering(prepared, tmp_path):
    views = prepared[0]["views"]
    export_views(views, tmp_path)
    path = tmp_path / "messages.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["messages"][2]["role"] = "system"
    path.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
    with pytest.raises(ValidationError):
        check_exports(tmp_path, views)


def test_extra_input_field_and_template_version(assignment):
    view = assignment[1]["method"]
    view["roles"]["input"]["answer"] = 265
    with pytest.raises(ValidationError):
        messages(view)
    del view["roles"]["input"]["answer"]
    view["version"] = "unknown"
    with pytest.raises(ValidationError):
        messages(view)


def test_synthetic_retry_and_real_call(assignment):
    record, views = assignment
    model = FakeModel(["not JSON", views["call"]["roles"]["target"]])
    run = run_view(views["call"], record, model)
    assert len(run["attempts"]) == 2
    assert run["feedback_repaired"] and run["final_correct"]
    assert run["attempts"][-1]["solver_result"]["objective_value"] == 265


def test_reference_changes_do_not_change_feedback(assignment):
    record, views = assignment
    changed = deepcopy(record)
    changed["unified"]["reference_result"]["objective_value"] = 999999
    a, b = FakeModel(["bad", views["call"]["roles"]["target"]]), FakeModel(["bad", views["call"]["roles"]["target"]])
    r1 = run_view(views["call"], record, a)
    r2 = run_view(views["call"], changed, b)
    assert a.requests == b.requests
    assert r1["final_correct"] and not r2["final_correct"]


def test_retry_cap_and_model_failure(assignment):
    record, views = assignment
    run = run_view(views["method"], record, FakeModel(["bad"]), retries=2)
    assert len(run["attempts"]) == 3 and not run["final_correct"]
    with pytest.raises(ValueError):
        run_view(views["method"], record, FakeModel(["bad"]), retries=3)
    run = run_view(views["method"], record, FakeModel([ModelError("model_unavailable", "synthetic")]))
    assert len(run["attempts"]) == 1 and run["attempts"][0]["status"] == "model_unavailable"


def test_failed_chain_no_reference_fallback(assignment):
    result = run_chain(assignment[0], FakeModel(["bad"]))
    assert not result["passed"] and result["stopped_at"] == "understanding"
    assert result["skipped"] == ["method", "call", "result"]


def test_synthetic_success_chain_uses_actual_return(assignment):
    record, views = assignment
    outputs = [views["understanding"]["roles"]["target"], views["method"]["roles"]["target"]["example"],
               views["call"]["roles"]["target"], views["result"]["roles"]["target"]]
    backend = FakeModel(outputs)
    result = run_chain(record, backend)
    assert result["passed"] and len(result["steps"]) == 4
    last_input = json.loads(backend.requests[3][1]["content"])
    assert last_input["actual_return"] == result["steps"][2]["attempts"][-1]["solver_result"]


def test_simplified_prompt_keeps_schema_numbers_out(assignment):
    prompt = messages(assignment[1]["understanding"])
    assert "1000000000" not in json.dumps(prompt)
    assert "265" not in prompt[1]["content"]


def test_mapping_includes_method_and_tool_materials(assignment):
    unified = assignment[0]["unified"]
    assert len(unified["method_knowledge"]) == 2
    assert len(unified["tool_contracts"]) == 2
    assert "linear_assignment" in unified["algorithm_skeletons"]
    assert unified["parameters"] == unified["problem"]["parameters"]


def test_current_candidate_filter_is_explicit(prepared):
    view = next(x for x in prepared[0]["views"] if x["id"] == "printers:method")
    assert [x["method_id"] for x in view["roles"]["input"]["candidates"]] == ["highs_milp"]


def test_report_uses_measurements_and_escapes_model_text(prepared, tmp_path):
    from task2.report import render
    payload, directory = prepared
    results = {"cases": list(CASES), "template_version": "1.1", "runs": [],
               "validation": validate(payload, directory), "fixtures": payload["fixtures"],
               "created_at": "<script>alert(1)</script>"}
    path = render(results, tmp_path)
    html = path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "未运行" in html and "0/16" in html
    assert "TEMPLATE v1.1" in html
