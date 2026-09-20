"""只从公开题干选择受限模板；另用虚构例题演示格式，不读取参考答案。"""
import json
import re

PROMPT_VERSION = "civilian-guided-fewshot-v4"


def template_hint(public_record):
    """透明教学规则：不按sample_id查表；混合类别要求人工拆分。"""
    text = public_record["description_en"].lower()
    transport = bool(re.search(r"\bwarehouses?\b", text))
    assignment = bool(re.search(r"\bworkers?\b", text))
    if transport and assignment:
        raise ValueError("Mixed worker/warehouse exercise is outside the demo templates.")
    if transport:
        return {"family": "transportation", "basis": "public description contains warehouse(s)"}
    if assignment:
        return {"family": "assignment", "basis": "public description contains worker(s)"}
    return {"family": "linear", "basis": "fallback within the declared linear-resource exercise scope"}


def make_messages(public_record):
    """白名单输入、显式字段清单、独立教学示例；新题数字必须由模型提取。"""
    family = template_hint(public_record)["family"]
    rules = {
        "linear": (
            "parameters keys: objective_coefficients, constraints, lower_bounds, upper_bounds, variable_type. "
            "Each constraint has name, coefficients, sense, rhs, unit. coefficients is a NUMBER array. "
            "Use bounds for individual limits. Add one constraint for EACH shared resource or budget. "
            "Lower bounds default to 0; absent upper bounds are null. variable_type follows the public notes."),
        "assignment": (
            "parameters has ONLY tasks and cost_matrix. Copy the cost matrix exactly. "
            "Rows are workers, columns are tasks. Each task is assigned once; each worker at most once. "
            "objective is minimize. Do not add workers or constraints fields."),
        "transportation": (
            "parameters keys: destinations, supply, demand, cost_matrix, variable_type. "
            "Copy supplies, demands, and costs exactly. Rows are warehouses; columns are destinations. "
            "Supply is an upper bound; demand is a lower bound. objective is minimize."),
    }
    # 示例来自独立虚构教学题，不是五道开发题的参考问题或最优解。
    examples = {
        "linear": (
            "Make products P and Q. Maximum quantities are 8 and 9. A shared resource has capacity 18; each P uses 2 and each Q uses 1. Profits are 3 and 4. Maximize profit. Counts are integers. Units: quantity=items, objective=dollars, resource=hours.",
            {"problem_type":"linear","objective":"maximize","entities":["P","Q"],"units":{"quantity":"items","objective":"dollars"},
             "parameters":{"objective_coefficients":[3,4],"constraints":[{"name":"resource","coefficients":[2,1],"sense":"<=","rhs":18,"unit":"hours"}],"lower_bounds":[0,0],"upper_bounds":[8,9],"variable_type":"integer"},"missing_information":[]}),
        "assignment": (
            "Workers U,V must perform tasks J,K, each task once and each worker at most once. Costs by worker rows and task columns are [[8,2],[3,9]]. Minimize cost. Units: quantity=assignments, objective=cost_units.",
            {"problem_type":"assignment","objective":"minimize","entities":["U","V"],"units":{"quantity":"assignments","objective":"cost_units"},"parameters":{"tasks":["J","K"],"cost_matrix":[[8,2],[3,9]]},"missing_information":[]}),
        "transportation": (
            "Warehouses X,Y ship integer crates to shops S,T. Supply=[10,20], minimum demand=[12,8], costs by warehouse rows and shop columns=[[4,2],[1,3]]. Minimize cost, unused supply allowed. Units: quantity=crates, objective=dollars.",
            {"problem_type":"transportation","objective":"minimize","entities":["X","Y"],"units":{"quantity":"crates","objective":"dollars"},"parameters":{"destinations":["S","T"],"supply":[10,20],"demand":[12,8],"cost_matrix":[[4,2],[1,3]],"variable_type":"integer"},"missing_information":[]}),
    }
    example_question, example_answer = examples[family]
    system = (
        "Extract an optimization question into a JSON object. Do not solve it. Return only JSON. "
        "EXACTLY SIX required top-level keys: problem_type, objective, entities, units, parameters, missing_information. "
        "objective must be maximize or minimize. entities is an array of identifier strings. "
        "units has quantity and objective strings from the public notes. missing_information is [] if nothing is missing. "
        "Do not omit any of these six keys. Do not add keys. Use NEW question numbers, not example numbers. "
        + rules[family])
    question = (
        "NEW QUESTION:\n" + public_record["description_en"] + "\nPUBLIC NOTES:\n"
        + public_record["modeling_notes_en"] + "\nUse problem_type=" + family
        + "; entities=" + json.dumps(public_record["entity_order"])
        + ". Include all SIX keys: problem_type, objective, entities, units, parameters, missing_information.")
    return [{"role":"system","content":system}, {"role":"user","content":example_question},
            {"role":"assistant","content":json.dumps(example_answer)}, {"role":"user","content":question}]
