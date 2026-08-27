from __future__ import annotations

import asyncio
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from eval.run_eval import (
    evaluate_case,
    load_suite,
    run_suite,
    summarize,
    write_json,
    write_junit,
)


def _issue(
    rule_id: str,
    *,
    block_index: int = 0,
    start: int = 0,
    end: int = 4,
    text: str = "текст",
    suggestion: str = "исправление",
    severity: str = "blocker",
) -> dict:
    return {
        "rule_id": rule_id,
        "block_index": block_index,
        "span": {"start": start, "end": end, "text": text},
        "suggestion": suggestion,
        "severity_llm": severity,
    }


def test_evaluate_case_scores_rule_block_span_and_suggestion() -> None:
    case = {
        "name": "all dimensions",
        "expect": {
            "rules": ["Guide.Rule"],
            "blocks": [{"rule_id": "Guide.Rule", "block_index": 2}],
            "spans": [{
                "rule_id": "Guide.Rule",
                "block_index": 2,
                "start": 5,
                "end": 11,
                "text": "ошибка",
                "severity": "blocker",
            }],
            "suggestions": [{
                "rule_id": "Guide.Rule",
                "value": r"исправ(ьте|ить)",
                "match": "regex",
            }],
        },
        "forbid": {
            "rules": ["Guide.Other"],
            "suggestions": [{"value": "опасная замена", "match": "exact"}],
        },
    }
    report = {
        "issues": [
            _issue(
                "Guide.Rule",
                block_index=2,
                start=5,
                end=11,
                text="ошибка",
                suggestion="исправьте",
            )
        ]
    }

    result = evaluate_case(case, report)

    assert result["passed"] is True
    assert result["expected"] == {
        "rules": 1,
        "blocks": 1,
        "spans": 1,
        "suggestions": 1,
    }
    assert result["hits"] == result["expected"]


def test_evaluate_case_reports_missing_and_forbidden_findings() -> None:
    case = {
        "name": "failure details",
        "expect": {"rules": ["Guide.Expected"]},
        "forbid": {
            "rules": ["Guide.Forbidden"],
            "suggestions": [{"value": "bad", "match": "exact"}],
        },
    }
    report = {
        "issues": [
            _issue("Guide.Forbidden", suggestion="bad"),
        ]
    }

    result = evaluate_case(case, report)

    assert result["passed"] is False
    assert result["forbidden_violations"] == 2
    assert any("missing rules" in failure for failure in result["failures"])
    assert any("forbidden suggestions" in failure for failure in result["failures"])


def test_clean_case_rejects_any_issue() -> None:
    result = evaluate_case(
        {"name": "clean", "clean": True},
        {"issues": [_issue("Unexpected.Rule")]},
    )

    assert result["passed"] is False
    assert result["clean_violation"] is True
    assert result["issues_found"] == 1


def test_legacy_expect_rules_remains_supported() -> None:
    result = evaluate_case(
        {"name": "legacy", "expect_rules": ["Legacy.Rule"]},
        {"issues": [{"rule": "Legacy.Rule", "line": 0}]},
    )

    assert result["passed"] is True
    assert result["hits"]["rules"] == 1


def test_run_suite_accepts_async_fake_provider_without_live_llm() -> None:
    suite = {
        "version": 2,
        "thresholds": {
            "min_case_pass_rate": 1,
            "min_rule_recall": 1,
            "max_forbidden_violations": 0,
        },
        "cases": [
            {"name": "positive", "expect": {"rules": ["Guide.Rule"]}},
            {"name": "negative", "clean": True},
        ],
    }

    async def fake_provider(case: dict) -> dict:
        if case["name"] == "positive":
            return {"issues": [_issue("Guide.Rule")]}
        return {"issues": []}

    result = asyncio.run(run_suite(suite, fake_provider))

    assert result["summary"]["passed"] is True
    assert result["summary"]["metrics"]["rule_recall"] == 1
    assert result["summary"]["metrics"]["case_pass_rate"] == 1


def test_run_suite_records_provider_failure_for_clean_case() -> None:
    suite = {
        "version": 2,
        "thresholds": {"min_case_pass_rate": 1},
        "cases": [{"name": "provider failed", "clean": True}],
    }

    def failed_provider(_case: dict) -> dict:
        raise RuntimeError("model unavailable")

    result = asyncio.run(run_suite(suite, failed_provider))

    case = result["cases"][0]
    assert case["passed"] is False
    assert case["report_error"] == "RuntimeError: model unavailable"
    assert result["summary"]["passed"] is False


def test_thresholds_control_overall_status() -> None:
    results = [
        {
            "passed": False,
            "expected": {"rules": 2, "blocks": 0, "spans": 0, "suggestions": 0},
            "hits": {"rules": 1, "blocks": 0, "spans": 0, "suggestions": 0},
            "forbidden_violations": 0,
            "clean_violation": False,
        },
        {
            "passed": True,
            "expected": {"rules": 0, "blocks": 0, "spans": 0, "suggestions": 0},
            "hits": {"rules": 0, "blocks": 0, "spans": 0, "suggestions": 0},
            "forbidden_violations": 0,
            "clean_violation": False,
        },
    ]

    failed = summarize(results, {"min_rule_recall": 0.75})
    passed = summarize(results, {"min_rule_recall": 0.5, "min_case_pass_rate": 0.5})

    assert failed["passed"] is False
    assert passed["passed"] is True


def test_json_and_junit_outputs_are_machine_readable(tmp_path: Path) -> None:
    result = {
        "schema_version": 2,
        "summary": {
            "failed_cases": 1,
            "metrics": {"case_pass_rate": 0.5, "span_recall": None},
        },
        "cases": [
            {
                "name": "passes",
                "capability": "routing",
                "passed": True,
                "failures": [],
            },
            {
                "name": "fails",
                "capability": "grounding",
                "passed": False,
                "failures": ["missing spans"],
            },
        ],
    }
    json_path = tmp_path / "result.json"
    junit_path = tmp_path / "result.xml"

    write_json(result, json_path)
    write_junit(result, junit_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["schema_version"] == 2
    xml = ET.parse(junit_path).getroot()
    assert xml.attrib["tests"] == "2"
    assert xml.attrib["failures"] == "1"
    assert xml.find("./testcase[@name='fails']/failure") is not None


def test_repository_corpus_uses_v2_capability_pairs() -> None:
    suite = load_suite(Path(__file__).parents[1] / "eval" / "cases.yaml")
    cases = suite["cases"]
    capabilities = {case.get("capability") for case in cases}

    assert suite["version"] == 2
    assert capabilities == {
        "style-guide-precedence",
        "non-obvious-rule-retrieval",
        "formatting-evidence",
        "ui-context-interpretation",
        "cross-block-structure",
    }
    for capability in capabilities:
        paired = [case for case in cases if case["capability"] == capability]
        assert any("positive" in case.get("tags", []) for case in paired)
        assert any("negative" in case.get("tags", []) for case in paired)
