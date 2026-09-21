"""Versioned template-to-checker bindings, validated before any model request."""
from demo.validation import ValidationError


CONTRACTS = {
    "understanding": ("problem", "problem_reference_alignment", "partial_problem"),
    "method": ("acceptable_methods", "method_conditions", "missing_fields"),
    "call": ("reference_call", "interface_and_execution", "missing_fields"),
    "result": ("result_interpretation", "return_and_recomputation", "not_instantiable"),
}
OUTPUT_FIELDS = {
    "understanding": ["problem_type", "objective", "entities", "units", "parameters", "missing_information"],
    "method": ["method_id", "condition_ids", "explanation"],
    "call": ["tool_name", "arguments"],
    "result": ["status", "objective_value", "values", "optimality_proven", "next_action", "explanation"],
}


def validate_contracts(spec):
    if spec.get("version") != "1.3" or set(spec.get("templates", {})) != set(CONTRACTS):
        raise ValidationError("Unsupported template contract version or forms; re-instantiate")
    for form, (target, validator, missing) in CONTRACTS.items():
        item = spec["templates"][form]
        if (item.get("target"), item.get("validator"), item.get("missing_policy")) != (target, validator, missing):
            raise ValidationError("Template/checker binding mismatch: " + form)
        if item.get("checker_version") != "1.3" or not item.get("output_contract") or not item.get("applicability"):
            raise ValidationError("Incomplete template contract: " + form)
        if item.get("output_fields") != OUTPUT_FIELDS[form]:
            raise ValidationError("Output field contract/checker mismatch: " + form)
        fields = item.get("input_fields", [])
        if len(fields) != len(set(fields)) or not fields:
            raise ValidationError("Invalid input whitelist: " + form)
    return spec
