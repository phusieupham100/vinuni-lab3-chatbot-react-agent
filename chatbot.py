"""
Lab baseline: one-shot LLM chat (no tools). Use for Chatbot vs Agent comparison.

Usage:
  python chatbot.py
  python chatbot.py "Your question here"

Requires .env with API keys. Set DEFAULT_PROVIDER to openai, google, or local.
"""
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

# Project root on path
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.core.llm_provider import LLMProvider


def _demo_tool_ground_truth_usd() -> tuple[float, dict]:
    """
    Same mock tools as the agent, run locally (chatbot never calls the LLM with tools).
    Used only so you can compare chatbot estimate vs agent vs catalog math.
    """
    import json

    from src.tools.ecommerce import dispatch_tool

    stock = json.loads(dispatch_tool("check_stock", {"item_name": "iphone"}))
    unit = float(stock["unit_price_usd"])
    disc = json.loads(dispatch_tool("get_discount", {"coupon_code": "WINNER"}))
    pct = float(disc["discount_percent"])
    line = json.loads(
        dispatch_tool(
            "calc_line_total",
            {"unit_price_usd": unit, "quantity": 2, "discount_percent": pct},
        )
    )
    line_total = float(line["line_total_usd"])
    ship = json.loads(
        dispatch_tool(
            "calc_shipping",
            {"weight_kg": 2 * 0.24, "destination_city": "Hanoi"},
        )
    )
    ship_usd = float(ship["shipping_usd"])
    pre_vat = line_total + ship_usd
    tax = json.loads(
        dispatch_tool("apply_vat", {"amount_usd": pre_vat, "country_code": "VN"})
    )
    total = float(tax["total_with_vat_usd"])
    breakdown = {
        "unit_price_usd": unit,
        "discount_percent": pct,
        "line_total_usd": line_total,
        "shipping_usd": ship_usd,
        "pre_vat_usd": round(pre_vat, 2),
        "total_with_vat_usd": total,
    }
    return total, breakdown


def build_llm_from_env() -> LLMProvider:
    load_dotenv(os.path.join(_ROOT, ".env"))
    provider = os.getenv("DEFAULT_PROVIDER", "openai").strip().lower()

    if provider == "openai":
        from src.core.openai_provider import OpenAIProvider

        model = os.getenv("DEFAULT_MODEL", "gpt-4o")
        return OpenAIProvider(model_name=model, api_key=os.getenv("OPENAI_API_KEY"))

    if provider in ("google", "gemini"):
        from src.core.gemini_provider import GeminiProvider

        model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        return GeminiProvider(model_name=model, api_key=os.getenv("GEMINI_API_KEY"))

    if provider == "local":
        from src.core.local_provider import LocalProvider

        path = os.getenv("LOCAL_MODEL_PATH", "./models/Phi-3-mini-4k-instruct-q4.gguf")
        if not os.path.isabs(path):
            path = os.path.normpath(os.path.join(_ROOT, path))
        return LocalProvider(model_path=path)

    raise ValueError(
        f"Unknown DEFAULT_PROVIDER={provider!r}. Use openai, google, or local."
    )


def build_llm_for_provider(provider: str) -> LLMProvider:
    """
    Build a specific backend (for benchmarks). Does not read DEFAULT_PROVIDER.
    provider: openai | google | gemini | local
    """
    load_dotenv(os.path.join(_ROOT, ".env"))
    p = provider.strip().lower()

    if p == "openai":
        from src.core.openai_provider import OpenAIProvider

        model = os.getenv("DEFAULT_MODEL", "gpt-4o")
        return OpenAIProvider(model_name=model, api_key=os.getenv("OPENAI_API_KEY"))

    if p in ("google", "gemini"):
        from src.core.gemini_provider import GeminiProvider

        model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        return GeminiProvider(model_name=model, api_key=os.getenv("GEMINI_API_KEY"))

    if p == "local":
        from src.core.local_provider import LocalProvider

        path = os.getenv("LOCAL_MODEL_PATH", "./models/Phi-3-mini-4k-instruct-q4.gguf")
        if not os.path.isabs(path):
            path = os.path.normpath(os.path.join(_ROOT, path))
        return LocalProvider(model_path=path)

    raise ValueError(f"Unknown provider={provider!r}. Use openai, google, or local.")


SYSTEM_PROMPT = """You are a helpful shop assistant.
Answer in plain language, briefly unless the user asks for detail.
You do NOT have access to inventory, coupons, shipping APIs, or calculators—only general knowledge.
If a question needs exact stock, prices, shipping, or multi-step checkout math, say what you would need and give your best estimate or explain the limitation."""

# Stricter instructions for --demo so the report has a number to compare to the agent.
SYSTEM_PROMPT_DEMO = """You are a helpful shop assistant (baseline chatbot — no tools, no live data).
Use reasonable general-knowledge guesses for prices, discounts, and shipping if needed.
Keep the main answer short (a few sentences).

You MUST end with exactly one extra line in this exact format (no markdown, no words after the number):
FINAL_ESTIMATE_USD: <number>
where <number> is a decimal like 1999.00 (your single best total in USD). If you truly cannot give a number, write:
FINAL_ESTIMATE_USD: unknown"""


DEMO_MULTI_STEP = (
    "I want to buy 2 iPhones using coupon code WINNER and ship to Hanoi. "
    "Assume each iPhone weighs 0.24 kg for shipping. What is my total in USD "
    "including 10% VAT for Vietnam?"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="One-shot chatbot baseline (no tools).")
    parser.add_argument(
        "question",
        nargs="?",
        default=None,
        help="User message. If omitted, prompts interactively.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help=f"Ask the instructor-style multi-step question: {DEMO_MULTI_STEP[:60]}...",
    )
    args = parser.parse_args()

    if args.demo:
        question = DEMO_MULTI_STEP
    elif args.question:
        question = args.question.strip()
    else:
        question = input("You: ").strip()

    if not question:
        print("Empty question.")
        sys.exit(1)

    llm = build_llm_from_env()
    system = SYSTEM_PROMPT_DEMO if args.demo else SYSTEM_PROMPT
    out = llm.generate(question, system_prompt=system)
    print(out["content"])
    print(
        f"\n[latency_ms={out['latency_ms']} usage={out.get('usage')} provider={out.get('provider', llm.model_name)}]",
        file=sys.stderr,
    )
    if args.demo:
        total, br = _demo_tool_ground_truth_usd()
        print(
            "\n--- Mock catalog / tools (NOT seen by this chatbot; compare to run_agent.py --demo) ---",
            file=sys.stderr,
        )
        print(
            f"Ground truth total_with_vat_usd: ${total:.2f} | breakdown: {br}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
