# Individual Report: Lab 3 - Chatbot vs ReAct Agent

- **Student Name**: Phung Huu Phu
- **Student ID**: 2A202600283
- **Date**: 2026-04-06

---

## I. Technical Contribution (15 Points)

*Describe your specific contribution to the codebase (e.g., implemented a specific tool, fixed the parser, etc.).*

- **Modules implemented**
  - `chatbot.py` — One-shot baseline using `LLMProvider` from `.env` (`openai` / `google` / `local`). For `--demo`, a stricter system prompt forces a comparable line `FINAL_ESTIMATE_USD: …`, and stderr prints **mock-tool ground truth** (same `ecommerce` functions the agent uses) so the chatbot run can be compared numerically to the agent without the chatbot ever calling tools. `build_llm_for_provider()` supports provider benchmarks.
  - `src/tools/web_tools.py` + `src/tools/registry.py` — Bonus **web_search** (DuckDuckGo + fallback) and **wikipedia_search** (MediaWiki API with `User-Agent`), merged with e-commerce tools for `get_tool_specs_for_prompt` / `dispatch_tool`.
  - `src/tools/ecommerce.py` — Five mock e-commerce tools: `check_stock`, `get_discount`, `calc_shipping`, `calc_line_total`, `apply_vat`, with fixed catalog/coupons/shipping/VAT. Prompt-facing registry is `src/tools/registry.py` (e-commerce + web tools).
  - `src/agent/agent.py` — Full ReAct loop: scratchpad (`Task` + assistant turns + `Observation:`), **v1 vs v2** system prompts (`agent_version`), parsing for `Final Answer:` vs `Action: tool({JSON})`, balanced-parenthesis extraction for JSON args, label normalization for markdown, `_execute_tool` → `dispatch_tool`, optional **v2 duplicate-action guard**, telemetry via `logger.log_event` (`AGENT_START`, `LLM_STEP`, `TOOL_RESULT`, `PARSE_ERROR`, `DUPLICATE_ACTION_BLOCKED`, `AGENT_END` with parse/tool/duplicate counts).
  - `src/agent/__init__.py` — Exports `ReActAgent`, `AgentVersion`.
  - `run_agent.py` — CLI: `build_llm_from_env()`, `get_tool_specs_for_prompt()` from `registry`, `ReActAgent.run()`, `--version v1|v2`.
  - `compare_providers.py` — Same task across providers and/or v1 vs v2; aggregates **sum of `latency_ms`** per run and **tokens** from each `generate()` `usage` (for group report tables).

- **Code highlights**
  - Parser hardening: `_normalize_react_labels()` maps `**Action:**` / `**Final Answer:**` (and similar) to plain labels so GPT-style markdown does not break the loop; optional backticks around tool calls are handled where applicable.
  - Tool arguments: JSON-first parsing with fallbacks (`ast.literal_eval`, string fallbacks for simple tools).

- **Documentation / interaction with the ReAct loop**
  - The agent never calls Python tools directly from free-form reasoning; it parses the model’s `Action:` line, runs `dispatch_tool(name, dict_args)`, and appends `Observation: …`. The next `llm.generate()` call conditions on **real tool output**, which is the core difference from the single-turn chatbot. See also `report/FAILURE_ANALYSIS_AND_V2.md` for trace-based rationale for Agent v2.

---

## II. Debugging Case Study (10 Points)

*Analyze a specific failure event you encountered during the lab using the logging system.*

- **Problem description**  
  Running `run_agent.py --demo`, the agent never reached `TOOL_RESULT` or a final answer. Every step logged `PARSE_ERROR` with hint `missing_action_and_final`, while `LLM_STEP`’s `response_preview` clearly contained a valid tool call, e.g.  
  `**Action:** check_stock({"item_name": "iPhone"})`.  
  The agent repeated the same intent until `max_steps`, burning tokens without executing tools.

- **Log source**  
  Structured JSON lines in `logs/2026-04-06.log` (project root `logs/`). Example pattern:  
  `event: "LLM_STEP"` with `response_preview` showing `**Action:** …`, immediately followed by `event: "PARSE_ERROR"` and the same preview truncated in `data.preview`.

- **Diagnosis**  
  The failure was **not** missing data (mock catalog was fine) and **not** the API refusing tools. The regex expected a literal `Action:` prefix, while the model emitted markdown-bold `**Action:**`. The parser therefore saw “no Action line” and “no Final Answer,” even though the semantic content was correct (**EVALUATION.md**: parser / format failure; wasted loops and tokens).

- **Solution**  
  1. **Normalize labels** before parsing (`**Thought:**` / `**Action:**` / `**Final Answer:**` → plain labels).  
  2. **Agent v2 system prompt**: few-shot, explicit “WRONG: **Action:**”, checkout ordering, plain-label rules.  
  3. **Relax the action regex** slightly for optional backticks after `Action:`.  
  4. **v2**: duplicate `Action` + same JSON after a successful observation → synthetic observation + `DUPLICATE_ACTION_BLOCKED` log.  
  After this, logs should show `TOOL_RESULT` with `observation_preview`, then `AGENT_END` with `outcome: final_answer`.

---

## III. Personal Insights: Chatbot vs ReAct (10 Points)

*Reflect on the reasoning capability difference.*

1. **Reasoning**  
   The chatbot answers in one shot from parametric knowledge; it may sound plausible but is not bound to our store’s prices, coupons, or shipping rules. The agent’s **Thought** steps make the model’s intermediate intent visible and encourage a **plan** (e.g. price → discount → line total → shipping → VAT). Even when imperfect, that structure makes errors easier to trace in the scratchpad and logs.

2. **Reliability**  
   The agent can perform **worse** than the chatbot when: parsing fails, the model loops or calls the wrong tool, or `max_steps` is exceeded—cost and latency are higher than a single completion. For **trivial** chit-chat or questions that need no grounded numbers, a one-turn chatbot is faster and “good enough.”

3. **Observation**  
   **Observation** is the bridge between LLM and environment: each JSON string from `dispatch_tool` becomes facts the model must reconcile on the next turn (e.g. `unit_price_usd`, `discount_percent`). Good runs show the model updating its plan after an observation; bad runs show ignored observations or repeated identical actions—both are visible in `logs/` and in the scratchpad.

*Lab tie-in:* On the demo checkout task, the chatbot’s `FINAL_ESTIMATE_USD:` line (stderr ground truth vs model) illustrates **ungrounded** vs tool-backed totals once `TOOL_RESULT` / `Final Answer` align with catalog math.

---

## IV. Future Improvements (5 Points)

*How would you scale this for a production-level AI agent system?*

- **Scalability**  
  Replace ad-hoc string scratchpads with a **state graph** (e.g. LangGraph) and optionally **async** tool execution for I/O-bound tools. For many tools, add **retrieval** over tool descriptions instead of stuffing all specs into one system prompt.

- **Safety**  
  Add a **policy layer**: allow-list tool names and argument schemas (e.g. Pydantic), cap steps and spend, sanitize user input, and optionally a **second model** or rules engine to audit `Action` before execution.

- **Performance**  
  Wire `src/telemetry/metrics.py` (`PerformanceTracker.track_request`) into every `LLM_STEP` so **cost_estimate** and token rollups are automatic for dashboards; tune prompts to shorten Thoughts; cache idempotent tool results.

- **RAG / multi-agent**  
  For production checkout or support, combine this pattern with **retrieval** over product/policy docs, and **specialist agents** (e.g. inventory vs billing) coordinated by a supervisor with shared trace logging.

---

> [!NOTE]
> Submit by renaming to `REPORT_[YOUR_NAME].md` or `individual_report.md` per course instructions.
