from copy import deepcopy

from task2.compare import comparison, generate, message_differences
from task2.core import CASES, FORMS, save


def fixture():
    return {"config_hashes": {"templates": "same"}, "runs": [
        {"view_id": c+":"+f, "first_correct": True, "final_correct": True,
         "feedback_repaired": False, "elapsed_seconds": 1,
         "attempts": [{"messages": [{"role": "user", "content": c+f}],
                       "raw_json_compliant": True, "online_pass": True, "raw_text": "{}"}]}
        for c in CASES for f in FORMS]}


def test_compare_requires_exact_prompts():
    left = fixture()
    right = deepcopy(left)
    assert comparison(left, right)["all_first_prompts_equal"]
    right["runs"][0]["attempts"][0]["messages"][0]["content"] = "changed"
    assert not comparison(left, right)["all_first_prompts_equal"]


def test_missing_runs_not_counted_as_regressions():
    left = fixture()
    right = deepcopy(left)
    right["runs"].pop()
    result = comparison(left, right)
    assert not result["complete_16_each"] and not result["regressed"]


def test_identifies_fixture_timing_not_solution_change():
    a = [{"role": "system", "content": "same"}, {"role": "user", "content": '{"actual_return":{"elapsed_seconds":1,"objective_value":265}}'}]
    b = deepcopy(a)
    b[1]["content"] = '{"actual_return":{"elapsed_seconds":2,"objective_value":265}}'
    assert message_differences(a, b) == ["messages[1].content.actual_return.elapsed_seconds"]
    b[1]["content"] = '{"actual_return":{"elapsed_seconds":2,"objective_value":266}}'
    assert "messages[1].content.actual_return.objective_value" in message_differences(a, b)


def test_comparison_escapes_output_and_preserves_records(tmp_path):
    left, right = fixture(), fixture()
    right["runs"][2]["attempts"][0]["raw_text"] = "<script>alert(1)</script>"
    save(tmp_path / "a.json", left)
    save(tmp_path / "b.json", right)
    before = (tmp_path / "b.json").read_bytes()
    report = generate(tmp_path / "a.json", tmp_path / "b.json", tmp_path / "report")
    assert "<script>alert(1)</script>" not in report.read_text(encoding="utf-8")
    assert (tmp_path / "b.json").read_bytes() == before
