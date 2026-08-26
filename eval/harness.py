"""
Eval harness for eval/prompts/*.yaml suites. Runs each case's prompt
through the gateway, applies deterministic `must_contain` substring
checks, and reports pass/fail — the systematic version of what caught
the real bug in Phase 1: a real Qwen2.5-3B-Instruct-AWQ run described
PagedAttention as an access-control mechanism instead of KV-cache memory
management (see docs/BENCHMARKS.md). `pagedattention_explanation` in
basic_suite.yaml exists specifically to catch that exact regression
automatically instead of by accident.

This is NOT a CI quality gate. Running it against the mock backend (as
CI does, see .github/workflows/ci.yml) is expected to fail every
must_contain check — the mock backend's canned text was never meant to
contain real answers. The point of that CI run is proving the harness
itself works end-to-end, not that mock passes an eval it can't pass.

LLM-as-judge scoring (rubric-based, subjective quality) is intentionally
NOT implemented here — every case's `rubric` field exists for a future
pass, likely using an independent judge model rather than having a model
grade its own output (a real methodological weakness worth naming rather
than hiding behind an unqualified "eval score"). Tracked in
docs/ROADMAP.md, not silently skipped.

Usage:
    python eval/harness.py --gateway-url http://localhost:8000 \
        --suite eval/prompts/basic_suite.yaml \
        --output eval/results/run.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
import yaml


@dataclass
class EvalResult:
    case_id: str
    prompt: str
    response_text: str
    must_contain: list[str]
    passed: bool
    missing: list[str]
    latency_ms: float
    error: str | None = None


def load_suite(path: str | Path) -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f)


def check_must_contain(text: str, must_contain: list[str]) -> tuple[bool, list[str]]:
    """
    Pure, network-free scoring logic — the part that's directly unit
    testable without a live gateway. Case-insensitive substring match;
    an empty must_contain list always passes (that case has no
    deterministic check, only a rubric for a human/judge to apply later).
    Returns (passed, missing_substrings).
    """
    if not must_contain:
        return True, []
    text_lower = text.lower()
    missing = [s for s in must_contain if s.lower() not in text_lower]
    return len(missing) == 0, missing


async def run_case(client: httpx.AsyncClient, gateway_url: str, case: dict,
                    max_tokens: int = 128) -> EvalResult:
    prompt = case["prompt"]
    must_contain = case.get("must_contain", [])

    try:
        resp = await client.post(
            f"{gateway_url}/v1/completions",
            json={"prompt": prompt, "max_tokens": max_tokens},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["text"]
        passed, missing = check_must_contain(text, must_contain)
        return EvalResult(
            case_id=case["id"],
            prompt=prompt,
            response_text=text,
            must_contain=must_contain,
            passed=passed,
            missing=missing,
            latency_ms=data.get("latency_ms", 0.0),
        )
    except Exception as exc:  # noqa: BLE001 - report the failure as a result, don't crash the run
        return EvalResult(
            case_id=case["id"],
            prompt=prompt,
            response_text="",
            must_contain=must_contain,
            passed=False,
            missing=must_contain,
            latency_ms=0.0,
            error=str(exc),
        )


async def run_suite(gateway_url: str, suite_path: str | Path,
                     max_tokens: int = 128) -> list[EvalResult]:
    cases = load_suite(suite_path)
    async with httpx.AsyncClient() as client:
        return [await run_case(client, gateway_url, case, max_tokens) for case in cases]


def print_summary(results: list[EvalResult]) -> None:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Eval results: {passed}/{total} passed")
    print(f"{'=' * 60}")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.case_id}")
        if not r.passed:
            if r.error:
                print(f"         error: {r.error}")
            elif r.missing:
                print(f"         missing: {r.missing}")
                print(f"         got: {r.response_text[:100]!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-url", default="http://localhost:8000")
    parser.add_argument("--suite", default="eval/prompts/basic_suite.yaml")
    parser.add_argument("--output", default=None, help="Path to write a JSON report")
    parser.add_argument("--max-tokens", type=int, default=128)
    args = parser.parse_args()

    results = asyncio.run(run_suite(args.gateway_url, args.suite, args.max_tokens))
    print_summary(results)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w") as f:
            json.dump([asdict(r) for r in results], f, indent=2)
        print(f"\nWrote report to {output_path}")

    # Deliberately does NOT sys.exit(1) on failures — see module docstring
    # on why this harness reports rather than gates. A non-zero exit here
    # would fail CI's mock-backend smoke test for the wrong reason (mock
    # is SUPPOSED to fail every check).
    sys.exit(0)


if __name__ == "__main__":
    main()
