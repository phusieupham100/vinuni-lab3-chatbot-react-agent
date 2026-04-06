import ast
import json
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from src.core.llm_provider import LLMProvider
from src.telemetry.logger import logger
from src.tools.registry import dispatch_tool, get_tool_by_name

AgentVersion = Literal["v1", "v2"]


class ReActAgent:
    """
    ReAct-style agent: Thought -> Action -> Observation until Final Answer or max_steps.

    v1: minimal system prompt (baseline for rubric / failure comparison).
    v2: few-shot + checkout ordering + anti-repeat; targets markdown label parse failures
        and duplicate tool calls seen in lab traces (compare logs before/after).
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: List[Dict[str, Any]],
        max_steps: int = 8,
        agent_version: AgentVersion = "v2",
    ):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.agent_version: AgentVersion = agent_version
        self.history: List[Dict[str, Any]] = []
        self.parse_error_count = 0
        self.tool_call_count = 0
        self.duplicate_action_count = 0

    def _tools_block(self) -> str:
        tool_lines: List[str] = []
        for t in self.tools:
            block = f"  - **{t['name']}**: {t['description'].strip()}"
            args = t.get("args")
            if args:
                block += f"\n    Arguments (JSON object keys): {args}"
            tool_lines.append(block)
        return "\n".join(tool_lines)

    def get_system_prompt(self) -> str:
        allowed = ", ".join(f"`{t['name']}`" for t in self.tools)
        tools_block = self._tools_block()
        if self.agent_version == "v1":
            return self._system_prompt_v1(allowed, tools_block)
        return self._system_prompt_v2(allowed, tools_block)

    def _system_prompt_v1(self, allowed: str, tools_block: str) -> str:
        """Minimal instructions (closer to first lab iteration; easier to break on markdown)."""
        return f"""You are a reasoning assistant with tools.
Use only these tool names: {allowed}.

### Tools
{tools_block}

Each turn write:
Thought: ...
Then Action: tool_name({{"key": "value", ...}}) with valid JSON (double quotes), OR Final Answer: ...
Do not write Observation: yourself."""

    def _system_prompt_v2(self, allowed: str, tools_block: str) -> str:
        """Improved from traces: explicit format, few-shot, ordering, no duplicate calls."""
        return f"""You are a reasoning assistant that MUST solve tasks by calling tools when needed.
You may ONLY use these tool names: {allowed}. Do NOT invent tools or alternate spellings.

### Available tools
{tools_block}

### Output format (every reply — use these plain labels exactly, no **bold** around label names)
1. Start with Thought: (one short reasoning step)
2. Then EITHER:
   - Action: tool_name({{...JSON arguments using the keys listed above...}})
   - OR Final Answer: (your complete answer; plain text or numbers)

Rules:
- Use valid JSON inside the parentheses (double quotes for strings).
- Example: Action: check_stock({{"item_name": "iphone"}})
- Do not wrap labels in **asterisks** and do not wrap the tool call in backticks (parsing fails otherwise).
- Do NOT write Observation: yourself; the system appends it after each Action.
- If you have enough information, use Final Answer: and stop.

### Few-shot (correct pattern)
Thought: I need the unit price from inventory.
Action: check_stock({{"item_name": "iphone"}})
(… system appends Observation …)
Thought: I have unit_price_usd; next I need the coupon discount percent.
Action: get_discount({{"coupon_code": "WINNER"}})

### Common mistakes (from lab traces — avoid)
- WRONG: **Action:** check_stock(...)  → labels must be plain Action: not markdown-bold.
- WRONG: Repeating the same Action with the same JSON after a successful Observation → read the Observation and call the NEXT tool or answer.
- For totals with tax: typical order check_stock → get_discount → calc_line_total → calc_shipping → apply_vat(amount_usd = line_total + shipping_usd) → Final Answer."""

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        t = text.strip()
        t = re.sub(r"^```(?:json|JSON)?\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
        return t.strip()

    @staticmethod
    def _normalize_react_labels(text: str) -> str:
        """
        Models often emit **Thought:** / **Action:** / **Final Answer:** while the
        parser expects plain labels. Strip optional markdown bold around them.
        """
        t = text
        t = re.sub(r"(?im)^\s*\*{1,2}\s*Thought\s*\*{1,2}\s*:", "Thought:", t)
        t = re.sub(r"(?im)^\s*\*{1,2}\s*Action\s*\*{1,2}\s*:", "Action:", t)
        t = re.sub(r"(?im)^\s*\*{1,2}\s*Final\s+Answer\s*\*{1,2}\s*:", "Final Answer:", t)
        # Same labels mid-line (e.g. after a blank line)
        t = re.sub(r"(?i)\*{1,2}\s*Thought\s*\*{1,2}\s*:", "Thought:", t)
        t = re.sub(r"(?i)\*{1,2}\s*Action\s*\*{1,2}\s*:", "Action:", t)
        t = re.sub(r"(?i)\*{1,2}\s*Final\s+Answer\s*\*{1,2}\s*:", "Final Answer:", t)
        # Underscore bold (__Action__:)
        t = re.sub(r"(?i)__\s*Thought\s*__\s*:", "Thought:", t)
        t = re.sub(r"(?i)__\s*Action\s*__\s*:", "Action:", t)
        t = re.sub(r"(?i)__\s*Final\s+Answer\s*__\s*:", "Final Answer:", t)
        return t

    @staticmethod
    def _unwrap_action_backticks(text: str) -> str:
        """Turn Action: `tool({...})` into Action: tool({...})."""
        return re.sub(
            r"(?is)Action:\s*`([a-zA-Z_][a-zA-Z0-9_]*\s*\([^`]*\))`",
            r"Action: \1",
            text,
        )

    @staticmethod
    def _extract_final_answer(text: str) -> Optional[str]:
        m = re.search(r"(?is)Final Answer:\s*(.*)", text)
        if not m:
            return None
        ans = m.group(1).strip()
        ans = ReActAgent._strip_code_fences(ans)
        return ans if ans else None

    @staticmethod
    def _extract_action(text: str) -> Optional[Tuple[str, str]]:
        m = re.search(
            r"(?is)Action:\s*`?\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*`?\s*\(",
            text,
        )
        if not m:
            return None
        tool = m.group(1)
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth:
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return tool, text[start:i].strip()
            i += 1
        return None

    def _parse_tool_arguments(self, tool_name: str, raw: str) -> Dict[str, Any]:
        s = self._strip_code_fences(raw).strip()
        if not s:
            return {}

        if s.startswith("{") and s.endswith("}"):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                try:
                    return json.loads(s.replace("'", '"'))
                except json.JSONDecodeError:
                    pass

        try:
            val = ast.literal_eval(s)
            if isinstance(val, dict):
                return val
            if tool_name == "check_stock" and isinstance(val, str):
                return {"item_name": val}
            if tool_name == "get_discount" and isinstance(val, str):
                return {"coupon_code": val}
        except (SyntaxError, ValueError, TypeError):
            pass

        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass

        # Last-resort string fallbacks
        if tool_name == "check_stock":
            return {"item_name": s.strip("'\"")}
        if tool_name == "get_discount":
            return {"coupon_code": s.strip("'\"")}
        return {}

    def _execute_tool(self, tool_name: str, args: str) -> str:
        if not get_tool_by_name(tool_name):
            allowed = [t["name"] for t in self.tools]
            return json.dumps({"error": "unknown_tool", "got": tool_name, "allowed": allowed})
        try:
            parsed = self._parse_tool_arguments(tool_name, args)
        except Exception as e:
            return json.dumps({"error": "parse_arguments_failed", "detail": str(e), "raw": args[:500]})
        return dispatch_tool(tool_name, parsed)

    def run(self, user_input: str) -> str:
        self.parse_error_count = 0
        self.tool_call_count = 0
        self.duplicate_action_count = 0
        self.history.clear()

        logger.log_event(
            "AGENT_START",
            {
                "input": user_input,
                "model": getattr(self.llm, "model_name", ""),
                "agent_version": self.agent_version,
            },
        )

        scratch: List[str] = [f"Task:\n{user_input.strip()}"]
        steps = 0
        system_prompt = self.get_system_prompt()

        while steps < self.max_steps:
            prompt = "\n\n".join(scratch)
            result = self.llm.generate(prompt, system_prompt=system_prompt)
            raw = result.get("content") or ""
            usage = result.get("usage")
            latency_ms = result.get("latency_ms")

            logger.log_event(
                "LLM_STEP",
                {
                    "step": steps,
                    "usage": usage,
                    "latency_ms": latency_ms,
                    "response_preview": raw[:800],
                },
            )

            self.history.append(
                {
                    "step": steps,
                    "assistant_raw": raw,
                    "usage": usage,
                    "latency_ms": latency_ms,
                }
            )

            parsed_text = self._unwrap_action_backticks(
                self._normalize_react_labels(self._strip_code_fences(raw))
            )

            final_ans = self._extract_final_answer(parsed_text)
            if final_ans is not None:
                logger.log_event(
                    "AGENT_END",
                    {
                        "steps": steps + 1,
                        "outcome": "final_answer",
                        "usage_last": usage,
                        "agent_version": self.agent_version,
                        "parse_errors": self.parse_error_count,
                        "tool_calls": self.tool_call_count,
                        "duplicate_actions": self.duplicate_action_count,
                    },
                )
                return final_ans

            action = self._extract_action(parsed_text)
            if action:
                tool_name, args_str = action
                dup = False
                if self.agent_version == "v2" and len(self.history) >= 2:
                    prev = self.history[-2]
                    if (
                        prev.get("tool") == tool_name
                        and prev.get("args") == args_str
                        and "error" not in (prev.get("observation") or "").lower()
                    ):
                        dup = True

                if dup:
                    self.duplicate_action_count += 1
                    observation = json.dumps(
                        {
                            "error": "duplicate_action",
                            "message": (
                                "Same tool+arguments as your last successful step. "
                                "Read the previous Observation and proceed with the next tool "
                                "or Final Answer."
                            ),
                        }
                    )
                    logger.log_event(
                        "DUPLICATE_ACTION_BLOCKED",
                        {
                            "step": steps,
                            "tool": tool_name,
                            "args_preview": args_str[:300],
                        },
                    )
                else:
                    observation = self._execute_tool(tool_name, args_str)
                    self.tool_call_count += 1

                logger.log_event(
                    "TOOL_RESULT",
                    {
                        "step": steps,
                        "tool": tool_name,
                        "args_preview": args_str[:500],
                        "observation_preview": observation[:800],
                        "duplicate": dup,
                    },
                )
                scratch.append(raw.strip())
                scratch.append(f"Observation: {observation}")
                self.history[-1]["tool"] = tool_name
                self.history[-1]["args"] = args_str
                self.history[-1]["observation"] = observation
            else:
                self.parse_error_count += 1
                hint = (
                    "Observation: No valid Action line found. "
                    "Reply with Thought:, then Action: tool_name({JSON}) using only allowed tools, "
                    "or Final Answer: if done."
                )
                logger.log_event(
                    "PARSE_ERROR",
                    {
                        "step": steps,
                        "hint": "missing_action_and_final",
                        "preview": raw[:500],
                        "agent_version": self.agent_version,
                    },
                )
                scratch.append(raw.strip())
                scratch.append(hint)

            steps += 1

        logger.log_event(
            "AGENT_END",
            {
                "steps": steps,
                "outcome": "max_steps",
                "agent_version": self.agent_version,
                "parse_errors": self.parse_error_count,
                "tool_calls": self.tool_call_count,
                "duplicate_actions": self.duplicate_action_count,
            },
        )
        return (
            "Agent stopped after max_steps without a Final Answer. "
            "Check logs for traces or increase max_steps."
        )
