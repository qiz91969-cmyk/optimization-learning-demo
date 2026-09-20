"""在线环路。关键约束：本模块不导入评估器，也不读取参考答案。

模型的工作是提取和填写参数；路由、校验、求解由确定性程序完成。
真正无解也是一次完成的求解，不会把参考最优值发回去要求模型改题。
"""
from copy import deepcopy
import time

from .backend import ModelError
from .prompts import make_messages, template_hint, PROMPT_VERSION
from .solver import solve_isolated
from .validation import ValidationError, parse_model_output, validate_problem, build_call


def run_online(public_record, mode, problem=None, backend=None, retries=2, solve_fn=solve_isolated):
    """retries是首轮以外的次数，取0可运行无反馈基线。

    JSON模式直接接收已整理问题，不能把其成功计为LLM成功。
    每轮保存请求、原文、规范化标记、校验结果、工具调用与返回。
    """
    if mode not in ("json", "nl") or not 0 <= retries <= 2:
        raise ValueError("mode must be json/nl; retries must be 0..2")
    started = time.perf_counter()
    record = {"sample_id": public_record["sample_id"], "mode": mode, "source": public_record["source"],
              "record_type": "real_local_model" if mode == "nl" else "structured_input",
              "prompt_version": PROMPT_VERSION, "attempts": [], "online_status": "not_started"}
    messages = make_messages(public_record) if mode == "nl" else []
    record["public_template_hint"] = template_hint(public_record) if mode == "nl" else None
    limit = 1 if mode == "json" else retries + 1
    for index in range(limit):
        attempt = {"attempt": index, "messages": deepcopy(messages), "raw_text": None,
                   "raw_json_valid": None, "normalized_json_valid": None,
                   "fence_removed": False, "schema_valid": False, "feedback": None}
        record["attempts"].append(attempt)
        try:
            if mode == "nl":
                response = backend.generate(messages)
                attempt["model_metadata"] = {k: v for k, v in response.items() if k != "raw_text"}
                attempt["raw_text"] = response["raw_text"]
                attempt["raw_json_valid"] = False
                attempt["normalized_json_valid"] = False
                extracted, cleaned = parse_model_output(response["raw_text"])
                attempt["fence_removed"] = cleaned
                attempt["raw_json_valid"] = not cleaned
                attempt["normalized_json_valid"] = True
            else:
                extracted = deepcopy(problem)
            attempt["problem"] = extracted
            validate_problem(extracted)
            if extracted["entities"] != public_record["entity_order"]:
                raise ValidationError("entities must copy the public entity_order identifiers exactly, in order.")
            attempt["schema_valid"] = True
            if extracted["missing_information"]:
                attempt["feedback"] = "Missing information was reported; no values were invented."
                record["online_status"] = "needs_information"
                break
            call = build_call(extracted)
            attempt["tool_call"] = call
            attempt["solver_result"] = solve_fn(call)
            state = attempt["solver_result"]["status"]
            record["online_status"] = "completed" if state in ("optimal", "infeasible", "unbounded") else state
            # 求解状态不是隐藏答案。无解/无界均停止，留给独立评估判别是否建模错误。
            break
        except ValidationError as exc:
            attempt["feedback"] = str(exc)
            record["online_status"] = "validation_failed"
            if mode == "nl" and index + 1 < limit:
                messages.extend([{"role": "assistant", "content": attempt["raw_text"] or ""},
                                 {"role": "user", "content": "Interface validation failed: " + str(exc) +
                                  " Correct the JSON only using the original question. Do not invent facts or change constraints."}])
        except ModelError as exc:
            attempt["feedback"] = str(exc)
            record["online_status"] = exc.status
            break
    record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return record
