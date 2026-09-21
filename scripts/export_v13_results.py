"""Re-export frozen v1.3 results, no model calls or retrospective regrading."""
import argparse
import hashlib
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from task2.core import read, save
from task2.expansion import public_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "outputs/task2_v13_comparison")
    parser.add_argument("--tests", type=Path, default=ROOT / "outputs/task2_v13_engineering/tests.xml")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/task2-v13-results.json")
    args = parser.parse_args()
    paths = {k: args.directory / (k + ".json") for k in ("instances", "validation", "results")}
    summary = public_summary(read(paths["instances"]), read(paths["validation"]), read(paths["results"]))
    suites = list(ET.parse(args.tests).getroot().iter("testsuite"))
    summary["tests"] = {k: sum(int(s.get(k, 0)) for s in suites)
                        for k in ("tests", "failures", "errors", "skipped")}
    summary["source_sha256"] = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()}
    summary["source_sha256"]["tests"] = hashlib.sha256(args.tests.read_bytes()).hexdigest()
    for name in ("catalog", "handoffs"):
        summary["source_sha256"][name] = hashlib.sha256((ROOT / f"data/task2_v13/{name}.json").read_bytes()).hexdigest()
    save(args.output, summary)
    print("Exported verified hashes and recorded scores; no model calls or regrading")


if __name__ == "__main__":
    main()
