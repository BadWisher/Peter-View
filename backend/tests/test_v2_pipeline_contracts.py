import asyncio

import app.llm.pipeline_v2 as pipeline_v2
from app.llm import client as llm_client
from app.llm import stats as usage_stats
from app.llm.documents import Block, Document, parse_txt
from app.llm.evidence import collect_lexicon_evidence
from app.llm.pipeline import _issue_keys
from app.llm.pipeline_v2 import _dedupe_candidates
from app.llm.schemas import parse_worker_issues, validate_final_issues
from app.llm.styleguide import StyleGuide


def _guide() -> StyleGuide:
    return StyleGuide(
        id="test",
        name="Test",
        rules=[
            {
                "rule_id": "Test.Dash",
                "title": "Dash",
                "rule": "Use the allowed dash.",
                "constraints": {"forbidden_chars": ["X"], "required_chars": ["Y"]},
            }
        ],
        lexicon={
            "forbidden": [
                {
                    "rule_id": "Lexicon.bad",
                    "term": "плохой термин",
                    "replacement": "хороший термин",
                }
            ],
            "allowed": [],
        },
    )


def test_worker_issue_rejects_invalid_block_index() -> None:
    guide = _guide()
    issues = parse_worker_issues(
        {
            "issues": [
                {
                    "block_index": 99,
                    "rule_id": "Test.Dash",
                    "description": "invalid location",
                    "suggestion": "Y",
                }
            ]
        },
        source_worker=1,
        valid_ids=guide.effective_ids,
        valid_indices={0},
        blocks_by_index={0: "source"},
        guide=guide,
    )
    assert issues == []


def test_worker_issue_enforces_declared_constraints() -> None:
    guide = _guide()
    response = {
        "issues": [
            {
                "block_index": 0,
                "rule_id": "Test.Dash",
                "description": "wrong direction",
                "suggestion": "X",
            }
        ]
    }
    assert parse_worker_issues(
        response,
        source_worker=1,
        valid_ids=guide.effective_ids,
        valid_indices={0},
        blocks_by_index={0: "source"},
        guide=guide,
    ) == []


def test_policy_validator_rejects_introducing_forbidden_character() -> None:
    guide = StyleGuide(
        id="yo",
        name="Yo",
        rules=[{
            "rule_id": "Policy.Yo",
            "title": "Yo",
            "rule": "Do not introduce yo.",
            "constraints": {"forbidden_introduced_chars": ["ё", "Ё"]},
        }],
    )
    accepted, rejected = validate_final_issues(
        [{
            "block_index": 0,
            "rule_id": "Policy.Yo",
            "description": "wrong direction",
            "suggestion": "четырёх",
            "span_text": "четырех",
            "source_workers": [6],
        }],
        guide,
        {0: "Результаты четырех методов."},
    )
    assert accepted == []
    assert rejected[0]["reason"] == "invalid_reference_or_constraint"


def test_candidate_dedupe_preserves_provenance() -> None:
    base = {
        "block_index": 0,
        "rule_id": "Test.Dash",
        "span_text": "source",
        "suggestion": "Y",
        "source_workers": [1],
        "evidence_source": "llm",
        "verification_required": True,
    }
    duplicate = {
        **base,
        "source_workers": [0],
        "evidence_source": "vale",
        "verification_required": False,
    }
    result = _dedupe_candidates([base, duplicate])
    assert len(result) == 1
    assert result[0]["source_workers"] == [0, 1]
    assert result[0]["evidence_source"] == "llm+vale"
    assert result[0]["verification_required"] is False


def test_conflict_resolver_prefers_declared_specialization() -> None:
    guide = StyleGuide(
        id="conflicts",
        name="Conflicts",
        rules=[{
            "rule_id": "Specific",
            "title": "Specific",
            "rule": "Specific policy",
            "relationships": {"specializes": ["Базовая.Пунктуация"]},
            "priority": 90,
        }],
    )
    issues = [
        {"block_index": 0, "rule_id": "Specific", "suggestion": "specific"},
        {
            "block_index": 0,
            "rule_id": "Базовая.Пунктуация",
            "suggestion": "generic",
        },
    ]
    result, diagnostics = pipeline_v2._resolve_conflicts(issues, guide)
    assert [issue["rule_id"] for issue in result] == ["Specific"]
    assert diagnostics == []


def test_lexicon_evidence_is_selected_guide_data() -> None:
    guide = _guide()
    document = Document([
        Block(0, "Это плохой термин.", "Это плохой термин.", {"type": "paragraph"})
    ])
    issues = collect_lexicon_evidence(document, guide)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "Lexicon.bad"
    assert issues[0]["block_index"] == 0
    assert issues[0]["verification_required"] is True


def test_shadow_comparison_keys_use_location_rule_and_suggestion() -> None:
    report = {
        "issues": [
            {"block_index": 2, "rule_id": "R", "suggestion": " Fix "},
            {"line": 3, "rule": "S", "replacement": "Other"},
        ]
    }
    assert _issue_keys(report) == {(2, "R", "fix"), (3, "S", "other")}


def test_cache_key_changes_across_pipeline_and_ablation_versions(monkeypatch) -> None:
    monkeypatch.setenv("PIPELINE_VERSION", "v1")
    monkeypatch.setenv("PIPELINE_V2_STAGES", "")
    first = llm_client._cache_key("system", "user")
    monkeypatch.setenv("PIPELINE_VERSION", "v2")
    second = llm_client._cache_key("system", "user")
    monkeypatch.setenv("PIPELINE_V2_STAGES", "language,verifier")
    third = llm_client._cache_key("system", "user")
    assert len({first, second, third}) == 3


def test_token_usage_is_attributed_to_worker(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(usage_stats, "DB_FILE", tmp_path / "stats.db")
    usage_stats._init_db()
    usage_stats.set_context("eval", "job")
    token = usage_stats.set_worker("Язык")
    try:
        usage_stats.record_tokens(10, 3)
    finally:
        usage_stats.reset_worker(token)
    totals = usage_stats.job_token_usage("job")
    assert totals["tokens"] == 13
    assert totals["by_worker"]["Язык"]["calls"] == 1


def test_plain_text_list_keeps_introduction_and_items() -> None:
    document = parse_txt(
        "Учитываются такие признаки:\n\n"
        "- адрес источника;\n"
        "- частота запросов."
    )
    assert [block.metadata["type"] for block in document.blocks] == [
        "paragraph",
        "list_item",
        "list_item",
    ]
    assert document.blocks[0].metadata["introduces_list"] == 1
    assert document.blocks[1].metadata["list_intro_index"] == 0


def test_verifier_failure_marks_partial_and_does_not_publish_unverified(
    monkeypatch,
) -> None:
    guide = StyleGuide(
        id="test",
        name="Test",
        rules=[{
            "rule_id": "Test.Rule",
            "title": "Rule",
            "rule": "Policy",
            "machine_verifiable": False,
        }],
    )
    document = Document([
        Block(0, "source", "source", {"type": "paragraph"})
    ], source="test")
    candidate = {
        "block_index": 0,
        "type": "style",
        "severity": "suggestion",
        "rule_id": "Test.Rule",
        "reasoning": "reason",
        "description": "candidate",
        "suggestion": "fixed",
        "span_text": "source",
        "source_workers": [1],
        "evidence_source": "llm",
        "verification_required": True,
    }

    monkeypatch.setenv("PIPELINE_V2_STAGES", "language,verifier")
    monkeypatch.setattr(pipeline_v2.rag, "ensure_index", lambda _guide: None)
    monkeypatch.setattr(
        pipeline_v2,
        "_retrieve_batch",
        lambda texts, _guide, task, k: ([[] for _ in texts], {"task": task}),
    )

    async def no_evidence(_document, _guide):
        return []

    async def finder(*_args, **_kwargs):
        return [candidate]

    async def empty_finder(*_args, **_kwargs):
        return []

    async def failed_verifier(*_args, **_kwargs):
        raise RuntimeError("verifier unavailable")

    monkeypatch.setattr(pipeline_v2, "collect_engine_evidence", no_evidence)
    monkeypatch.setattr(pipeline_v2, "worker_language", finder)
    monkeypatch.setattr(pipeline_v2, "worker_guide_local", empty_finder)
    monkeypatch.setattr(pipeline_v2, "worker_verifier", failed_verifier)

    report = asyncio.run(pipeline_v2.run_pipeline_v2(document, guide))

    assert report["partial"] is True
    assert report["meta"]["complete"] is False
    assert report["issues"] == []
    assert report["meta"]["candidates"] == 1
    assert report["meta"]["failed_passes"][0]["worker"] == "Верификатор"


def test_pass_error_message_for_timeout() -> None:
    assert "таймаут прохода" in pipeline_v2._pass_error_message(asyncio.TimeoutError())


def test_retry_pass_recovers_after_timeout(monkeypatch) -> None:
    attempts = {"count": 0}

    async def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise asyncio.TimeoutError
        return "ok"

    monkeypatch.setattr(pipeline_v2, "PASS_RETRIES", 1)
    monkeypatch.setattr(pipeline_v2, "PASS_TIMEOUT", 5.0)

    result = asyncio.run(pipeline_v2._retry_pass(
        flaky,
        worker_name="Язык",
        scope="фрагмент 1 из 1",
    ))
    assert result == "ok"
    assert attempts["count"] == 2


def test_retry_pass_does_not_retry_non_retriable(monkeypatch) -> None:
    attempts = {"count": 0}

    async def broken() -> str:
        attempts["count"] += 1
        raise ValueError("logic bug")

    monkeypatch.setattr(pipeline_v2, "PASS_RETRIES", 2)

    try:
        asyncio.run(pipeline_v2._retry_pass(
            broken,
            worker_name="Язык",
            scope="фрагмент 1 из 1",
        ))
    except ValueError as exc:
        assert str(exc) == "logic bug"
    else:
        raise AssertionError("expected ValueError")
    assert attempts["count"] == 1
