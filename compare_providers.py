"""
Compare LLM providers and/or agent versions on the same task (latency + tokens from generate()).

Examples:
  python compare_providers.py --demo
  python compare_providers.py --demo --providers openai,google
  python compare_providers.py --demo --both-versions
  python compare_providers.py "Your task" --version v1

Requires API keys in .env (OPENAI_API_KEY, GEMINI_API_KEY as needed).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from chatbot import build_llm_for_provider  # noqa: E402
from src.agent.agent import AgentVersion, ReActAgent  # noqa: E402
from src.tools.registry import get_tool_specs_for_prompt  # noqa: E402

DEMO_TASK = (
    "I want to buy 2 iPhones using coupon code WINNER and ship to Hanoi. "
    "Assume each iPhone weighs 0.24 kg for shipping. What is my total in USD "
    "including 10% VAT for Vietnam?"
)


def _aggregate_run(agent: ReActAgent) -> dict:
    lat = sum((h.get("latency_ms") or 0) for h in agent.history)
    pt = sum((h.get("usage") or {}).get("prompt_tokens") or 0 for h in agent.history)
    ct = sum((h.get("usage") or {}).get("completion_tokens") or 0 for h in agent.history)
    return {
        "steps": len(agent.history),
        "total_latency_ms": lat,
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": pt + ct,
        "parse_errors": agent.parse_error_count,
        "tool_calls": agent.tool_call_count,
        "duplicate_actions": agent.duplicate_action_count,
    }


def run_case(provider: str, task: str, version: AgentVersion) -> tuple[str, dict]:
    llm = build_llm_for_provider(provider)
    agent = ReActAgent(
        llm,
        get_tool_specs_for_prompt(),
        max_steps=12,
        agent_version=version,
    )
    t0 = time.perf_counter()
    answer = agent.run(task)
    wall_ms = int((time.perf_counter() - t0) * 1000)
    m = _aggregate_run(agent)
    m["wall_clock_ms"] = wall_ms
    m["model"] = getattr(llm, "model_name", provider)
    return answer, m


def main() -> None:
    load_dotenv(os.path.join(_ROOT, ".env"))
    parser = argparse.ArgumentParser(description="Provider / agent-version benchmark")
    parser.add_argument("question", nargs="?", default=None)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--version", choices=("v1", "v2"), default="v2")
    parser.add_argument(
        "--both-versions",
        action="store_true",
        help="Run v1 then v2 on DEFAULT_PROVIDER only (for rubric v1 vs v2 table).",
    )
    parser.add_argument(
        "--providers",
        default=None,
        help="Comma-separated: openai,google. Default: every provider with an API key.",
    )
    args = parser.parse_args()

    task = DEMO_TASK if args.demo else (args.question or "").strip()
    if not task:
        print("Provide --demo, a question string, or stdin.", file=sys.stderr)
        sys.exit(1)

    if args.both_versions:
        p = os.getenv("DEFAULT_PROVIDER", "openai").strip().lower()
        if p in ("gemini",):
            p = "google"
        if p not in ("openai", "google", "local"):
            p = "openai"
        rows = []
        for ver in ("v1", "v2"):
            if p == "local":
                print("Skipping --both-versions with local (slow); use openai/google.", file=sys.stderr)
                break
            try:
                ans, m = run_case(p, task, ver)
            except Exception as e:
                print(f"{p} {ver} FAILED: {e}", file=sys.stderr)
                continue
            rows.append((f"{p}+{ver}", ans, m))
        _print_table(rows)
        return

    if args.providers:
        plist = [x.strip().lower() for x in args.providers.split(",") if x.strip()]
    else:
        plist = []
        if os.getenv("OPENAI_API_KEY"):
            plist.append("openai")
        if os.getenv("GEMINI_API_KEY"):
            plist.append("google")
        if not plist:
            print("No OPENAI_API_KEY or GEMINI_API_KEY in .env; set --providers or keys.", file=sys.stderr)
            sys.exit(1)

    rows = []
    for p in plist:
        if p == "gemini":
            p = "google"
        try:
            ans, m = run_case(p, task, args.version)
        except Exception as e:
            print(f"{p} FAILED: {e}", file=sys.stderr)
            continue
        rows.append((f"{p}+{args.version}", ans, m))
    _print_table(rows)


def _print_table(rows: list[tuple[str, str, dict]]) -> None:
    print("\n### Benchmark (same task)\n")
    print(
        "| Run | steps | tool_calls | parse_err | dup_action | sum(latency_ms)* | wall_ms | prompt_tok | compl_tok |"
    )
    print("|:---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for label, ans, m in rows:
        print(
            f"| {label} | {m['steps']} | {m['tool_calls']} | {m['parse_errors']} | "
            f"{m['duplicate_actions']} | {m['total_latency_ms']} | {m['wall_clock_ms']} | "
            f"{m['prompt_tokens']} | {m['completion_tokens']} |"
        )
    print(
        "\n*sum(latency_ms) = per-LLM-call latency from `generate()` (EVALUATION.md: loop latency).\n"
    )
    for label, ans, m in rows:
        preview = (ans or "").replace("\n", " ")[:240]
        print(f"**{label}** answer preview: {preview}\n")


if __name__ == "__main__":
    main()
