"""Versioned handoff adapter and four views of three training-template classes.

Public inputs, references and evidence are deliberately stored separately from
the prompt whitelist. Changing a reference must never alter model messages.
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from demo.validation import (ASSIGNMENT, LINEAR, PROBLEM_SCHEMA, ValidationError,
                             validate_problem)

ROOT = Path(__file__).resolve().parents[1]
CASES = ("assignment", "printers", "bakery", "advertising")
FORMS = ("understanding", "method", "call", "result")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                   allow_nan=False).encode()).hexdigest()


def config(name):
    return read(ROOT / "configs/task2" / (name + ".json"))


def at_path(value, path):
    for key in path.split("."):
        value = value[key]
    return value


def map_fields(bundle, specification=None):
    specification = specification or config("mappings")
    result, operations = {}, []
    types = {"string": str, "object": dict, "array": list}
    for item in specification["fields"]:
        try:
            value = at_path(bundle, item["source"])
        except KeyError as exc:
            if item["required"]:
                raise ValidationError("Missing handoff field: " + item["source"]) from exc
            value = None
        if item["conversion"] != "identity":
            raise ValidationError("Unregistered mapping conversion")
        if value is not None and not isinstance(value, types[item["type"]]):
            raise ValidationError("Wrong handoff type: " + item["source"])
        result[item["target"]] = deepcopy(value)
        operations.append({**item, "value_hash": digest(value)})
    return result, operations


def applicable(problem):
    validate_problem(problem)
    if problem["problem_type"] == "assignment":
        return ["assignment_jv", "highs_milp"]
    if problem["problem_type"] == "linear" and problem["parameters"]["variable_type"] == "integer":
        return ["highs_milp"]
    return []


def context(method_id, problem_type, method_version="1.0", tool_version="1.0"):
    """Retrieval key has no case ID, target, reference call or answer."""
    cards = config("methods")
    card = next((x for x in cards["methods"] if x["method_id"] == method_id), None)
    if card is None or card["version"] != method_version or card["tool_version"] != tool_version:
        raise ValidationError("Method/tool version not registered")
    if problem_type not in card["tool_names"]:
        raise ValidationError("Method not registered for this problem class")
    return {"context_version": cards["context_version"], "method": {
                k: deepcopy(card[k]) for k in ("method_id", "version", "name", "condition_ids", "conditions")},
            "tool_name": card["tool_names"][problem_type], "tool_version": tool_version,
            "arguments_fields": ["objective", "entities", "units", "parameters"],
            "argument_rules": "Copy these four fields from problem exactly. objective is a string; entities is an array; units and parameters are objects. No problem_type or missing_information inside arguments.",
            "ordering": "Preserve entities order; matrix columns follow tasks; output values are row-major.",
            "limits": {"solver_seconds": 10, "process_seconds": 20}}


def fixture_call(problem, method_id):
    ctx = context(method_id, problem["problem_type"])
    return {"tool_name": ctx["tool_name"], "arguments": {
        k: deepcopy(problem[k]) for k in ctx["arguments_fields"]}}


STATUS_ACTIONS = {"optimal": "report_solution", "infeasible": "review_constraints",
                  "unbounded": "review_bounds", "limit_reached": "consider_more_time",
                  "solver_timeout": "consider_more_time", "solver_error": "inspect_tool_error"}


def interpretation(result):
    return {"status": result["status"], "objective_value": result.get("objective_value"),
            "values": result.get("values"), "optimality_proven": result["status"] == "optimal",
            "next_action": STATUS_ACTIONS[result["status"]],
            "explanation": "Interpret only the observed termination status; feasibility and optimality differ."}


def archive(case):
    if case not in CASES:
        raise ValidationError("Unknown demo case")
    bundle = {"public": read(ROOT / f"data/inputs/{case}.json"),
              "problem": read(ROOT / f"data/problems/{case}.json"),
              "answer": read(ROOT / "data/references/answers.json")[case]}
    methods = [m for m in config("methods")["methods"] if m["method_id"] in applicable(bundle["problem"])]
    bundle["materials"] = {"method_knowledge": methods,
                           "algorithm_skeletons": [m["skeleton_id"] for m in methods],
                           "tool_contracts": [context(m["method_id"], bundle["problem"]["problem_type"]) for m in methods]}
    unified, operations = map_fields(bundle)
    validate_problem(unified["problem"])
    return {"id": case, "version": "task2-handoff-1.0", "unified": unified,
            "scenario": {"domain": "public_civilian_teaching", "time_urgency": None,
                         "evidence": "Public statement and explicit demo modeling notes only"},
            "process": operations,
            "evidence": {"source": unified["source"], "public_hash": digest(bundle["public"]),
                         "problem_hash": digest(bundle["problem"]), "human_review": "pending",
                         "construction": "Manually curated temporary handoff; not an output of task one",
                         "supplements": bundle["public"]["modeling_notes_en"],
                         "missing": ["project scenario classification", "upstream metamodel release"],
                         "field_provenance": {
                             "task_text": "public.description_en (verbatim from local attributed input)",
                             "problem": "existing curated data/problems; source alignment pending human review",
                             "reference_result": "independent certificate in data/references/answers.json"}}}


def instantiate(record, form, actual_return=None, problem=None, method_id=None):
    spec = config("templates")
    definition = spec["templates"][form]
    u = record["unified"]
    p = deepcopy(problem if problem is not None else u["problem"])
    allowed = applicable(p)
    selected = method_id or allowed[0]
    # Only the empty shape goes to the model; numerical schema bounds remain in validators.
    parameters = ({"tasks": [], "cost_matrix": []} if p["problem_type"] == "assignment" else
                  {"objective_coefficients": [], "constraints": [], "lower_bounds": [],
                   "upper_bounds": [], "variable_type": ""})
    contract = {"empty_output": {"problem_type": "", "objective": "", "entities": [],
                                  "units": {"quantity": "", "objective": ""},
                                  "parameters": parameters, "missing_information": []},
                "rules": ["problem_type: assignment for workers/tasks, otherwise linear for production/advertising.",
                          "objective: minimize or maximize; entities are identifier strings.",
                          "Assignment: tasks are identifiers; cost_matrix rows follow entities and columns follow tasks.",
                          "Linear: each constraint is {name: string, coefficients: number array, sense: <= or >= or =, rhs: number, unit: string}.",
                          "Linear: all vectors follow entities; use null for an absent upper bound; variable_type is integer or continuous."]}
    values = {"task_text": u["task_text"], "supplement": u["supplement"],
              "entity_order": u["entity_order"], "field_contract": contract,
              "problem": p, "scenario": record["scenario"],
              "requirements": {"objective": p["objective"], "need": "exact optimum or explicit termination status"},
              "candidates": [{k: deepcopy(m[k]) for k in ("method_id", "version", "name", "condition_ids", "conditions")}
                             for m in config("methods")["methods"] if m["method_id"] in allowed],
              "selected_method": selected, "context": context(selected, p["problem_type"]),
              "actual_return": actual_return, "status_definitions": STATUS_ACTIONS}
    if form == "result" and actual_return is None:
        raise ValidationError("Result template needs an actual solver return")
    targets = {"understanding": p,
               "method": {"accepted_method_ids": allowed, "example": {
                   "method_id": selected, "condition_ids": context(selected, p["problem_type"])["method"]["condition_ids"],
                   "explanation": "Applicable to the supplied model; alternatives are also accepted."}},
               "call": fixture_call(p, selected),
               "result": interpretation(actual_return) if actual_return else None}
    return {"id": record["id"] + ":" + form, "case_id": record["id"], "form": form,
            "category": definition["category"], "version": spec["version"],
            "definition_hash": digest(definition),
            "roles": {"input": {k: deepcopy(values[k]) for k in definition["input_fields"]},
                      "process": {"mapping_version": config("mappings")["version"],
                                  "operations": record["process"],
                                  "method_rules_version": config("methods")["version"]},
                      "target": targets[form],
                      "evidence": deepcopy(record["evidence"])},
            "human_review": "pending", "usage": "development_demo_not_training_ready"}


def messages(view):
    """Strict projection: never serialize the entire instance into a prompt."""
    spec = config("templates")
    definition = spec["templates"][view["form"]]
    if view["version"] != spec["version"] or view["definition_hash"] != digest(definition):
        raise ValidationError("Template version/hash mismatch; instantiate again")
    inputs = view["roles"]["input"]
    if set(inputs) != set(definition["input_fields"]):
        raise ValidationError("Input whitelist mismatch")
    return [{"role": "system", "content": definition["instruction"]},
            {"role": "user", "content": json.dumps({k: inputs[k] for k in definition["input_fields"]},
                                                     ensure_ascii=False, allow_nan=False)}]


def export_views(views, directory):
    """Teaching exports include targets; runtime does not consume these files."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    instruction_rows, chat_rows = [], []
    for view in views:
        prompt = messages(view)
        target = view["roles"]["target"]
        target = target["example"] if view["form"] == "method" else target
        metadata = {"id": view["id"], "human_review": "pending", "usage": view["usage"]}
        instruction_rows.append({**metadata, "instruction": prompt[0]["content"],
                                 "input": json.loads(prompt[1]["content"]), "target": target})
        chat_rows.append({**metadata, "messages": prompt + [
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)}]})
    for name, rows in (("instruction.jsonl", instruction_rows), ("messages.jsonl", chat_rows)):
        (directory / name).write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                                             for row in rows), encoding="utf-8")
    return check_exports(directory, views)


def check_exports(directory, views):
    directory = Path(directory)
    instructions = [json.loads(x) for x in (directory / "instruction.jsonl").read_text(encoding="utf-8").splitlines()]
    chats = [json.loads(x) for x in (directory / "messages.jsonl").read_text(encoding="utf-8").splitlines()]
    if not len(instructions) == len(chats) == len(views):
        raise ValidationError("Export row count mismatch")
    for view, row, chat in zip(views, instructions, chats):
        prompt = messages(view)
        target = view["roles"]["target"]
        target = target["example"] if view["form"] == "method" else target
        if (row["id"] != view["id"] or chat["id"] != view["id"] or
                row["instruction"] != prompt[0]["content"] or row["input"] != json.loads(prompt[1]["content"]) or
                row["target"] != target or chat["messages"][:2] != prompt or
                len(chat["messages"]) != 3 or chat["messages"][2]["role"] != "assistant" or
                json.loads(chat["messages"][2]["content"]) != target):
            raise ValidationError("Export field/value/role roundtrip mismatch")
    return {"passed": True, "rows_per_format": len(views), "formats": 2, "human_review": "pending"}
