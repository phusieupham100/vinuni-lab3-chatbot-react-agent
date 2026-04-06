"""Run ReAct agent from project root: python run_agent.py [--demo]"""
import argparse
import os
import sys

from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from chatbot import build_llm_from_env  # noqa: E402
from src.agent.agent import ReActAgent  # noqa: E402
from src.tools.registry import get_tool_specs_for_prompt  # noqa: E402


def main() -> None:
    load_dotenv(os.path.join(_ROOT, ".env"))
    demo = (
        "I want to buy 2 iPhones using coupon code WINNER and ship to Hanoi. "
        "Assume each iPhone weighs 0.24 kg for shipping. What is my total in USD "
        "including 10% VAT for Vietnam?"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default=None)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument(
        "--version",
        choices=("v1", "v2"),
        default="v2",
        help="v1 = minimal prompt; v2 = few-shot + anti-repeat (recommended).",
    )
    args = parser.parse_args()
    q = demo if args.demo else (args.question or input("Task: ").strip())
    if not q:
        return

    llm = build_llm_from_env()
    tools = get_tool_specs_for_prompt()
    agent = ReActAgent(llm, tools, max_steps=12, agent_version=args.version)
    print(agent.run(q))


if __name__ == "__main__":
    main()
