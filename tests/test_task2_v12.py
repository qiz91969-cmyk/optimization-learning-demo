"""Deterministic contract/boundary checks, separate from real Qwen measurements."""
from copy import deepcopy
import json

import pytest

from demo.validation import ValidationError
from task2.boundaries import cases
from task2.contracts import validate_contracts
from task2.core import archive, config, instantiate, messages, fixture_call, interpretation, read, ROOT
from task2.diagnostics import field_checks, problem_matches
from task2.handoff import receive_problem, validate_partial
from task2.runtime import check_online, grade, run_view
from task2.tools import solve_direct


class FakeModel:
    def __init__(self, output):
        self.output = output

    def generate(self, messages):
        return {"raw_text": json.dumps(self.output), "origin": "synthetic_unit_test"}


@pytest.mark.parametrize("form", ["understanding", "method", "call"])
def test_real_missing_handoff_reaches_template_without_tool(form):
    p = archive("assignment")["unified"]["problem"]
    del p["parameters"]["cost_matrix"]
    record = archive("assignment", problem=p)
    view = instantiate(record, form)
    target = view["roles"]["target"]
    target = target["example"] if form == "method" else target
    assert record["unified"]["problem"]["missing_information"] == ["parameters.cost_matrix"]
    assert "cost_matrix" not in record["unified"]["problem"]["parameters"]
    def forbidden(*args):
        pytest.fail("Incomplete problem executed")
    result = run_view(view, record, FakeModel(target), solve_fn=forbidden)
    assert result["final_correct"]
    assert result["attempts"][0]["online_checks"]["state"] == "needs_information"


def test_completion_restores_executable_path():
    base = archive("assignment")
    p = deepcopy(base["unified"]["problem"])
    matrix = p["parameters"].pop("cost_matrix")
    p = receive_problem(p)
    with pytest.raises(ValidationError):
        fixture_call(p, "assignment_jv")
    p["parameters"]["cost_matrix"] = matrix
    p["missing_information"] = []
    p = receive_problem(p)
    assert solve_direct(fixture_call(p, "assignment_jv"))["objective_value"] == 265


def test_absent_fields_never_filled_with_placeholders():
    p = archive("printers")["unified"]["problem"]
    del p["parameters"]["variable_type"]
    record = archive("printers", problem=p)
    for form in ("method", "call"):
        view = instantiate(record, form)
        target = view["roles"]["target"]
        assert (target["example"] if form == "method" else target) == {"missing_fields": ["parameters.variable_type"]}


@pytest.mark.parametrize("marker", ["cost_matrix", "parameters.unknown", "parameters.tasks"])
def test_wrong_missing_paths_rejected(marker):
    p = archive("assignment")["unified"]["problem"]
    del p["parameters"]["cost_matrix"]
    p["missing_information"] = [marker]
    with pytest.raises(ValidationError):
        receive_problem(p)


def test_bad_present_data_not_hidden_by_missing_field():
    p = archive("assignment")["unified"]["problem"]
    del p["parameters"]["tasks"]
    p["parameters"]["cost_matrix"][0][0] = True
    with pytest.raises(ValidationError):
        receive_problem(p)


def test_missing_result_never_fabricated():
    with pytest.raises(ValidationError, match="actual solver return"):
        instantiate(archive("assignment"), "result")


def test_prepare_partial_handoff_skips_fixture_and_result(monkeypatch, tmp_path):
    from task2 import workflow
    entry = cases()[0]
    monkeypatch.setattr(workflow, "archive", lambda case: deepcopy(entry["record"]))
    def forbidden(*args):
        pytest.fail("Partial handoff reached fixture solver")
    monkeypatch.setattr(workflow, "solve", forbidden)
    payload = workflow.prepare(tmp_path, cases=("assignment",))
    assert len(payload["views"]) == 3 and payload["fixtures"] == []
    assert payload["unavailable_views"][0]["form"] == "result"
    assert workflow.validate(payload, tmp_path)["passed"]
    assert workflow.fault_checks(payload)["skipped_reason"] == "requires_complete_assignment_call"


def test_pending_call_report_does_not_invent_solver_result(tmp_path):
    from task2.report import render
    entry = cases()[1]
    run = run_view(entry["view"], entry["record"], FakeModel(entry["view"]["roles"]["target"]))
    result = {"cases": ["assignment"], "template_version": "1.2", "runs": [run],
              "validation": {"passed": True, "checks": []}, "fixtures": [], "created_at": "synthetic_test"}
    assert render(result, tmp_path).exists()


@pytest.mark.parametrize("case", ["assignment", "printers", "bakery", "advertising"])
def test_field_evidence_offsets_and_visibility(case):
    record = archive(case)
    public = read(ROOT / f"data/inputs/{case}.json")
    evidence = record["evidence"]["field_evidence"]
    assert "units" in evidence and "objective" in evidence and "entities" in evidence
    for items in evidence.values():
        for item in items:
            assert public[item["source_field"]][item["start"]:item["end"]] == item["quote"]
    view = instantiate(record, "understanding")
    before = messages(view)
    view["roles"]["evidence"] = {"field_evidence": "SECRET_REFERENCE"}
    view["roles"]["target"] = {"answer": 999999}
    assert messages(view) == before


def test_integer_mismatch_is_explained_with_supplement_evidence():
    record = archive("printers")
    output = deepcopy(record["unified"]["problem"])
    output["parameters"]["variable_type"] = "continuous"
    view = instantiate(record, "understanding")
    check_online(view, output)
    result = grade(view, {"output": output, "online_pass": True}, record)
    row = next(x for x in result["field_checks"] if x["path"] == "parameters.variable_type")
    assert not result["correct"] and row["status"] == "fail"
    assert row["evidence"][0]["origin"] == "demo_supplement"


def test_extraction_omission_not_reference_absence():
    record = archive("assignment")
    output = deepcopy(record["unified"]["problem"])
    del output["parameters"]["cost_matrix"]
    output = receive_problem(output)
    validate_partial(output)
    result = grade(instantiate(record, "understanding"), {"output": output, "online_pass": True}, record)
    assert not result["correct"]
    assert any(x["reason"] == "extraction_omission_or_invented_missing_marker" for x in result["field_checks"])


def test_linear_reordering_scaling_and_bounds_equivalence():
    p = archive("printers")["unified"]["problem"]
    candidate = deepcopy(p)
    candidate["parameters"]["constraints"].reverse()
    for row in candidate["parameters"]["constraints"]:
        row["coefficients"] = [3*x for x in row["coefficients"]]
        row["rhs"] *= 3
    assert problem_matches(candidate, p)


def test_unsupported_redundant_constraint_requires_review():
    p = archive("printers")["unified"]["problem"]
    candidate = deepcopy(p)
    candidate["parameters"]["constraints"].append(
        {"name": "redundant", "coefficients": [1, 1], "sense": "<=", "rhs": 100, "unit": "printers/day"})
    assert any(x["status"] == "review_required" for x in field_checks(candidate, p))
    assert not problem_matches(candidate, p)


@pytest.mark.parametrize("field,value", [("validator", "invented"), ("target", "wrong"),
                                         ("checker_version", "1.1"), ("missing_policy", "guess"),
                                         ("output_fields", ["answer"])])
def test_contract_binding_mismatch(field, value):
    spec = config("templates")
    spec["templates"]["call"][field] = value
    with pytest.raises(ValidationError):
        validate_contracts(spec)


def test_old_instances_do_not_silently_upgrade():
    view = instantiate(archive("assignment"), "call")
    view["version"] = "1.1"
    with pytest.raises(ValidationError):
        messages(view)


def test_method_knowledge_reaches_relevant_inputs_only():
    record = archive("assignment")
    method = instantiate(record, "method")["roles"]["input"]
    call = instantiate(record, "call")["roles"]["input"]
    for key in ("initialization", "core_operation", "constraint_handling", "stopping", "output"):
        assert key in method["candidates"][0] and key in call["context"]["method"]
    assert "candidates" not in instantiate(record, "understanding")["roles"]["input"]


@pytest.mark.parametrize("index", range(6))
def test_boundary_reference_contracts(index):
    entry = cases()[index]
    view = entry["view"]
    target = view["roles"]["target"]
    target = target["example"] if view["form"] == "method" else target
    result = run_view(view, entry["record"], FakeModel(target), solve_fn=solve_direct)
    assert result["final_correct"]


def test_inapplicable_candidate_is_not_implicitly_accepted():
    view = next(x["view"] for x in cases() if x["name"] == "inapplicable_candidate")
    assert {x["method_id"] for x in view["roles"]["input"]["candidates"]} == {"assignment_jv", "highs_milp"}
    bad = next(x for x in view["roles"]["input"]["candidates"] if x["method_id"] == "assignment_jv")
    with pytest.raises(ValidationError):
        check_online(view, {"method_id": bad["method_id"], "condition_ids": bad["condition_ids"], "explanation": "listed"})


def test_boundary_cli_reuses_instances_without_model(monkeypatch, tmp_path):
    from task2 import boundaries
    from task2.core import save
    import sys
    entries = cases()
    source = tmp_path / "saved.json"
    save(source, entries)
    destination = tmp_path / "replay"
    def forbidden(*args, **kwargs):
        pytest.fail("validate-only must not rebuild inputs or contact model")
    monkeypatch.setattr(boundaries, "cases", forbidden)
    monkeypatch.setattr(boundaries, "OllamaModel", forbidden)
    monkeypatch.setattr(sys, "argv", ["boundaries", "--instances", str(source), "--directory",
                                    str(destination), "--backend", "ollama", "--validate-only"])
    boundaries.main()
    assert read(destination / "instances.json") == entries
    with pytest.raises(SystemExit):
        boundaries.main()
