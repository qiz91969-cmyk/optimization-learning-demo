"""Partial handoffs are allowed; executable problems still use the strict validator."""
from copy import deepcopy

from demo.validation import (PROBLEM_SCHEMA, LINEAR, ASSIGNMENT, TRANSPORTATION,
                             ValidationError, _schema, _finite, validate_problem)

PARAMETERS = {"linear": LINEAR, "assignment": ASSIGNMENT, "transportation": TRANSPORTATION}


def missing_paths(problem):
    if not isinstance(problem, dict) or problem.get("problem_type") not in PARAMETERS:
        raise ValidationError("Handoff needs a supported problem_type for routing; no type is guessed")
    missing = []
    for key in PROBLEM_SCHEMA["required"]:
        if key not in problem and key != "missing_information":
            missing.append(key)
    for group, schema in (("parameters", PARAMETERS[problem["problem_type"]]),
                          ("units", PROBLEM_SCHEMA["properties"]["units"])):
        if group in problem and isinstance(problem[group], dict):
            missing.extend(group + "." + k for k in schema["required"] if k not in problem[group])
    return sorted(missing)


def receive_problem(problem):
    """Normalize absence markers only; never populate a missing numerical field."""
    p = deepcopy(problem)
    absent = missing_paths(p)
    declared = p.get("missing_information", [])
    if not isinstance(declared, list) or any(not isinstance(x, str) for x in declared):
        raise ValidationError("missing_information must contain field paths")
    if any(x not in absent for x in declared):
        raise ValidationError("Missing marker names a present or unknown field")
    p["missing_information"] = absent
    validate_partial(p)
    return p


def validate_partial(problem):
    absent = missing_paths(problem)
    declared = problem.get("missing_information")
    if isinstance(declared, list):
        for path in declared:
            if not isinstance(path, str):
                raise ValidationError("missing_information must contain field paths")
            current = problem
            for part in path.split("."):
                if not isinstance(current, dict) or part not in current:
                    break
                current = current[part]
            else:
                raise ValidationError(path + " is marked missing but still present; omit this field, not a zero or placeholder array")
    if problem.get("missing_information") != absent:
        raise ValidationError("missing_information must list exactly the absent field paths, sorted")
    if not absent:
        return validate_problem(problem)
    _finite(problem)
    schema = deepcopy(PROBLEM_SCHEMA)
    schema["properties"]["parameters"] = deepcopy(PARAMETERS[problem["problem_type"]])
    for path in absent:
        parts = path.split(".")
        parent = schema
        for part in parts[:-1]:
            parent = parent["properties"][part]
        parent["required"].remove(parts[-1])
    _schema(problem, schema)
    # Check all relationships whose operands are present, without dummy values.
    names = problem.get("entities")
    params = problem.get("parameters", {})
    if names is not None and len(names) != len(set(names)):
        raise ValidationError("entities must be unique")
    columns = params.get("tasks", params.get("destinations"))
    if columns is not None and len(columns) != len(set(columns)):
        raise ValidationError("Task/destination identifiers must be unique")
    if names is not None:
        n = len(names)
        for key in ("objective_coefficients", "lower_bounds", "upper_bounds", "supply"):
            if key in params and len(params[key]) != n:
                raise ValidationError("parameters." + key + ": length differs from entities")
        if any(len(row["coefficients"]) != n for row in params.get("constraints", [])):
            raise ValidationError("Constraint dimensions differ from entities")
        if "cost_matrix" in params and len(params["cost_matrix"]) != n:
            raise ValidationError("Matrix row count differs from entities")
    if columns is not None and "cost_matrix" in params:
        if any(len(row) != len(columns) for row in params["cost_matrix"]):
            raise ValidationError("Matrix column count differs from tasks/destinations")
    if problem["problem_type"] != "linear" and problem.get("objective", "minimize") != "minimize":
        raise ValidationError("Assignment/transportation require minimize")
    if "lower_bounds" in params and "upper_bounds" in params:
        if len(params["lower_bounds"]) != len(params["upper_bounds"]) or any(
            hi is not None and lo > hi for lo, hi in zip(params["lower_bounds"], params["upper_bounds"])):
            raise ValidationError("Inconsistent variable bounds")
    return problem
