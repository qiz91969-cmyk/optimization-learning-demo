"""结构检查不等于读懂题目。此模块只检查数据形状、数值和接口约定。

JSON Schema负责字段、类型、枚举；下面的Python检查负责数组之间的关系。
这里不能读取reference文件，否则在线反馈可能把答案泄漏给模型。
"""
import json
import math
from copy import deepcopy

from jsonschema import Draft202012Validator


class ValidationError(ValueError):
    """可以交给模型修正的格式或接口错误；不是原题答案错误。"""


def object_schema(properties):
    """所有列出的字段必填，拒绝额外字段，避免模型悄悄改变接口。"""
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


NUMBER = {"type": "number", "minimum": -1e9, "maximum": 1e9}
TEXT = {"type": "string", "minLength": 1, "maxLength": 100}


def array(items, minimum=1, maximum=50):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


CONSTRAINT = object_schema({
    "name": TEXT, "coefficients": array(NUMBER),
    "sense": {"enum": ["<=", ">=", "="]}, "rhs": NUMBER,
    "unit": TEXT,
})
LINEAR = object_schema({
    "objective_coefficients": array(NUMBER), "constraints": array(CONSTRAINT),
    "lower_bounds": array(NUMBER),
    "upper_bounds": array({"anyOf": [NUMBER, {"type": "null"}]}),
    "variable_type": {"enum": ["continuous", "integer"]},
})
ASSIGNMENT = object_schema({"tasks": array(TEXT), "cost_matrix": array(array(NUMBER))})
TRANSPORTATION = object_schema({
    "destinations": array(TEXT), "supply": array(NUMBER), "demand": array(NUMBER),
    "cost_matrix": array(array(NUMBER)),
    "variable_type": {"enum": ["continuous", "integer"]},
})
PROBLEM_SCHEMA = object_schema({
    "problem_type": {"enum": ["linear", "assignment", "transportation"]},
    "objective": {"enum": ["maximize", "minimize"]},
    "entities": array(TEXT),
    "units": object_schema({"quantity": TEXT, "objective": TEXT}),
    "parameters": {"type": "object"},
    "missing_information": array(TEXT, minimum=0),
})
PROBLEM_SCHEMA["$schema"] = "https://json-schema.org/draft/2020-12/schema"
TOOL_NAMES = {"linear": "solve_linear", "assignment": "solve_assignment",
              "transportation": "solve_transportation"}


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_model_output(raw):
    """仅接受一个JSON对象；只允许剥去包裹整个对象的单层代码框。

    不从一大段解释里搜索花括号，不修补逗号，不改数字。
    返回normalized标志，让报告区分原生JSON与经过包装清理的JSON。
    """
    text = raw.strip()
    normalized = False
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].strip() in ("```json", "```") and lines[-1].strip() == "```":
        text = "\n".join(lines[1:-1])
        normalized = True
    try:
        def bad_constant(value):
            raise ValidationError(f"Non-finite JSON number: {value}")
        value = json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=bad_constant)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Return a single JSON object: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValidationError("The root must be a JSON object, not a list/string.")
    return value, normalized


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("NaN and infinity are not permitted.")
    if isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)


def _schema(value, schema):
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        # 限制反馈长度；返回字段位置而不是任何参考答案。
        messages = [f"{'.'.join(map(str, e.absolute_path)) or '$'}: {e.message}" for e in errors[:4]]
        raise ValidationError("; ".join(messages)[:1200])


def validate_problem(problem):
    """验证接口内部一致性，不判断模型有没有漏掉原文中的约束。"""
    _finite(problem)
    _schema(problem, PROBLEM_SCHEMA)
    kind = problem["problem_type"]
    p = problem["parameters"]
    _schema(p, {"linear": LINEAR, "assignment": ASSIGNMENT,
                "transportation": TRANSPORTATION}[kind])
    names = problem["entities"]
    if len(names) != len(set(names)):
        raise ValidationError("entities must be unique identifiers.")
    n = len(names)
    if kind == "linear":
        for key in ("objective_coefficients", "lower_bounds", "upper_bounds"):
            if len(p[key]) != n:
                raise ValidationError(f"parameters.{key}: length must equal entities length {n}.")
        for row in p["constraints"]:
            if len(row["coefficients"]) != n:
                raise ValidationError("Each constraint coefficient vector must follow entities order.")
        for lo, hi in zip(p["lower_bounds"], p["upper_bounds"]):
            if hi is not None and lo > hi:
                raise ValidationError("A lower bound exceeds its upper bound; verify the supplied bounds.")
    else:
        if problem["objective"] != "minimize":
            raise ValidationError(f"The {kind} interface supports minimum cost only.")
        columns = p["tasks"] if kind == "assignment" else p["destinations"]
        if len(columns) != len(set(columns)):
            raise ValidationError("Task/destination identifiers must be unique.")
        if n * len(columns) > 200:
            raise ValidationError("Demo limit: at most 200 decision variables.")
        if len(p["cost_matrix"]) != n or any(len(row) != len(columns) for row in p["cost_matrix"]):
            raise ValidationError("Cost matrix rows follow entities; columns follow tasks/destinations.")
        if kind == "transportation":
            if len(p["supply"]) != n or len(p["demand"]) != len(columns):
                raise ValidationError("Supply/demand lengths do not match entity/destination counts.")
            if any(x < 0 for x in p["supply"] + p["demand"]):
                raise ValidationError("Supply and demand must be nonnegative.")
            if any(x < 0 for row in p["cost_matrix"] for x in row):
                raise ValidationError("This transportation demo requires nonnegative unit costs.")
    # unit只能检查有标签。米/千米是否混用必须靠来源核对，不能声称已自动理解。
    return problem


def build_call(problem):
    """确定性路由，只包装模型填写的参数，不选择复杂算法，也不补答案。"""
    validate_problem(problem)
    if problem["missing_information"]:
        raise ValidationError("Missing information: " + ", ".join(problem["missing_information"]))
    return {"tool_name": TOOL_NAMES[problem["problem_type"]],
            "arguments": deepcopy({k: problem[k] for k in ("objective", "entities", "units", "parameters")})}


def validate_call(call):
    if not isinstance(call, dict) or set(call) != {"tool_name", "arguments"}:
        raise ValidationError("Tool call requires exactly tool_name and arguments.")
    reverse = {v: k for k, v in TOOL_NAMES.items()}
    if not isinstance(call["tool_name"], str) or call["tool_name"] not in reverse:
        raise ValidationError("Tool is not registered in the fixed allowlist.")
    args = call["arguments"]
    if not isinstance(args, dict) or set(args) != {"objective", "entities", "units", "parameters"}:
        raise ValidationError("Unexpected tool argument fields.")
    problem = {"problem_type": reverse[call["tool_name"]], **deepcopy(args), "missing_information": []}
    return validate_problem(problem)
