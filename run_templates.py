"""Task-two entry point. Run with --help; the legacy run_demo.py stays intact."""
import argparse
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET

from demo.backend import LocalQwen, ModelError
from demo.ollama_backend import OllamaModel
from task2.core import CASES, FORMS, ROOT, read, save
from task2.report import render
from task2.runtime import run_view
from task2.workflow import fault_checks, prepare, run_chain, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("instantiate", "validate", "run", "report", "probe"))
    parser.add_argument("--directory", type=Path, default=ROOT / "outputs/task2_demo")
    parser.add_argument("--case", choices=(*CASES, "all"), default="all")
    parser.add_argument("--template", choices=("all", "problem_understanding", "method_selection", "tool_use"), default="all")
    parser.add_argument("--form", choices=(*FORMS, "all"), default="all")
    parser.add_argument("--retries", type=int, choices=(0, 1, 2), default=2)
    parser.add_argument("--chain", action="store_true", help="Also run the assignment chain")
    parser.add_argument("--tests-xml", type=Path)
    parser.add_argument("--backend", choices=("local", "ollama"), default="local")
    parser.add_argument("--ollama-url", help="Default: DEMO_OLLAMA_URL or http://127.0.0.1:11435")
    parser.add_argument("--model", default="qwen2.5:14b", help="Ollama installed model tag")
    parser.add_argument("--model-timeout", type=float, default=300, help="Ollama request timeout in seconds")
    args = parser.parse_args()
    if args.command == "probe":
        if args.backend != "ollama":
            parser.error("probe requires --backend ollama; for local use check_environment.py")
        import json
        try:
            backend = OllamaModel(args.ollama_url, args.model, args.model_timeout)
            print(json.dumps(backend.probe(), ensure_ascii=False, indent=2))
            return 0
        except (ValueError, ModelError) as exc:
            print(str(exc))
            return 2
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.command == "instantiate":
        if (directory / "instances.json").exists():
            parser.error("Directory already contains instances; choose a new directory to preserve history")
        payload = prepare(directory)
        checks = validate(payload, directory)
        save(directory / "validation.json", checks)
        print(f"Instantiated {len(payload['views'])} views. Checks passed: {checks['passed']}")
        return 0 if checks["passed"] else 2
    if args.command == "report":
        results = read(directory / "results.json")
        if args.tests_xml:
            tree = ET.parse(args.tests_xml)
            suites = list(tree.getroot().iter("testsuite"))
            results["tests"] = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
            results["tests"]["source"] = args.tests_xml.name
            save(directory / "results.json", results)
        print(render(results, directory))
        return 0
    payload = read(directory / "instances.json")
    checks = validate(payload, directory)
    save(directory / "validation.json", checks)
    if args.command == "validate":
        print(f"Checks: {sum(c['passed'] for c in checks['checks'])}/{len(checks['checks'])}")
        return 0 if checks["passed"] else 2
    if not checks["passed"]:
        parser.error("Instance checks failed; inspect validation.json")
    if (directory / "results.json").exists():
        parser.error("Results already exist; instantiate in a new directory for another run")
    results = {"created_at": datetime.now().astimezone().isoformat(), "cases": list(CASES),
               "template_version": payload["views"][0]["version"],
               "validation": checks, "fixtures": payload["fixtures"], "faults": fault_checks(payload),
               "config_hashes": payload["config_hashes"], "runs": [], "chain": None}
    records = {r["id"]: r for r in payload["records"]}
    if args.backend == "ollama":
        try:
            backend = OllamaModel(args.ollama_url, args.model, args.model_timeout)
            results["model_config"] = backend.probe()
        except (ValueError, ModelError) as exc:
            parser.error(str(exc))
    else:
        backend = LocalQwen(max_new_tokens=1400)
        results["model_config"] = {"backend": "local", "model": "Qwen/Qwen2.5-0.5B-Instruct"}
    for view in payload["views"]:
        if args.case != "all" and view["case_id"] != args.case:
            continue
        if args.template != "all" and view["category"] != args.template:
            continue
        if args.form != "all" and view["form"] != args.form:
            continue
        print("Running " + view["id"], flush=True)
        run = run_view(view, records[view["case_id"]], backend, retries=args.retries)
        results["runs"].append(run)
        save(directory / "results.json", results)
        print(f"  first={run['first_correct']} final={run['final_correct']} attempts={len(run['attempts'])}", flush=True)
    if args.chain:
        print("Running assignment chain", flush=True)
        results["chain"] = run_chain(records["assignment"], backend, retries=args.retries)
    save(directory / "results.json", results)
    print(render(results, directory))
    # Completion of bounded attempts is not a claim that the model answered correctly.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
