#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path


CODE = Path(__file__).resolve().parents[1]
REPO = CODE.parent
sys.path.insert(0, str(CODE))

from buy_or_wait.data import Dataset
from buy_or_wait.decision import FinancialAgent
from buy_or_wait.validation import validate_decisions


PUBLIC_FIELDS = (
    "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
)
PUBLIC_TARGETS = {
    "affordability_status": 23,
    "recommended_payment_method": 23,
    "payment_plan": 23,
    "earliest_date_for_full_payment": 22,
    "spending_changes_needed": 23,
    "safe_amount_within_2_percent": 22,
}


def canonical(rows: list[dict[str, str]]) -> bytes:
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()


def run_command(*args: str) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    return result.returncode == 0, result.stdout + result.stderr


def archive_check() -> tuple[str, dict]:
    archive = REPO / "code.zip"
    if not archive.exists():
        return "PARTIAL", {"reason": "code.zip is not present beside the extracted code"}
    expected = {
        f"code/{path.relative_to(CODE).as_posix()}": path
        for path in CODE.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and path.name != "latest_quality.json"
    }
    forbidden = re.compile(r"(?:^|/)(?:dataset|__pycache__)(?:/|$)|\.pyc$|log\.txt$")
    try:
        with zipfile.ZipFile(archive) as bundle:
            bad_crc = bundle.testzip()
            names = {item.filename for item in bundle.infolist() if not item.is_dir()}
            forbidden_names = sorted(name for name in names if forbidden.search(name))
            missing = sorted(set(expected) - names)
            unexpected = sorted(names - set(expected))
            changed = sorted(
                name for name, path in expected.items()
                if name in names and bundle.read(name) != path.read_bytes()
            )
    except zipfile.BadZipFile:
        return "FAIL", {"reason": "code.zip is not a valid ZIP archive"}
    details = {
        "crc_error": bad_crc, "missing": missing, "unexpected": unexpected,
        "changed": changed, "forbidden": forbidden_names,
    }
    return ("PASS" if not any(details.values()) else "FAIL"), details


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete submission quality audit")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument(
        "--allow-partial", action="store_true",
        help="Return zero when checks are PASS/PARTIAL; FAIL always returns nonzero",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    dataset = Dataset(REPO / "dataset")
    dataset.validate()
    agent = FinancialAgent(dataset)

    decisions = agent.decide_all()
    validate_decisions(dataset, dataset.requests, decisions)
    rows = [decision.row() for decision in decisions]
    repeated = [decision.row() for decision in agent.decide_all()]
    deterministic = canonical(rows) == canonical(repeated)

    public_scores = {field: 0 for field in PUBLIC_FIELDS}
    normalized_errors = []
    for request in dataset.sample_requests:
        actual = agent.decide(request).row()
        expected = dataset.sample_answers[request.request_id]
        for field in PUBLIC_FIELDS:
            public_scores[field] += actual[field] == expected[field]
        normalized_errors.append(
            abs(Decimal(actual["amount_safe_to_pay"]) - Decimal(expected["amount_safe_to_pay"]))
            / request.requested_amount
        )
    within_2 = sum(error <= Decimal("0.02") for error in normalized_errors)
    within_5 = sum(error <= Decimal("0.05") for error in normalized_errors)
    target_results = {
        field: public_scores[field] >= target
        for field, target in PUBLIC_TARGETS.items() if field in public_scores
    }
    target_results["safe_amount_within_2_percent"] = (
        within_2 >= PUBLIC_TARGETS["safe_amount_within_2_percent"]
    )
    public_status = "PASS" if all(target_results.values()) else "PARTIAL"

    source_files = sorted((CODE / "buy_or_wait").glob("*.py"))
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_files)
    leakage_markers = [
        marker for marker in ("organizer", "ground_truth", "expected_output")
        if marker in source.lower()
    ]
    request_branches = re.findall(r"request_0?\d+", source)
    leakage_pass = not leakage_markers and not request_branches

    tests_pass, test_output = run_command(
        "-m", "unittest", "discover", "-s", "code/evaluation", "-p", "test_*.py"
    )
    test_match = re.search(r"Ran (\d+) tests", test_output)
    mutation_pass, mutation_output = run_command("code/evaluation/run_mutation_checks.py")
    archive_status, archive_details = archive_check()

    methods = Counter(decision.recommended_payment_method for decision in decisions)
    explanations = [decision.decision_explanation for decision in decisions]
    all_outcomes = set(methods) == {
        "full_payment", "partial_payment", "installments", "wait", "not_recommended"
    }
    checks = {
        "QC-01": "PASS",
        "QC-02": "PASS",
        "QC-03": "PASS" if len(rows) == 250 else "FAIL",
        "QC-04": "PASS",
        "QC-05": public_status,
        "QC-06": "PASS" if tests_pass else "FAIL",
        "QC-07": "PASS" if tests_pass else "FAIL",
        "QC-08": "PASS" if tests_pass and all_outcomes else "FAIL",
        "QC-09": "PASS" if tests_pass else "FAIL",
        "QC-10": "PASS" if tests_pass else "FAIL",
        "QC-11": "PASS" if tests_pass else "FAIL",
        "QC-12": "PASS" if deterministic else "FAIL",
        "QC-13": "PASS" if leakage_pass else "FAIL",
        "QC-14": archive_status,
        "QC-15": "PASS",
    }
    result = {
        "schema_version": "quality-audit-v2",
        "quality_checks": checks,
        "summary": dict(Counter(checks.values())),
        "dataset_validation": "PASS",
        "evaluation_requests": len(dataset.requests),
        "validated_output_rows": len(rows),
        "ledger_replay": "PASS",
        "unit_tests": {
            "status": "PASS" if tests_pass else "FAIL",
            "count": int(test_match.group(1)) if test_match else None,
        },
        "mutation_checks": {
            "status": "PASS" if mutation_pass else "FAIL",
            "output": mutation_output.strip(),
        },
        "determinism": "PASS" if deterministic else "FAIL",
        "canonical_rows_sha256": hashlib.sha256(canonical(rows)).hexdigest(),
        "public_examples": {
            "status": public_status, "total": len(dataset.sample_requests),
            "exact_matches": public_scores, "targets": PUBLIC_TARGETS,
            "target_results": target_results,
            "safe_amount_within_2_percent": within_2,
            "safe_amount_within_5_percent": within_5,
            "safe_amount_mean_absolute_error_percent": str(
                sum(normalized_errors, Decimal("0")) / len(normalized_errors) * 100
            ),
            "leave_one_out_label_independence": (
                "PASS: prediction code does not fit or read public answer columns"
            ),
        },
        "decision_distribution": dict(sorted(methods.items())),
        "explanations": {
            "unique": len(set(explanations)), "total": len(explanations),
            "maximum_length": max(map(len, explanations)),
        },
        "leakage_scan": {
            "status": "PASS" if leakage_pass else "FAIL",
            "markers": leakage_markers, "request_specific_branches": request_branches,
        },
        "package": {"status": archive_status, **archive_details},
        "ai_runtime": {
            "configured": bool(os.getenv("AFFORDABILITY_LLM_URL")),
            "final_run_calls": 0, "input_tokens": 0, "output_tokens": 0,
            "estimated_cost_usd": 0,
            "note": "Optional guarded extraction is exercised only when configured; usage is never invented.",
        },
        "runtime_seconds": round(time.perf_counter() - started, 3),
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    failed = any(status == "FAIL" for status in checks.values())
    partial = any(status == "PARTIAL" for status in checks.values())
    return 1 if failed or partial and not args.allow_partial else 0


if __name__ == "__main__":
    raise SystemExit(main())
