"""受控求解工具：将已验证参数转成SciPy矩阵，不执行LLM生成代码。"""
import json
import subprocess
import sys
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp

from .validation import validate_call


def compile_model(problem):
    """只实现三种教材模型。返回c、矩阵A、约束上下界、变量界及整数标志。

    SciPy默认最小化；最大化在调用前把目标系数乘-1，报告时再还原。
    矩阵展开顺序是行优先，例如配送[A->1,A->2,...,B->1,...]。
    """
    p = problem["parameters"]
    kind = problem["problem_type"]
    if kind == "linear":
        c = np.array(p["objective_coefficients"], dtype=float)
        A = np.array([r["coefficients"] for r in p["constraints"]], dtype=float)
        lower = [r["rhs"] if r["sense"] in (">=", "=") else -np.inf for r in p["constraints"]]
        upper = [r["rhs"] if r["sense"] in ("<=", "=") else np.inf for r in p["constraints"]]
        lb = p["lower_bounds"]
        ub = [np.inf if v is None else v for v in p["upper_bounds"]]
        integral = p["variable_type"] == "integer"
    else:
        costs = np.array(p["cost_matrix"], dtype=float)
        rows, cols = costs.shape
        c = costs.ravel()
        A = []
        lower, upper = [], []
        for i in range(rows):
            row = np.zeros((rows, cols))
            row[i, :] = 1
            A.append(row.ravel())
            lower.append(-np.inf)
            upper.append(1 if kind == "assignment" else p["supply"][i])
        for j in range(cols):
            row = np.zeros((rows, cols))
            row[:, j] = 1
            A.append(row.ravel())
            lower.append(1 if kind == "assignment" else p["demand"][j])
            upper.append(1 if kind == "assignment" else np.inf)
        A = np.array(A)
        lb = np.zeros(len(c))
        ub = np.ones(len(c)) if kind == "assignment" else np.full(len(c), np.inf)
        integral = kind == "assignment" or p["variable_type"] == "integer"
    return c, np.array(A), np.array(lower), np.array(upper), np.array(lb), np.array(ub), integral


def solve_direct(call, time_limit=10.0):
    """在子进程中调用真实求解器；返回状态而不是假设始终存在最优解。"""
    problem = validate_call(call)
    c, A, lower, upper, lb, ub, integer = compile_model(problem)
    sign = -1 if problem["objective"] == "maximize" else 1
    start = time.perf_counter()
    if integer:
        result = milp(sign * c, integrality=np.ones(len(c)), bounds=Bounds(lb, ub),
                      constraints=LinearConstraint(A, lower, upper),
                      options={"time_limit": float(time_limit), "mip_rel_gap": 0.0})
        backend = "scipy.optimize.milp/HiGHS"
    else:
        # 把一般约束 lower <= A*x <= upper 拆为linprog的 <= 和 = 两类。
        eq, beq, le, ble = [], [], [], []
        for row, lo, hi in zip(A, lower, upper):
            if lo == hi:
                eq.append(row); beq.append(hi)
            else:
                if np.isfinite(hi):
                    le.append(row); ble.append(hi)
                if np.isfinite(lo):
                    le.append(-row); ble.append(-lo)
        result = linprog(sign * c, A_ub=np.array(le) if le else None,
                         b_ub=np.array(ble) if ble else None,
                         A_eq=np.array(eq) if eq else None, b_eq=np.array(beq) if beq else None,
                         bounds=list(zip(lb, ub)), method="highs",
                         options={"time_limit": float(time_limit)})
        backend = "scipy.optimize.linprog/HiGHS"
    status = {0: "optimal", 1: "limit_reached", 2: "infeasible", 3: "unbounded"}.get(result.status, "solver_error")
    # 超时可能带候选解，但本Demo不把候选解伪装成最优解。
    return {"status": status, "values": result.x.tolist() if status == "optimal" else None,
            "objective_value": float(c @ result.x) if status == "optimal" else None,
            "backend": backend, "message": str(result.message),
            "elapsed_seconds": round(time.perf_counter() - start, 4)}


def solve_isolated(call, timeout=20.0, solver_time_limit=10.0):
    """外层硬超时保证求解库卡住也会停止；Python -m入口仅接受白名单调用。"""
    validate_call(call)
    try:
        process = subprocess.run([sys.executable, "-m", "demo.solver"],
                                 input=json.dumps({"call": call, "time_limit": solver_time_limit}),
                                 text=True, encoding="utf-8", capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "solver_timeout", "values": None, "objective_value": None}
    if process.returncode:
        return {"status": "solver_error", "values": None, "objective_value": None,
                "message": process.stderr[-2000:]}
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError:
        return {"status": "solver_error", "values": None, "objective_value": None,
                "message": "Worker did not return JSON."}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(solve_direct(request["call"], request["time_limit"]), allow_nan=False))
