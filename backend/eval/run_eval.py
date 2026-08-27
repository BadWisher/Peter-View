"""Оценка отчётов вычитки по версионированному корпусу кейсов.

По умолчанию команда гоняет живой пайплайн. Функции подсчёта баллов
намеренно не зависят от пайплайна: CI может проверять их на подложных
отчётах без ключей к модели.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import re
import sys
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import yaml

CASES_PATH = Path(__file__).resolve().parent / "cases.yaml"
SCHEMA_VERSION = 2

Report = Mapping[str, Any]
ReportProvider = Callable[[dict[str, Any]], Report | Awaitable[Report]]


def load_suite(path: Path = CASES_PATH) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("cases", []), list):
        raise ValueError("Eval file must contain a 'cases' list")
    version = int(data.get("version", 1))
    if version not in (1, SCHEMA_VERSION):
        raise ValueError(f"Unsupported eval schema version: {version}")
    return data


def _rule_id(issue: Mapping[str, Any]) -> str:
    return str(issue.get("rule_id") or issue.get("rule") or issue.get("registry_id") or "")


def _block_index(issue: Mapping[str, Any]) -> int | None:
    value = issue.get("block_index", issue.get("line"))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _span(issue: Mapping[str, Any]) -> tuple[int, int] | None:
    sources = [issue]
    for key in ("span", "evidence", "location"):
        value = issue.get(key)
        if isinstance(value, Mapping):
            sources.append(value)
    for source in sources:
        start = source.get("start", source.get("start_offset"))
        end = source.get("end", source.get("end_offset"))
        try:
            if start is not None and end is not None:
                return int(start), int(end)
        except (TypeError, ValueError):
            continue
    return None


def _evidence_text(issue: Mapping[str, Any]) -> str:
    for key in ("span_text", "evidence_text", "matched_text", "text"):
        if issue.get(key):
            return str(issue[key])
    for key in ("span", "evidence"):
        nested = issue.get(key)
        if isinstance(nested, Mapping) and nested.get("text"):
            return str(nested["text"])
    return ""


def _as_expectation(value: Any, default_key: str = "rule_id") -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {default_key: value}


def _matches_issue(expectation: Mapping[str, Any], issue: Mapping[str, Any]) -> bool:
    expected_rule = expectation.get("rule_id", expectation.get("rule"))
    if expected_rule is not None and str(expected_rule) != _rule_id(issue):
        return False
    expected_block = expectation.get("block_index", expectation.get("block"))
    if expected_block is not None and int(expected_block) != _block_index(issue):
        return False
    expected_severity = expectation.get("severity")
    actual_severity = issue.get("severity_llm", issue.get("severity"))
    if expected_severity is not None and str(expected_severity) != str(actual_severity):
        return False
    expected_text = expectation.get("text")
    if expected_text is not None and str(expected_text) not in _evidence_text(issue):
        return False
    if expectation.get("start") is not None or expectation.get("end") is not None:
        actual_span = _span(issue)
        if actual_span is None:
            return False
        if expectation.get("start") is not None and int(expectation["start"]) != actual_span[0]:
            return False
        if expectation.get("end") is not None and int(expectation["end"]) != actual_span[1]:
            return False
    return True


def _suggestion_matches(expectation: Any, issue: Mapping[str, Any]) -> bool:
    item = _as_expectation(expectation, "value")
    if not _matches_issue(item, issue):
        return False
    expected = str(item.get("value", item.get("suggestion", "")))
    actual = str(issue.get("suggestion", issue.get("replacement", "")))
    mode = item.get("match", "contains")
    if mode == "exact":
        return actual == expected
    if mode == "regex":
        return re.search(expected, actual, re.IGNORECASE) is not None
    return expected.casefold() in actual.casefold()


def _case_contract(case: Mapping[str, Any]) -> tuple[dict[str, list[Any]], dict[str, list[Any]], bool]:
    expected = case.get("expect", {})
    forbidden = case.get("forbid", {})
    expected = dict(expected) if isinstance(expected, Mapping) else {}
    forbidden = dict(forbidden) if isinstance(forbidden, Mapping) else {}
    # Version 1 compatibility.
    expected.setdefault("rules", case.get("expect_rules", []) or [])
    forbidden.setdefault("rules", case.get("forbid_rules", []) or [])
    for key in ("rules", "blocks", "spans", "suggestions"):
        expected[key] = list(expected.get(key, []) or [])
        forbidden[key] = list(forbidden.get(key, []) or [])
    clean = bool(case.get("clean", False))
    return expected, forbidden, clean


def evaluate_case(case: Mapping[str, Any], report: Report) -> dict[str, Any]:
    issues = [item for item in report.get("issues", []) if isinstance(item, Mapping)]
    expected, forbidden, clean = _case_contract(case)
    missing: dict[str, list[Any]] = {key: [] for key in expected}
    violations: dict[str, list[Any]] = {key: [] for key in forbidden}

    for item in expected["rules"]:
        expectation = _as_expectation(item)
        if not any(_matches_issue(expectation, issue) for issue in issues):
            missing["rules"].append(item)
    for item in expected["blocks"]:
        expectation = _as_expectation(item, "block_index")
        if not any(_matches_issue(expectation, issue) for issue in issues):
            missing["blocks"].append(item)
    for item in expected["spans"]:
        expectation = _as_expectation(item)
        if not any(_matches_issue(expectation, issue) for issue in issues):
            missing["spans"].append(item)
    for item in expected["suggestions"]:
        if not any(_suggestion_matches(item, issue) for issue in issues):
            missing["suggestions"].append(item)

    for item in forbidden["rules"]:
        expectation = _as_expectation(item)
        if any(_matches_issue(expectation, issue) for issue in issues):
            violations["rules"].append(item)
    for item in forbidden["blocks"]:
        expectation = _as_expectation(item, "block_index")
        if any(_matches_issue(expectation, issue) for issue in issues):
            violations["blocks"].append(item)
    for item in forbidden["spans"]:
        expectation = _as_expectation(item)
        if any(_matches_issue(expectation, issue) for issue in issues):
            violations["spans"].append(item)
    for item in forbidden["suggestions"]:
        if any(_suggestion_matches(item, issue) for issue in issues):
            violations["suggestions"].append(item)

    clean_violation = clean and bool(issues)
    failures = [
        f"missing {key}: {value}" for key, value in missing.items() if value
    ] + [
        f"forbidden {key}: {value}" for key, value in violations.items() if value
    ]
    if clean_violation:
        failures.append(f"clean case produced {len(issues)} issue(s)")

    expected_counts = {key: len(value) for key, value in expected.items()}
    hit_counts = {key: expected_counts[key] - len(missing[key]) for key in expected}
    expected_rule_ids = {
        str(_as_expectation(item).get("rule_id", ""))
        for item in expected["rules"]
        if _as_expectation(item).get("rule_id")
    }
    meta = report.get("meta", {}) if isinstance(report.get("meta"), Mapping) else {}
    retrieval = meta.get("retrieval", {}) if isinstance(meta.get("retrieval"), Mapping) else {}
    selected = retrieval.get("selected_rules", {})
    selected_rule_ids = {
        str(rule_id)
        for values in selected.values()
        for rule_id in (values if isinstance(values, list) else [])
    } if isinstance(selected, Mapping) else set()
    provenance = meta.get("candidate_provenance", [])
    candidate_rule_ids = {
        str(item.get("rule_id", ""))
        for item in provenance
        if isinstance(item, Mapping) and item.get("rule_id")
    } if isinstance(provenance, list) else set()
    final_rule_ids = {_rule_id(issue) for issue in issues}
    pass_metrics = meta.get("pass_metrics", [])
    latency_ms = sum(
        float(item.get("duration_ms", 0) or 0)
        for item in pass_metrics
        if isinstance(item, Mapping)
    ) if isinstance(pass_metrics, list) else None
    token_usage = meta.get("token_usage", {})
    if not isinstance(token_usage, Mapping):
        token_usage = {}
    return {
        "name": str(case.get("name", "unnamed")),
        "capability": case.get("capability"),
        "tags": list(case.get("tags", []) or []),
        "passed": not failures,
        "failures": failures,
        "expected": expected_counts,
        "hits": hit_counts,
        "forbidden_violations": sum(len(value) for value in violations.values()),
        "clean": clean,
        "clean_violation": clean_violation,
        "issues_found": len(issues),
        "partial_report": bool(report.get("partial", False)),
        "pipeline_version": meta.get("pipeline_version"),
        "retrieval_observed": isinstance(selected, Mapping),
        "candidate_observed": "candidate_provenance" in meta,
        "expected_rule_ids": sorted(expected_rule_ids),
        "retrieval_rule_hits": len(expected_rule_ids & selected_rule_ids),
        "candidate_rule_hits": len(expected_rule_ids & candidate_rule_ids),
        "final_rule_hits": len(expected_rule_ids & final_rule_ids),
        "latency_ms": latency_ms,
        "tokens": int(token_usage.get("tokens", 0) or 0),
        "token_calls": int(token_usage.get("calls", 0) or 0),
        "tokens_by_worker": dict(token_usage.get("by_worker", {}) or {}),
        "fallback_tiers": sorted({
            str(value.get("fallback_tier"))
            for value in retrieval.values()
            if isinstance(value, Mapping) and value.get("fallback_tier")
        }),
    }


def _recall(results: Iterable[Mapping[str, Any]], key: str) -> float | None:
    expected = sum(int(result["expected"][key]) for result in results)
    hits = sum(int(result["hits"][key]) for result in results)
    return hits / expected if expected else None


def summarize(results: list[dict[str, Any]], thresholds: Mapping[str, Any] | None = None) -> dict[str, Any]:
    thresholds = dict(thresholds or {})
    total = len(results)
    passed_cases = sum(bool(result["passed"]) for result in results)
    retrieval_expected = sum(
        len(result.get("expected_rule_ids", []))
        for result in results
        if result.get("retrieval_observed")
    )
    candidate_expected = sum(
        len(result.get("expected_rule_ids", []))
        for result in results
        if result.get("candidate_observed")
    )
    metrics = {
        "case_pass_rate": passed_cases / total if total else 1.0,
        "rule_recall": _recall(results, "rules"),
        "block_recall": _recall(results, "blocks"),
        "span_recall": _recall(results, "spans"),
        "suggestion_recall": _recall(results, "suggestions"),
        "forbidden_violations": sum(int(result["forbidden_violations"]) for result in results),
        "clean_failures": sum(bool(result["clean_violation"]) for result in results),
        "rule_recall_at_k": (
            sum(result.get("retrieval_rule_hits", 0) for result in results) / retrieval_expected
            if retrieval_expected else None
        ),
        "finder_rule_recall": (
            sum(result.get("candidate_rule_hits", 0) for result in results) / candidate_expected
            if candidate_expected else None
        ),
        "verifier_rule_recall": (
            sum(
                result.get("final_rule_hits", 0)
                for result in results
                if result.get("candidate_observed")
            )
            / candidate_expected
            if candidate_expected else None
        ),
        "latency_ms_total": sum(
            result.get("latency_ms") or 0 for result in results
        ),
        "tokens_total": sum(result.get("tokens", 0) for result in results),
        "token_calls": sum(result.get("token_calls", 0) for result in results),
    }
    checks: list[dict[str, Any]] = []
    threshold_map = {
        "min_case_pass_rate": ("case_pass_rate", "min"),
        "min_rule_recall": ("rule_recall", "min"),
        "min_block_recall": ("block_recall", "min"),
        "min_span_recall": ("span_recall", "min"),
        "min_suggestion_recall": ("suggestion_recall", "min"),
        "max_forbidden_violations": ("forbidden_violations", "max"),
        "max_clean_failures": ("clean_failures", "max"),
        "min_rule_recall_at_k": ("rule_recall_at_k", "min"),
        "min_finder_rule_recall": ("finder_rule_recall", "min"),
        "min_verifier_rule_recall": ("verifier_rule_recall", "min"),
        "max_latency_ms_total": ("latency_ms_total", "max"),
        "max_tokens_total": ("tokens_total", "max"),
    }
    for threshold_name, raw_limit in thresholds.items():
        if threshold_name not in threshold_map:
            continue
        metric_name, direction = threshold_map[threshold_name]
        actual = metrics[metric_name]
        limit = float(raw_limit)
        passed = actual is None or (actual >= limit if direction == "min" else actual <= limit)
        checks.append({
            "threshold": threshold_name,
            "metric": metric_name,
            "actual": actual,
            "limit": limit,
            "passed": passed,
        })
    return {
        "total_cases": total,
        "passed_cases": passed_cases,
        "failed_cases": total - passed_cases,
        "metrics": metrics,
        "thresholds": checks,
        "passed": all(check["passed"] for check in checks),
    }


async def run_suite(
    suite: Mapping[str, Any],
    report_provider: ReportProvider,
    threshold_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    results = []
    for case in suite.get("cases", []):
        try:
            report = report_provider(case)
            if inspect.isawaitable(report):
                report = await report
            if not isinstance(report, Mapping):
                raise TypeError("report provider returned a non-object")
            result = evaluate_case(case, report)
        except Exception as exc:
            result = evaluate_case(case, {"issues": [], "partial": True})
            result["passed"] = False
            result["report_error"] = f"{type(exc).__name__}: {exc}"
            result["failures"].append(f"report error: {result['report_error']}")
        results.append(result)
    thresholds = dict(suite.get("thresholds", {}) or {})
    thresholds.update(threshold_overrides or {})
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summarize(results, thresholds),
        "cases": results,
    }


def write_json(result: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_junit(result: Mapping[str, Any], path: Path) -> None:
    cases = result.get("cases", [])
    summary = result.get("summary", {})
    root = ET.Element(
        "testsuite",
        name="proofreader-eval",
        tests=str(len(cases)),
        failures=str(summary.get("failed_cases", 0)),
    )
    properties = ET.SubElement(root, "properties")
    for name, value in summary.get("metrics", {}).items():
        ET.SubElement(properties, "property", name=name, value="" if value is None else str(value))
    for case in cases:
        node = ET.SubElement(
            root,
            "testcase",
            name=str(case["name"]),
            classname=f"eval.{case.get('capability') or 'general'}",
        )
        if not case["passed"]:
            failure = ET.SubElement(node, "failure", message="; ".join(case["failures"]))
            failure.text = "\n".join(case["failures"])
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


async def _live_provider() -> ReportProvider:
    # Keep app imports out of score-only tests and report conversion tools.
    from app.llm import styleguide_store
    from app.llm import stats as llm_stats
    from app.llm.documents import parse_html, parse_markdown, parse_txt
    from app.llm.pipeline import run_pipeline

    styleguide_store.seed_default()
    guide = styleguide_store.get_guide(styleguide_store.DEFAULT_ID)
    if guide is None:
        raise RuntimeError("Built-in style guide was not found")

    async def provide(case: dict[str, Any]) -> Report:
        text = str(case.get("text", ""))
        source = str(case.get("name", "eval"))
        input_format = str(case.get("format", "txt")).lower()
        if input_format in {"md", "markdown"}:
            document = parse_markdown(text, source=source)
        elif input_format in {"html", "htm"}:
            document = parse_html(text, source=source)
        else:
            document = parse_txt(text, source=source)
        eval_job_id = f"eval:{source}"
        llm_stats.set_context("eval", eval_job_id)
        report = await run_pipeline(document, guide)
        report.setdefault("meta", {})["token_usage"] = llm_stats.job_token_usage(eval_job_id)
        return report

    return provide


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--json", type=Path, dest="json_path")
    parser.add_argument("--junit", type=Path, dest="junit_path")
    parser.add_argument("--min-case-pass-rate", type=float)
    parser.add_argument("--min-rule-recall", type=float)
    parser.add_argument("--min-block-recall", type=float)
    parser.add_argument("--min-span-recall", type=float)
    parser.add_argument("--min-suggestion-recall", type=float)
    parser.add_argument("--max-forbidden-violations", type=int)
    parser.add_argument("--max-clean-failures", type=int)
    parser.add_argument("--min-rule-recall-at-k", type=float)
    parser.add_argument("--min-finder-rule-recall", type=float)
    parser.add_argument("--min-verifier-rule-recall", type=float)
    parser.add_argument("--max-latency-ms-total", type=float)
    parser.add_argument("--max-tokens-total", type=int)
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    suite = load_suite(args.cases)
    overrides = {
        name: value
        for name, value in vars(args).items()
        if name.startswith(("min_", "max_")) and value is not None
    }
    result = await run_suite(suite, await _live_provider(), overrides)
    if args.json_path:
        write_json(result, args.json_path)
    if args.junit_path:
        write_junit(result, args.junit_path)

    summary = result["summary"]
    print(
        f"Eval: {summary['passed_cases']}/{summary['total_cases']} cases passed; "
        f"thresholds {'passed' if summary['passed'] else 'failed'}"
    )
    for case in result["cases"]:
        if not case["passed"]:
            print(f"- {case['name']}: {'; '.join(case['failures'])}")
    return 0 if summary["passed"] else 1


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(async_main(argv)))


if __name__ == "__main__":
    main(sys.argv[1:])
