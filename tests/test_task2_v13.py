"""v1.3 fixes and new data: deterministic tests, not real model achievements."""
from copy import deepcopy
import json

import pytest

from demo.backend import ModelError
from demo.validation import ValidationError
from task2.core import archive, instantiate, messages, read, ROOT, fixture_call, digest
from task2.diagnostics import field_checks, problem_matches
from task2.expansion import (BudgetedBackend, certificates, load_records, run_models,
                             public_summary)
from task2.handoff import validate_partial, receive_problem
from task2.runtime import check_online, run_view
from task2.tools import solve_direct
from task2.workflow import prepare, validate


def move_bounds(p):
    result = deepcopy(p)
    params = result["parameters"]
    n = len(result["entities"])
    for i, (lo, hi) in enumerate(zip(params["lower_bounds"], params["upper_bounds"])):
        for sign, value in ((">=", lo), ("<=", hi)):
            if value is None:
                continue
            row = [0]*n
            row[i] = 1
            params["constraints"].append({"name": "explicit_bound", "coefficients": row,
                                           "sense": sign, "rhs": value,
                                           "unit": p["units"]["quantity"]})
    # Keep lower bounds: replacing them by zero adds weaker redundant rows,
    # outside the registered equivalence rules (not a general LP proof engine).
    params["upper_bounds"] = [None]*n
    return result


def test_advertising_quantity_bounds_are_not_dollar_constraints():
    p = archive("advertising")["unified"]["problem"]
    assert problem_matches(move_bounds(p), p)


@pytest.mark.parametrize("change", ["budget", "bound", "scale_wrong_unit"])
def test_units_checked_per_constraint_not_global_union(change):
    p = archive("advertising")["unified"]["problem"]
    candidate = move_bounds(p)
    if change == "bound":
        candidate["parameters"]["constraints"][-1]["unit"] = "dollars"
    else:
        row = candidate["parameters"]["constraints"][0]
        row["unit"] = "ads"
        if change == "scale_wrong_unit":
            row["coefficients"] = [3*x for x in row["coefficients"]]
            row["rhs"] *= 3
    assert not problem_matches(candidate, p)
    assert any(x["group"] == "units" and x["status"] == "review_required" for x in field_checks(candidate, p))


def test_scaled_reordered_units_with_bounds_pass():
    p = archive("advertising")["unified"]["problem"]
    candidate = move_bounds(p)
    for row in candidate["parameters"]["constraints"]:
        row["coefficients"] = [2*x for x in row["coefficients"]]
        row["rhs"] *= 2
    candidate["parameters"]["constraints"].reverse()
    assert problem_matches(candidate, p)


def test_general_redundancy_still_requires_review():
    p = archive("advertising")["unified"]["problem"]
    candidate = move_bounds(p)
    candidate["parameters"]["lower_bounds"] = [0,0]
    assert not problem_matches(candidate, p)
    assert any(x["status"] == "review_required" for x in field_checks(candidate, p))


def test_equalities_match_both_unit_directions():
    p = archive("printers")["unified"]["problem"]
    p["parameters"]["constraints"][0]["sense"] = "="
    candidate = deepcopy(p)
    assert problem_matches(candidate, p)
    candidate["parameters"]["constraints"][0]["unit"] = "dollars"
    assert not problem_matches(candidate, p)


@pytest.mark.parametrize("placeholder", [[], [[0,0]], None])
def test_missing_placeholder_feedback_is_specific(placeholder):
    p = deepcopy(load_records()[-1]["unified"]["problem"])
    p["parameters"]["cost_matrix"] = placeholder
    with pytest.raises(ValidationError, match="parameters.cost_matrix is marked missing but still present; omit"):
        validate_partial(p)


def test_missing_prompt_has_no_all_keys_requirement():
    view = instantiate(load_records()[-1], "understanding")
    text = messages(view)[0]["content"]
    assert "exact keys" not in text and "omit" in text and "placeholder" in text
    assert "Respect explicit integer or continuous" in text


def test_missing_feedback_can_repair_without_reference_leak():
    record = load_records()[-1]
    view = instantiate(record, "understanding")
    correct = deepcopy(view["roles"]["target"])
    bad = deepcopy(correct)
    bad["parameters"]["cost_matrix"] = []
    class Fake:
        def __init__(self):
            self.responses = iter([bad, correct])
        def generate(self, prompt):
            return {"raw_text": json.dumps(next(self.responses)), "origin": "synthetic_unit_test"}
    result = run_view(view, record, Fake())
    assert result["feedback_repaired"]
    feedback = result["attempts"][1]["messages"][-1]["content"]
    assert "omit this field" in feedback and "certificate" not in feedback


@pytest.mark.parametrize("variable_type", ["integer", "continuous"])
def test_variable_type_follows_reference_not_object_name(variable_type):
    p = archive("printers")["unified"]["problem"]
    p["parameters"]["variable_type"] = variable_type
    record = archive("printers", problem=p)
    view = instantiate(record, "understanding")
    check_online(view, p)
    assert problem_matches(p, p)
    bad = deepcopy(p)
    bad["parameters"]["variable_type"] = "continuous" if variable_type == "integer" else "integer"
    assert not problem_matches(bad, p)
    if variable_type == "continuous":
        with pytest.raises(ValidationError, match="No registered method"):
            instantiate(record, "call")


def test_previous_instances_cannot_silently_use_v13():
    view = instantiate(archive("printers"), "understanding")
    view["version"] = "1.2"
    with pytest.raises(ValidationError, match="version/hash"):
        messages(view)


def test_catalog_has_twelve_and_only_four_scored():
    qs = read(ROOT / "data/task2_v13/catalog.json")["questions"]
    assert len(qs) == len({q["id"] for q in qs}) == 12
    assert sum(q["verification"] == "candidate_only" for q in qs) == 8
    assert len(load_records()) == 4
    assert all(sum(q["group"] == g for q in qs) == 4 for g in ("production", "assignment", "budget"))


def test_statement_certificates_are_independent():
    c = certificates()
    assert c["glass"]["objective_value"] == 480 and c["glass"]["witness"] == [60, 0]
    assert c["library_assignment"]["objective_value"] == 9
    assert c["library_assignment"]["candidates_checked"] == 24
    assert c["book_budget"]["contradiction"]
    assert c["repair_missing"]["status"] == "needs_information"


@pytest.mark.parametrize("index", [0,1,2])
def test_new_cases_real_solver_matches_independent_certificate(index):
    from demo.evaluation import evaluate_attempt
    record = load_records()[index]
    p = record["unified"]["problem"]
    method = "assignment_jv" if p["problem_type"] == "assignment" else "highs_milp"
    result = solve_direct(fixture_call(p, method))
    assert evaluate_attempt({"problem": p, "solver_result": result}, p,
                            record["unified"]["reference_result"])["verified_against_reference"]


def test_new_partial_restored_by_real_supplied_costs():
    record = load_records()[-1]
    p = deepcopy(record["unified"]["problem"])
    p["parameters"]["cost_matrix"] = [[4,1],[2,5],[7,8]]
    p["missing_information"] = []
    p = receive_problem(p)
    assert solve_direct(fixture_call(p,"assignment_jv"))["objective_value"] == 3


def test_new_frozen_views_and_roles(tmp_path):
    payload = prepare(tmp_path, records=load_records())
    assert len(payload["views"]) == 15 and len(payload["fixtures"]) == 3
    assert payload["unavailable_views"] == [{"case_id":"repair_missing", "form":"result", "reason":"missing_data_no_actual_return"}]
    assert validate(payload, tmp_path)["passed"]
    for view in payload["views"]:
        initial = messages(view)
        for role in ("target", "process", "evidence"):
            view["roles"][role] = {"private": "SECRET"}
        view["id"] = "SECRET_FILENAME"
        assert messages(view) == initial


def test_deadline_prevents_request():
    class Forbidden:
        def generate(self, prompt):
            pytest.fail("Request after deadline")
    with pytest.raises(ModelError, match="deadline"):
        BudgetedBackend(Forbidden(), 0).generate([])


def test_probe_failure_is_reported_without_fallback(tmp_path):
    payload = prepare(tmp_path, records=load_records())
    class Down:
        def probe(self):
            raise ModelError("model_unavailable", "private service information")
    results = run_models(payload, tmp_path, names=("ollama",), factories={"ollama": Down})
    summary = public_summary(payload, validate(payload, tmp_path), results)
    assert results["models"]["ollama"]["status"] == "model_unavailable"
    assert len(summary["models"]["ollama"]["not_run"]) == 15
    assert "private service" not in json.dumps(summary)
    assert summary["models"]["ollama"]["completed_views"] == 0


def test_supplied_answer_never_changes_messages():
    original = load_records()[0]
    changed = deepcopy(original)
    changed["unified"]["reference_result"] = {"status": "infeasible", "objective_value": 987654321}
    for form in ("understanding", "method", "call"):
        assert messages(instantiate(original, form)) == messages(instantiate(changed, form))


def test_model_timeout_stops_backend_without_extra_requests(tmp_path):
    payload = prepare(tmp_path, records=load_records())
    class Timeout:
        calls = 0
        def generate(self, prompt):
            self.calls += 1
            raise ModelError("model_timeout", "simulated timeout, not a real run")
    model = Timeout()
    results = run_models(payload, tmp_path, names=("local",), factories={"local": lambda: model})
    assert model.calls == 1
    state = results["models"]["local"]
    assert state["status"] == "model_timeout" and len(state["not_run"]) == 14
    summary = public_summary(payload, validate(payload, tmp_path), results)
    assert not summary["comparison_complete"] and summary["matched_pair_views"] == 0


def test_public_projection_detects_actual_message_tampering(tmp_path):
    payload = prepare(tmp_path, records=load_records())
    class Down:
        def generate(self, prompt):
            raise ModelError("model_unavailable", "simulated")
    results = run_models(payload, tmp_path, names=("local",), factories={"local": Down})
    validation = validate(payload, tmp_path)
    public_summary(payload, validation, results)
    results["models"]["local"]["runs"][0]["attempts"][0]["messages"][0]["content"] += " modified"
    with pytest.raises(ValidationError, match="input mismatch"):
        public_summary(payload, validation, results)


def test_public_projection_detects_instance_tampering(tmp_path):
    payload = prepare(tmp_path, records=load_records())
    class Down:
        def probe(self):
            raise ModelError("model_unavailable", "simulated")
    results = run_models(payload, tmp_path, names=("ollama",), factories={"ollama": Down})
    payload["records"][0]["evidence"]["human_review"] = "forged"
    with pytest.raises(ValidationError, match="instances changed"):
        public_summary(payload, {}, results)


def test_no_fixture_for_missing_new_case(monkeypatch, tmp_path):
    import task2.workflow as workflow
    def forbidden(*a, **k):
        pytest.fail("Missing case must never reach solver")
    monkeypatch.setattr(workflow, "solve", forbidden)
    payload = prepare(tmp_path, records=[load_records()[-1]])
    assert len(payload["views"]) == 3 and not payload["fixtures"]
