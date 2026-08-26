"""
Tests eval/harness.py's pure, network-free scoring logic. run_case()
itself (which makes a real HTTP call) is exercised live against the
gateway instead — see docs/ROADMAP.md Phase 6 for how, and
eval/results/ for a real run's output once one exists.
"""

from eval.harness import check_must_contain, load_suite


def test_empty_must_contain_always_passes():
    passed, missing = check_must_contain("literally anything at all", [])
    assert passed is True
    assert missing == []


def test_passes_when_all_substrings_present():
    passed, missing = check_must_contain("The capital of France is Paris.", ["Paris"])
    assert passed is True
    assert missing == []


def test_fails_and_reports_missing_substring():
    passed, missing = check_must_contain(
        "PagedAttention is an access-control mechanism.", ["cache"]
    )
    assert passed is False
    assert missing == ["cache"]


def test_case_insensitive_matching():
    passed, missing = check_must_contain("the answer is PARIS", ["paris"])
    assert passed is True
    assert missing == []


def test_requires_all_substrings_present():
    passed, missing = check_must_contain("12 times 7 is 84", ["84", "reasoning"])
    assert passed is False
    assert missing == ["reasoning"]


def test_load_suite_reads_real_yaml_file():
    cases = load_suite("eval/prompts/basic_suite.yaml")
    assert len(cases) >= 5
    ids = [c["id"] for c in cases]
    assert "pagedattention_explanation" in ids
    assert "factual_capital" in ids
