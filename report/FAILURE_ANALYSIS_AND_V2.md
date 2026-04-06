# Failure analysis → Agent v2 (for group report)

## Observed failure (v1-style trace)

- **Symptom:** Repeated `PARSE_ERROR` in `logs/*.log` while `LLM_STEP.response_preview` showed a valid tool call.
- **Example pattern:** Model emitted `**Action:** check_stock({"item_name": "iPhone"})` (markdown-bold label). Parser required `Action:` → no match → no `TOOL_RESULT` → same intent retried until `max_steps`.
- **Metric angle (EVALUATION.md):** JSON/parser-style failure; wasted **loop count** and **tokens**; **latency** scaled with useless steps.

## v2 mitigations (evidence-based, not random prompting)

| Change | Rationale |
|--------|-----------|
| **v2 system prompt** | Few-shot trace; explicit “WRONG: **Action:**”; checkout tool order; plain-label rules. |
| **Parser (existing)** | `_normalize_react_labels` + optional backticks — handles markdown the model still emits. |
| **Runtime guard (v2 only)** | If same `tool` + JSON args repeats after a **successful** observation → synthetic `duplicate_action` observation + `DUPLICATE_ACTION_BLOCKED` log (stops “spin” on one step). |
| **Tool copy** | Clearer `apply_vat` description: amount = line + shipping when tax is on full checkout. |
| **Telemetry** | `AGENT_START` / `AGENT_END` include `agent_version`, `parse_errors`, `tool_calls`, `duplicate_actions`. |

## How to reproduce numbers for the report

```bash
# Same task, v1 vs v2 on DEFAULT_PROVIDER (OpenAI if configured)
python compare_providers.py --demo --both-versions

# Latency + tokens: OpenAI vs Gemini (both keys in .env)
python compare_providers.py --demo --providers openai,google --version v2
```

Paste the printed markdown table into the group report (Evaluation & Ablation sections).
