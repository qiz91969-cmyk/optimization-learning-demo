"""Online checks use visible inputs only. Hidden scoring runs after retries."""
import math
import time
from copy import deepcopy

from demo.backend import ModelError
from demo.evaluation import aligned, evaluate_attempt, feasible_and_value, _finite_number
from demo.validation import (ValidationError, parse_model_output, validate_problem,
                             object_schema, array, TEXT, NUMBER, _schema)
from .core import STATUS_ACTIONS, applicable, context, messages
from .tools import call_problem, solve
from .handoff import validate_partial
from .diagnostics import field_checks, problem_matches

METHOD_SCHEMA = object_schema({"method_id": TEXT, "condition_ids": array(TEXT),
                               "explanation": {"type": "string", "minLength": 1, "maxLength": 2000}})
RESULT_SCHEMA = object_schema({
    "status": {"enum": list(STATUS_ACTIONS)},
    "objective_value": {"anyOf": [NUMBER, {"type": "null"}]},
    "values": {"anyOf": [array(NUMBER, maximum=200), {"type": "null"}]},
    "optimality_proven": {"type": "boolean"},
    "next_action": {"enum": list(set(STATUS_ACTIONS.values()))},
    "explanation": {"type": "string", "minLength": 1, "maxLength": 2000}})


def same_problem(candidate, supplied):
    return problem_matches(candidate, supplied)


def check_online(view, output):
    """Never read roles.target/evidence, references or expected optimal values."""
    form, inputs = view["form"], view["roles"]["input"]
    if form == "understanding":
        validate_partial(output)
        if "entities" in output and output["entities"] != inputs["entity_order"]:
            raise ValidationError("Preserve supplied entity_order")
        return {"state": "needs_information" if output["missing_information"] else "validated"}
    if form == "method":
        if inputs["problem"]["missing_information"]:
            if set(output) != {"missing_fields"} or output["missing_fields"] != inputs["problem"]["missing_information"]:
                raise ValidationError("Return missing_fields; do not guess a method for incomplete input")
            return {"state": "needs_information"}
        _schema(output, METHOD_SCHEMA)
        candidates = {x["method_id"]: x for x in inputs["candidates"]}
        if output["method_id"] not in candidates or output["method_id"] not in applicable(inputs["problem"]):
            raise ValidationError("Chosen method does not satisfy the supplied applicability conditions")
        card = candidates[output["method_id"]]
        if sorted(output["condition_ids"]) != sorted(card["condition_ids"]):
            raise ValidationError("Use the condition_ids of the selected candidate card")
        return {"state": "validated", "condition_checks": output["condition_ids"],
                "explanation_review": "pending"}
    if form == "call":
        missing = inputs["problem"]["missing_information"]
        if missing:
            if set(output) != {"missing_fields"} or output["missing_fields"] != missing:
                raise ValidationError("Return missing_fields from supplied problem; do not construct a call")
            return {"state": "needs_information"}
        candidate = call_problem(output)
        ctx = inputs["context"]
        registered = context(inputs["selected_method"], inputs["problem"]["problem_type"],
                             ctx["method"]["version"], ctx["tool_version"])
        if ctx != registered or output["tool_name"] != registered["tool_name"]:
            raise ValidationError("Tool/context/method version mismatch")
        if not same_problem(candidate, inputs["problem"]):
            raise ValidationError("Arguments differ from supplied problem: check coefficients, bounds, order and units")
        return {"state": "validated", "argument_conversion": "identity with explicit entity order"}
    _schema(output, RESULT_SCHEMA)
    actual = inputs["actual_return"]
    if output["status"] != actual["status"] or output["optimality_proven"] != (actual["status"] == "optimal"):
        raise ValidationError("Interpret the actual termination status; a feasible solution is not proof of optimality")
    if output["next_action"] != STATUS_ACTIONS[actual["status"]]:
        raise ValidationError("next_action does not match the supplied status definitions")
    if output["values"] != actual.get("values") or output["objective_value"] != actual.get("objective_value"):
        raise ValidationError("Do not change the actual returned values/objective")
    if output["values"] is not None:
        okay, value = feasible_and_value(inputs["problem"], output["values"])
        if not okay or not _finite_number(output["objective_value"]) or not math.isclose(value, output["objective_value"], abs_tol=1e-6):
            raise ValidationError("Returned solution fails constraint/objective recomputation")
    elif output["objective_value"] is not None or output["status"] == "optimal":
        raise ValidationError("Missing solution cannot have an objective or an optimal status")
    return {"state": "validated", "explanation_review": "pending"}


def grade(view, attempt, record):
    """Offline evaluation is not supplied to the model's feedback loop."""
    output, form = attempt.get("output"), view["form"]
    p = record["unified"]["problem"]
    answer = record["unified"]["reference_result"]
    details = []
    if form == "understanding" and isinstance(output, dict):
        try:
            details = field_checks(output, p, record["evidence"].get("field_evidence", {}))
        except (TypeError, ValueError, KeyError, OverflowError):
            details = [{"path": "$", "status": "fail", "reason": "malformed_problem; see online error"}]
    if not attempt.get("online_pass"):
        return {"correct": False, "reason": "online_check_failed", "human_review": "pending", "field_checks": details}
    if form == "understanding":
        okay = same_problem(output, p)
        return {"correct": okay, "reason": "conservative_reference_alignment",
                "source_correspondence": "curated_reference; field-level human review pending",
                "unit_limitation": "labels checked; dimensional conversion not proven", "human_review": "pending",
                "field_checks": details, "review_required": any(x["status"] == "review_required" for x in details)}
    if form in ("method", "call") and p["missing_information"]:
        return {"correct": output == {"missing_fields": p["missing_information"]},
                "reason": "missing_request; no_tool_execution", "human_review": "pending",
                "field_checks": [{"path": "missing_fields", "actual": output.get("missing_fields"),
                                  "expected": p["missing_information"],
                                  "status": "pass" if output == {"missing_fields": p["missing_information"]} else "fail"}]}
    if form == "method":
        okay = output["method_id"] in applicable(p)
        return {"correct": okay, "reason": "method_and_condition_ids; prose not automatically certified",
                "human_review": "pending"}
    if form == "call":
        if "solver_result" not in attempt:
            return {"correct": bool(p["missing_information"]), "reason": "no_execution", "human_review": "pending"}
        result = evaluate_attempt({"problem": call_problem(output), "solver_result": attempt["solver_result"]}, p, answer)
        return {**result, "correct": result["verified_against_reference"],
                "field_checks": field_checks(call_problem(output), p, record["evidence"].get("field_evidence", {}))}
    # Independent result views use an actual fixture execution; still check its origin against the reference.
    result = evaluate_attempt({"problem": view["roles"]["input"]["problem"],
                               "solver_result": view["roles"]["input"]["actual_return"]}, p, answer)
    return {**result, "correct": result["verified_against_reference"], "explanation_review": "pending"}


def run_view(view, record, backend, retries=2, solve_fn=solve):
    if type(retries) is not int or not 0 <= retries <= 2:
        raise ValueError("Retries must be 0..2")
    prompt = messages(view)
    history = deepcopy(prompt)
    attempts = []
    start = time.perf_counter()
    for index in range(retries+1):
        attempt = {"index": index, "messages": deepcopy(history), "online_pass": False,
                   "raw_json_compliant": False, "normalized_json_compliant": False,
                   "fence_removed": False}
        tick = time.perf_counter()
        terminal_error = False
        try:
            reply = backend.generate(history)
            attempt["model_metadata"] = {k: v for k, v in reply.items() if k != "raw_text"}
            attempt["raw_text"] = reply["raw_text"]
            output, removed = parse_model_output(reply["raw_text"])
            attempt.update(output=output, fence_removed=removed,
                           raw_json_compliant=not removed, normalized_json_compliant=True)
            checks = check_online(view, output)
            attempt.update(online_pass=True, online_checks=checks)
            if view["form"] == "call" and checks["state"] == "validated":
                attempt["solver_result"] = solve_fn(output)
        except ValidationError as exc:
            attempt["error"] = str(exc)
            attempt["status"] = "validation_failed"
        except ModelError as exc:
            attempt["error"], attempt["status"] = str(exc), exc.status
            terminal_error = True
        attempt["elapsed_seconds"] = round(time.perf_counter()-tick, 3)
        attempts.append(attempt)
        if attempt["online_pass"] or terminal_error:
            break
        if index < retries:
            history += [{"role": "assistant", "content": attempt.get("raw_text", "")},
                        {"role": "user", "content": "Interface check failed: " + attempt["error"] +
                         "\nReturn a corrected JSON object. Only use the supplied input and interface."}]
    # Hidden answer files cannot influence number of retries or their messages.
    for attempt in attempts:
        attempt["evaluation"] = grade(view, attempt, record)
    return {"view_id": view["id"], "case_id": view["case_id"], "form": view["form"],
            "category": view["category"], "template_version": view["version"],
            "attempts": attempts, "first_correct": attempts[0]["evaluation"]["correct"],
            "final_correct": attempts[-1]["evaluation"]["correct"],
            "feedback_repaired": len(attempts) > 1 and attempts[-1]["evaluation"]["correct"],
            "elapsed_seconds": round(time.perf_counter()-start, 3), "human_review": "pending"}
