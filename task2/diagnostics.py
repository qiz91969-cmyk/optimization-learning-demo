"""Offline, field-level diagnostics. Never send reference values back as feedback."""
from demo.evaluation import _linear_signature


def _unit_rows(problem):
    """Pair each normalized inequality with its own physical-unit label."""
    p = problem["parameters"]
    rows = []

    def add(coefficients, rhs, unit):
        scale = max(map(abs, coefficients)) or 1
        key = tuple(round(x / scale, 8) for x in list(coefficients) + [rhs])
        rows.append((key, unit))

    for row in p["constraints"]:
        if row["sense"] in ("<=", "="):
            add(row["coefficients"], row["rhs"], row["unit"])
        if row["sense"] in (">=", "="):
            add([-x for x in row["coefficients"]], -row["rhs"], row["unit"])
    n = len(p["objective_coefficients"])
    for i, (lo, hi) in enumerate(zip(p["lower_bounds"], p["upper_bounds"])):
        row = [0] * n
        row[i] = -1
        add(row, -lo, problem["units"]["quantity"])
        if hi is not None:
            row = [0] * n
            row[i] = 1
            add(row, hi, problem["units"]["quantity"])
    return rows


def _units_match(candidate, reference):
    expected = {}
    for key, unit in _unit_rows(reference):
        expected.setdefault(key, set()).add(unit)
    # Unknown rows and unsupported conversions require review, not guessed aliases.
    return all(unit in expected.get(key, set()) for key, unit in _unit_rows(candidate))


def field_checks(candidate, reference, evidence=None):
    evidence = evidence or {}
    rows = []

    def check(group, path, actual, expected, status=None, reason=None):
        status = status or ("pass" if actual == expected else "fail")
        rows.append({"group": group, "path": path, "status": status,
                     "actual": actual, "expected": expected,
                     "reason": reason or ("matches_reference" if status == "pass" else "field_mismatch"),
                     "evidence": evidence.get(path, []), "human_review": "pending"})

    for group, key in (("category", "problem_type"), ("entities", "entities"),
                       ("objective", "objective"), ("units", "units"),
                       ("missing", "missing_information")):
        reason = None
        if key == "missing_information" and candidate.get(key) != reference.get(key):
            reason = "extraction_omission_or_invented_missing_marker" if not reference.get(key) else "missing_fields_mismatch"
        check(group, key, candidate.get(key), reference.get(key), reason=reason)
    a, b = candidate.get("parameters", {}), reference.get("parameters", {})
    if not isinstance(a, dict):
        check("parameters", "parameters", a, b)
        return rows
    keys = set(a) | set(b)
    for key in sorted(keys - {"constraints", "lower_bounds", "upper_bounds"}):
        group = "variable_type" if key == "variable_type" else ("entities" if key in ("tasks", "destinations") else "numbers")
        check(group, "parameters." + key, a.get(key), b.get(key))
    if reference.get("problem_type") == "linear":
        try:
            same = _linear_signature(a) == _linear_signature(b)
            check("constraints", "parameters.constraints", a.get("constraints"), b.get("constraints"),
                  "pass" if same else "review_required",
                  "equivalent_under_registered_linear_rules" if same else "not_equivalent_under_supported_rules; manual_review_required")
            units = [x["unit"] for x in a["constraints"]]
            check("units", "parameters.constraints.unit", units,
                  [x["unit"] for x in b["constraints"]],
                  "pass" if _units_match(candidate, reference) else "review_required",
                  "unit_labels_matched_per_normalized_constraint_and_bound; no_conversion_proof")
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            for key in ("constraints", "lower_bounds", "upper_bounds"):
                check("constraints", "parameters." + key, a.get(key), b.get(key))
    return rows


def problem_matches(candidate, reference):
    return all(x["status"] == "pass" for x in field_checks(candidate, reference))
