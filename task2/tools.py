"""Small registered tools; fixed Python implementation, never generated code."""
import json
import subprocess
import sys
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linear_sum_assignment, milp

from demo.evaluation import feasible_and_value
from demo.solver import compile_model
from demo.validation import ValidationError, validate_call
from .core import ROOT


def call_problem(call):
    if not isinstance(call, dict) or set(call) != {"tool_name", "arguments"}:
        raise ValidationError("Expected tool_name and arguments only")
    name = call["tool_name"]
    if not isinstance(name, str):
        raise ValidationError("Tool name must be a registered string")
    if name == "solve_assignment_jv":
        return validate_call({**call, "tool_name": "solve_assignment"})
    if name not in ("solve_assignment", "solve_linear"):
        raise ValidationError("Tool is not registered for task two")
    p = validate_call(call)
    if p["problem_type"] == "linear" and p["parameters"]["variable_type"] != "integer":
        raise ValidationError("This method version expects integer decisions")
    return p


def solve_direct(call, time_limit=10):
    p = call_problem(call)
    start = time.perf_counter()
    if call["tool_name"] == "solve_assignment_jv":
        costs = np.asarray(p["parameters"]["cost_matrix"], dtype=float)
        if costs.shape[0] < costs.shape[1]:
            status, values, value = "infeasible", None, None
        else:
            row, col = linear_sum_assignment(costs)
            matrix = np.zeros_like(costs)
            matrix[row, col] = 1
            status, values, value = "optimal", matrix.ravel().tolist(), float(costs[row, col].sum())
        backend = "scipy.optimize.linear_sum_assignment/modified Jonker-Volgenant"
        detail = "Each task exactly once; each worker at most once"
    else:
        c, A, lower, upper, lb, ub, integer = compile_model(p)
        sign = -1 if p["objective"] == "maximize" else 1
        result = milp(sign*c, integrality=np.ones(len(c)) if integer else np.zeros(len(c)),
                      bounds=Bounds(lb, ub), constraints=LinearConstraint(A, lower, upper),
                      options={"time_limit": float(time_limit), "mip_rel_gap": 0.0})
        status = {0: "optimal", 1: "limit_reached", 2: "infeasible", 3: "unbounded"}.get(result.status, "solver_error")
        values = result.x.tolist() if result.x is not None and status in ("optimal", "limit_reached") else None
        okay, value = feasible_and_value(p, values)
        if not okay:
            values, value = None, None
            if status == "optimal":
                status = "solver_error"
        backend, detail = "scipy.optimize.milp/HiGHS", str(result.message)
    return {"status": status, "values": values, "objective_value": value,
            "feasible_solution_present": values is not None, "optimality_proven": status == "optimal",
            "backend": backend, "tool_version": "1.0", "message": detail,
            "elapsed_seconds": round(time.perf_counter()-start, 4)}


def solve(call, timeout=20, solver_time_limit=10):
    call_problem(call)
    try:
        proc = subprocess.run([sys.executable, "-m", "task2.tools"], cwd=ROOT,
                              input=json.dumps({"call": call, "time_limit": solver_time_limit}),
                              encoding="utf-8", capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "solver_timeout", "values": None, "objective_value": None,
                "feasible_solution_present": False, "optimality_proven": False}
    if proc.returncode:
        return {"status": "solver_error", "values": None, "objective_value": None,
                "message": proc.stderr[-2000:]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "solver_error", "values": None, "objective_value": None,
                "message": "Invalid worker protocol"}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(solve_direct(request["call"], request["time_limit"]), allow_nan=False))
