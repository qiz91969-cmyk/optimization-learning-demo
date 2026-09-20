"""独立离线评价：不能把本模块结果接回LLM的重试提示。

校验使用参考问题直接逐条计算，不调用solver.compile_model，避免同一矩阵
构造错误同时污染求解与检查。结构对齐是保守检查，不是数学等价证明器。
"""
import math

TOL = 1e-6


def _finite_number(value):
    # bool是Python的int子类，但不是本接口允许的求解数值。
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def feasible_and_value(reference, values):
    """把实际返回的数代回参考题，而不是代回模型自己写的约束。"""
    p = reference["parameters"]
    kind = reference["problem_type"]
    n = len(reference["entities"])
    expected = n if kind == "linear" else n * len(p["tasks"] if kind == "assignment" else p["destinations"])
    if not isinstance(values, list) or len(values) != expected or any(not _finite_number(x) for x in values):
        return False, None
    integral = kind == "assignment" or p.get("variable_type") == "integer"
    if integral and any(abs(x-round(x)) > TOL for x in values):
        return False, None
    if kind == "linear":
        okay = all(x >= lo-TOL and (hi is None or x <= hi+TOL)
                   for x, lo, hi in zip(values, p["lower_bounds"], p["upper_bounds"]))
        for row in p["constraints"]:
            lhs = sum(a*x for a, x in zip(row["coefficients"], values))
            rhs = row["rhs"]
            okay &= {"<=": lhs <= rhs+TOL, ">=": lhs >= rhs-TOL, "=": abs(lhs-rhs) <= TOL}[row["sense"]]
        value = sum(a*x for a, x in zip(p["objective_coefficients"], values))
    else:
        m = len(p["tasks"] if kind == "assignment" else p["destinations"])
        matrix = [values[i*m:(i+1)*m] for i in range(n)]
        okay = all(x >= -TOL for x in values)
        if kind == "assignment":
            okay &= all(sum(row) <= 1+TOL for row in matrix)
            okay &= all(abs(sum(row[j] for row in matrix)-1) <= TOL for j in range(m))
        else:
            okay &= all(sum(row) <= p["supply"][i]+TOL for i, row in enumerate(matrix))
            okay &= all(sum(row[j] for row in matrix) >= p["demand"][j]-TOL for j in range(m))
        value = sum(matrix[i][j]*p["cost_matrix"][i][j] for i in range(n) for j in range(m))
    return bool(okay), value


def _linear_signature(p):
    """统一<=方向、正比例缩放、上下界位置和排列；不消除一般冗余约束。"""
    n = len(p["objective_coefficients"])
    rows = []
    for constraint in p["constraints"]:
        row = list(constraint["coefficients"])
        rhs = constraint["rhs"]
        if constraint["sense"] in ("<=", "="):
            rows.append(row+[rhs])
        if constraint["sense"] in (">=", "="):
            rows.append([-v for v in row]+[-rhs])
    for i, (lo, hi) in enumerate(zip(p["lower_bounds"], p["upper_bounds"])):
        row = [0]*n; row[i] = -1
        rows.append(row+[-lo])
        if hi is not None:
            row = [0]*n; row[i] = 1
            rows.append(row+[hi])
    return sorted(set(tuple(round(x/(max(map(abs, r[:-1])) or 1), 8) for x in r) for r in rows))


def aligned(candidate, reference):
    """不按整个JSON字符串打分；忽略约束名字，允许边界写到约束中。"""
    if any(candidate[k] != reference[k] for k in ("problem_type", "objective", "entities")):
        return False
    a, b = candidate["parameters"], reference["parameters"]
    if candidate["problem_type"] == "linear":
        return (a["objective_coefficients"] == b["objective_coefficients"] and
                a["variable_type"] == b["variable_type"] and _linear_signature(a) == _linear_signature(b))
    return a == b


def evaluate_attempt(attempt, reference, answer):
    result = attempt.get("solver_result")
    if result is None:
        return {"verified_against_reference": False, "reason": "No solver result", "reference_alignment": None}
    candidate = attempt["problem"]
    alignment = aligned(candidate, reference)
    units_match = candidate["units"] == reference["units"]
    status_match = result["status"] == answer["status"]
    feasibility, objective_match, recomputed = None, None, None
    if result["status"] == "optimal":
        feasibility, recomputed = feasible_and_value(reference, result.get("values"))
        expected = answer["objective_value"]
        reported = result.get("objective_value")
        objective_match = (_finite_number(expected) and _finite_number(recomputed) and _finite_number(reported) and
                           math.isclose(recomputed, expected, rel_tol=1e-7, abs_tol=TOL) and
                           math.isclose(recomputed, reported, rel_tol=1e-7, abs_tol=TOL))
    verified = bool(alignment and units_match and status_match and
                    (answer["status"] == "infeasible" or (feasibility and objective_match)))
    return {"verified_against_reference": verified, "reference_alignment": alignment,
            "unit_labels_match": units_match, "status_match": status_match,
            "original_constraints_satisfied": feasibility, "objective_match": objective_match,
            "recomputed_reference_objective": recomputed, "human_review": answer["human_review"],
            "note": "Reference alignment is conservative, not a general equivalence proof. Unit labels are not a unit-conversion proof."}


def evaluate_record(record, reference, answer):
    """必须在run_online返回后调用；这一步是考试评分，不是模型输入。"""
    evaluations = [evaluate_attempt(a, reference, answer) for a in record["attempts"]]
    return {"attempt_evaluations": evaluations,
            "first_pass_verified": evaluations[0]["verified_against_reference"] if evaluations else False,
            "final_verified": evaluations[-1]["verified_against_reference"] if evaluations else False}
