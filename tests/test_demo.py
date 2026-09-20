"""真实求解器集成测试 + 明确标为人工注入的接口故障测试。

FakeBackend仅用于测试机制，绝不能拿它的成绩当Qwen成绩。
"""
from copy import deepcopy
import itertools
import json
from pathlib import Path
import subprocess

import pytest

from demo.backend import LocalQwen, ModelError
from demo.evaluation import aligned, evaluate_record, feasible_and_value
from demo.harness import run_online
from demo.prompts import make_messages
from demo.prompts import PROMPT_VERSION, template_hint
from demo.solver import solve_direct, solve_isolated
from demo.validation import ValidationError, build_call, parse_model_output, validate_call, validate_problem

ROOT = Path(__file__).resolve().parents[1]
CASES = ("printers", "bakery", "advertising", "assignment", "transportation")


def read(kind, case):
    return json.loads((ROOT/"data"/kind/f"{case}.json").read_text(encoding="utf-8"))


def answers():
    return json.loads((ROOT/"data/references/answers.json").read_text(encoding="utf-8"))


class FakeBackend:
    """Synthetic fault-injection only; no actual model calls."""
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def generate(self, messages):
        self.requests.append(deepcopy(messages))
        return {"raw_text": next(self.replies), "model": "SYNTHETIC_TEST_ONLY"}


@pytest.mark.parametrize("case", CASES)
def test_structured_real_solver(case):
    problem = read("problems", case)
    record = run_online(read("inputs", case), "json", problem)
    evaluation = evaluate_record(record, problem, answers()[case])
    assert record["online_status"] == "completed"
    assert evaluation["final_verified"]


@pytest.mark.parametrize("case", ["printers", "bakery", "assignment", "transportation"])
def test_independent_witness(case):
    okay, value = feasible_and_value(read("problems", case), answers()[case]["witness"])
    assert okay
    assert value == answers()[case]["objective_value"]


def test_reference_proofs():
    # 不经过求解器的独立小规模枚举/算术证明。
    assert max(200*x+70*y for x in range(21) for y in range(31) if x+y<=35) == 5050
    assert max(5*x+3*min(int(6000-2*x), 3000-3*x) for x in range(1001)) == 9000
    costs = read("problems", "assignment")["parameters"]["cost_matrix"]
    assert min(sum(costs[w][j] for j,w in enumerate(ws)) for ws in itertools.permutations(range(5),4)) == 265
    assert 15*5000+35*9150 == 395250 > 250000
    assert 10300 - (700*2+300*1) == 8600


def test_fence_normalization_is_recorded():
    raw = json.dumps(read("problems", "printers"))
    assert parse_model_output(raw)[1] is False
    assert parse_model_output("```json\n"+raw+"\n```")[1] is True


@pytest.mark.parametrize("raw", ['{"a":NaN}', '{"a":Infinity}', '{"a":1,"a":2}',
                                    'text {"a":1}', '[]', '```json\n{}\n```\nextra'])
def test_invalid_json_rejected(raw):
    with pytest.raises(ValidationError):
        parse_model_output(raw)


@pytest.mark.parametrize("mutation", ["missing", "dimension", "nan", "infinity", "bounds", "duplicate", "type"])
def test_invalid_problem_rejected(mutation):
    p = read("problems", "printers")
    if mutation == "missing": del p["objective"]
    if mutation == "dimension": p["parameters"]["constraints"][0]["coefficients"] = [1]
    if mutation == "nan": p["parameters"]["objective_coefficients"][0] = float("nan")
    if mutation == "infinity": p["parameters"]["objective_coefficients"][0] = float("inf")
    if mutation == "bounds": p["parameters"]["lower_bounds"][0] = 21
    if mutation == "duplicate": p["entities"][1] = p["entities"][0]
    if mutation == "type": p["parameters"]["objective_coefficients"][0] = True
    with pytest.raises(ValidationError): validate_problem(p)


def test_illegal_tool():
    call = build_call(read("problems", "printers"))
    call["tool_name"] = "execute_python"
    with pytest.raises(ValidationError): validate_call(call)


def test_synthetic_repair():
    problem = read("problems", "printers")
    model = FakeBackend(['{"oops":1}', json.dumps(problem)])
    record = run_online(read("inputs", "printers"), "nl", backend=model)
    record["record_type"] = "synthetic_fault_injection"
    assert len(record["attempts"]) == 2
    assert record["attempts"][0]["feedback"]
    assert record["online_status"] == "completed"


def test_retry_cap():
    model = FakeBackend(["bad"]*3)
    record = run_online(read("inputs", "printers"), "nl", backend=model)
    assert len(record["attempts"]) == 3
    assert record["online_status"] == "validation_failed"


def test_zero_retries():
    record = run_online(read("inputs", "printers"), "nl", backend=FakeBackend(["bad"]), retries=0)
    assert len(record["attempts"]) == 1


def test_true_infeasible_does_not_rewrite_question():
    problem = read("problems", "advertising")
    model = FakeBackend([json.dumps(problem)])
    record = run_online(read("inputs", "advertising"), "nl", backend=model)
    assert len(model.requests) == 1
    assert record["attempts"][0]["solver_result"]["status"] == "infeasible"


def test_no_answer_leakage():
    public = read("inputs", "printers")
    a = make_messages(public)
    public["reference_answer"] = "SECRET_STANDARD_ANSWER_5050"
    assert make_messages(public) == a
    assert "SECRET_STANDARD_ANSWER" not in json.dumps(a)
    problem = read("problems", "printers")
    model = FakeBackend([json.dumps(problem)])
    record = run_online(public, "nl", backend=model)
    before = deepcopy(model.requests)
    answer = answers()["printers"]
    assert evaluate_record(record, problem, answer)["final_verified"]
    answer["objective_value"] = -999
    assert not evaluate_record(record, problem, answer)["final_verified"]
    assert model.requests == before  # 离线改答案不产生新的LLM调用或反馈。


def test_wrong_model_not_certified_by_coincidental_answer():
    reference = read("problems", "printers")
    altered = deepcopy(reference)
    altered["parameters"]["upper_bounds"][1] = 100  # 同样最优解，但问题不再相同。
    record = run_online(read("inputs", "printers"), "json", altered)
    assert record["attempts"][0]["solver_result"]["objective_value"] == 5050
    assert not evaluate_record(record, reference, answers()["printers"])["final_verified"]


def test_bounds_can_be_written_as_constraints():
    reference = read("problems", "printers")
    altered = deepcopy(reference)
    altered["parameters"]["upper_bounds"] = [None, None]
    altered["parameters"]["constraints"] += [
        {"name":"x","coefficients":[2,0],"sense":"<=","rhs":40,"unit":"printers/day"},
        {"name":"y","coefficients":[0,1],"sense":"<=","rhs":30,"unit":"printers/day"}]
    assert aligned(altered, reference)


def test_alternative_optimum_is_accepted():
    p = read("problems", "printers")
    p["parameters"]["objective_coefficients"] = [1,1]
    reference_answer = {"status":"optimal","objective_value":35,"human_review":"pending"}
    record = run_online(read("inputs", "printers"), "json", p)
    record["attempts"][0]["solver_result"]["values"] = [10,25]
    record["attempts"][0]["solver_result"]["objective_value"] = 35
    assert evaluate_record(record,p,reference_answer)["final_verified"]


def test_lp_path():
    p = read("problems", "printers")
    p["parameters"]["variable_type"] = "continuous"
    result = solve_direct(build_call(p))
    assert result["objective_value"] == 5050
    assert "linprog" in result["backend"]


def test_unbounded_status():
    p = read("problems", "printers")
    p["parameters"]["upper_bounds"] = [None, None]
    p["parameters"]["variable_type"] = "continuous"
    p["parameters"]["constraints"] = [{"name":"nonnegative","coefficients":[1,1],"sense":">=","rhs":0,"unit":"printers/day"}]
    assert solve_direct(build_call(p))["status"] == "unbounded"


def test_solver_timeout_is_explicit(monkeypatch):
    def timeout(*args, **kwargs): raise subprocess.TimeoutExpired("synthetic", .01)
    monkeypatch.setattr("demo.solver.subprocess.run", timeout)
    assert solve_isolated(build_call(read("problems", "printers")))["status"] == "solver_timeout"


def test_model_timeout_is_explicit(monkeypatch):
    monkeypatch.setattr("demo.backend.Path.is_file", lambda p: True)
    def timeout(*args, **kwargs): raise subprocess.TimeoutExpired("synthetic", .01)
    monkeypatch.setattr("demo.backend.subprocess.run", timeout)
    record = run_online(read("inputs", "printers"), "nl", backend=LocalQwen())
    assert record["online_status"] == "model_timeout"
    assert len(record["attempts"]) == 1


def test_missing_information_blocks_execution():
    p = read("problems", "printers")
    p["missing_information"] = ["profit coefficient is missing"]
    record = run_online(read("inputs", "printers"), "json", p)
    assert record["online_status"] == "needs_information"
    assert "tool_call" not in record["attempts"][0]


@pytest.mark.parametrize("case", CASES)
def test_v4_prompt_whitelist_and_independent_example(case):
    public = read("inputs", case)
    messages = make_messages(public)
    assert PROMPT_VERSION == "civilian-guided-fewshot-v4"
    assert len(messages) == 4
    example = json.loads(messages[2]["content"])
    validate_problem(example)
    assert example["entities"] != public["entity_order"]
    for key in ("sample_id", "source", "title_zh", "description_zh", "reference_answer"):
        public[key] = "PRIVATE_CANARY_DO_NOT_SEND"
    assert make_messages(public) == messages
    assert "PRIVATE_CANARY" not in json.dumps(messages)
    assert set(example) == {"problem_type", "objective", "entities", "units", "parameters", "missing_information"}


def test_public_hint_not_sample_id_lookup():
    public = read("inputs", "assignment")
    public["sample_id"] = "transportation"
    assert template_hint(public)["family"] == "assignment"
    public["description_en"] = "Workers and warehouses in one mixed problem."
    with pytest.raises(ValueError, match="Mixed"):
        template_hint(public)


@pytest.mark.parametrize("name", [None, True, 1, [], {}])
def test_tool_name_type_rejected(name):
    call = build_call(read("problems", "printers"))
    call["tool_name"] = name
    with pytest.raises(ValidationError):
        validate_call(call)


@pytest.mark.parametrize("bad", [True, False, float("nan"), float("inf"), -float("inf"), "1", None, 10**400])
def test_invalid_solver_values_rejected(bad):
    values = answers()["assignment"]["witness"][:]
    values[0] = bad
    assert feasible_and_value(read("problems", "assignment"), values) == (False, None)


@pytest.mark.parametrize("bad", [True, False, float("nan"), float("inf"), -float("inf"), "5050", None])
def test_invalid_reported_objective_rejected(bad):
    p = read("problems", "printers")
    attempt = {"problem": p, "solver_result": {"status":"optimal", "values":[20,15], "objective_value":bad}}
    record = {"attempts":[attempt]}
    assert not evaluate_record(record, p, answers()["printers"])["final_verified"]


@pytest.mark.parametrize("mode", ["nonzero", "invalid_json", "empty_object", "timeout", "os_error", "cpu_only", "valid"])
def test_environment_probe_status(monkeypatch, capsys, mode):
    import check_environment
    monkeypatch.setattr(check_environment, "discover_model", lambda: ("fake-python", "fake-model"))
    monkeypatch.setattr(check_environment.Path, "is_file", lambda path: True)
    monkeypatch.setattr(check_environment.importlib.metadata, "version", lambda name: "test")
    def probe(*args, **kwargs):
        if mode == "timeout": raise subprocess.TimeoutExpired("fake", 45)
        if mode == "os_error": raise OSError("Synthetic launch failure")
        stdout = {"valid": '{"torch":"test","transformers":"test","cuda":true}',
                  "cpu_only": '{"torch":"test","transformers":"test","cuda":false}',
                  "invalid_json":"not json", "empty_object":"{}"}.get(mode, "")
        return subprocess.CompletedProcess("fake", 1 if mode == "nonzero" else 0, stdout, "Synthetic probe error")
    monkeypatch.setattr(check_environment.subprocess, "run", probe)
    assert check_environment.main() == (0 if mode == "valid" else 1)
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == ("ready" if mode == "valid" else "unavailable")
