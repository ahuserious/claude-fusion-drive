# Changelog

## Claude Fusion Drive 0.2.2 (Claude Code edition) - 2026-08-05

- Fixed CLI OAuth seats silently returning telemetry instead of an answer. The
  Grok CLI names two envelope fields in camelCase (`structuredOutput`), which
  the extractor did not recognise, so `_is_result_envelope` rejected the
  envelope and the whole payload — cost, session ids, and the model's private
  reasoning — was canonicalised and handed back as the seat's response. Any
  `grok_oauth` seat was affected; direct-HTTP xAI seats were not.

## Claude Fusion Drive 0.2.1 (Claude Code edition) - 2026-08-05

- Added the `codex_cli_oauth` transport and a `codex_oauth` provider, so
  `gpt-5.6-sol` panel/judge/fuser seats can bill the ChatGPT subscription
  through the Codex CLI instead of a metered `OPENAI_API_KEY`. Ships
  `sol-codex-panel`, `sol-codex-judge`, and `sol-codex-fuser`.
- `OPENAI_API_KEY` now joins `ANTHROPIC_API_KEY` and `XAI_API_KEY` in the set
  stripped from every CLI OAuth child process. Without this, a metered key in
  the environment silently overrides the subscription path the seat asked for.
- Codex seats run `codex exec --ignore-user-config` with a read-only sandbox
  and web search disabled. Because Codex has no empty-tool-list switch, their
  route reports `tools_disabled: false` rather than overclaiming.
- Reasoning normalization for Codex: verified against codex-cli 0.144.5, which
  rejects `minimal` for gpt-5.6-sol and accepts none/low/medium/high/xhigh/max.
- Added a `model_fallbacks` map. Fable 5 bills the Claude subscription, so when
  that allowance runs out every seat, profile execution model, and subagent
  driver naming it fails at once; the map redirects the model at each read
  point (default `claude-fable-5` -> `claude-opus-5`, provider prefixes
  preserved) and records the swap on the receipt route and resolved preset.
  The two invariants that pin Fable 5 now accept the declared fallback target
  but still reject any other model.
- Added a status line stack row: panel/judge/fuser as short model badges, the
  models the subagent-review rung actually dispatches (the rung name says
  nothing about what runs), planning mode, active fallback substitutions, and
  running/total fusion seats read from the same panel and ledger state
  `fusion watch` uses.
- Fixed CI, which had been failing since 0.1.4: the workflow ran
  `unittest discover` while thirteen test modules import pytest, which it
  never installed.

## Claude Fusion Drive 0.2.0 (Claude Code edition) - 2026-08-03

- Added seven first-class Claude Dynamic Workflows: `opinion`, `fusion`,
  `auto-validate`, `debate`, `parallel`, `coordinate`, and `best-of-n`.
  Claude's native `/workflows` view now provides phases, live agents, token
  counts, elapsed time, drill-down, pause, stop, restart, and reusable graph
  scripts.
- Added durable `seat_run` graph nodes. A workflow can select a configured
  panel, judge, fuser, or verifier seat by role/index without hardcoding a
  model. Requested and actual model/provider/reasoning, usage, receipt hashes,
  and artifact paths remain explicit. External seats stay tool-free; native
  Claude workflow agents own tools, worktrees, and writes.
- Added one profile/config-bound aggregate ledger per external workflow graph.
  Cross-process call reservations are strict before dispatch while provider
  calls remain parallel; tokens, cost, and approval thresholds latch later
  nodes. Deterministic node identities preserve receipts on resume, and strict
  proxy envelopes prevent a truthy tool-error report from reaching a fuser,
  judge, or deliverer.
- Added validator-first auto-validation with a required baseline RED, persisted
  gate SHA-256, independent before/after hash checks, and bounded repair loops.
  Parallel and coordinated writers use isolated worktrees.
- Replaced raw pretty-printed MCP result text with concise human receipts plus
  bounded `structuredContent`. Oversized evidence still spills to a full JSON
  artifact. Workflow seats retain complete top-level model text without
  duplicating response text or aggregate-ledger entries, and external graph
  edges no longer silently slice model results. Added `job_wait` to collapse
  repeated status/result polling into one bounded call.
- Replaced the dense topology/status chip line with a width-aware two-line
  Fusion Drive status view that consumes Claude's official model, effort,
  1M-context, cost, and duration fields. Added native subagent status rows.
  Removed binary-presence-as-authenticated claims.
- Changed passive orchestration defaults to quiet/manual: automatic fusion-plan
  and subagent review are off, the high preset remains available for explicit
  workflow commands, and the external-seat watcher is opt-in.
- Added a workflow authoring guide and skill covering graph code, external-seat
  proxies, isolation, fail-closed gates, run controls, and the no-mid-run-human
  boundary.

## Claude Fusion Drive 0.1.5 (Claude Code edition) - 2026-08-02

Closes the last three findings from the 2026-08-01 field evaluation.

- **`adversarial_gate` now runs against the Fusion Drive configuration.** It previously delegated straight to the vendored legacy server, whose config universe has no drive gate sets and no OAuth seats and reports drive profile names as "unknown profile". It now routes through `FusionDriveEngine.approval_gate`, sharing the drive gate sets, the hybrid provider registry, and the corrected verdict unwrap. The result keeps the inherited top-level `run_id`/`artifacts_dir`/`gate`/`ledger` and **adds** `verdict`/`artifact_sha256`/`profile`/`engine`. **`profile` now names a Fusion Drive profile** (`maximum-intelligence`, not `maximum_intelligence`); the legacy spelling now fails loudly instead of silently gating against a different config. Still records no lifecycle receipt — `approval_gate` remains the recorded form. `run_status`, `run_abort` and `execution_handoff` intentionally stay on the inherited route: they address engine run directories and return before any config load, which is what keeps `run_abort` working as a kill switch under an invalid drive config.
- **Abandoned workflows are discoverable and closable.** New `workflow_list` (oldest-updated first, with an advisory `stale` flag) and `workflow_abort` (explicit reason plus the current lifecycle hash). `lifecycle_status` gains an `abort` record and a `staleness` view. Staleness is computed at read time and abort is a persisted compare-and-swap transition — a read that wrote would invalidate the very `expected_lifecycle_sha256` it exists to hand back. Aborting appends to the hash chain and deletes nothing; a terminal workflow is never reported stale, and gates recorded after an abort are now rejected (previously the non-transition subagent stages slipped past that check). The expiry window is a module constant rather than configuration, because changing the default config would change `config_sha256` and break resume for every pre-upgrade workflow. The statusline no longer counts aborted workflows as live.
- **The `subagent_pre_execution` gate stage is now part of the documented host contract.** It shipped in all three gate sets but had fired zero times while the other seven stages had all fired. Investigation found the code affordance was never missing — `approval_gate` records any stage under CAS and `approval_gate_start` validates it against the active gate set — so this was a contract gap: the skill only ever told the orchestrator to review subagents *after* completion. The execution checklist now requires a scope gate before each material subagent batch. Tests pin all eight canonical stages as reachable on one workflow and assert the skill names every stage, so config presence, code reachability, and the documented contract can no longer diverge silently.
- The eight canonical stage names are now a single `CANONICAL_GATE_STAGES` constant in `config.py`, pinned by test against lifecycle's own transition table, instead of a literal repeated in `validate_config`.
- Documented that `bench/validate_evidence.py` remains pinned to the inherited profile and config hash, so the benchmark cannot validate the shipped server's identity claims and is not evidence for drive-side changes.
- Full suite: 394 passed, 1 skipped, 425 subtests.

## Claude Fusion Drive 0.1.4 (Claude Code edition) - 2026-08-02

- **Bounded tool responses.** Every MCP result now passes a size guard: a payload over `reporting.max_inline_response_chars` (new, default 24000) is written to `<state>/responses/` and the caller receives a small envelope naming the file, the total size, and the byte size of each top-level section, so it can read back only what it needs. Measured against a real completed job, `job_result` drops from 399,086 characters (~100K tokens) to 392; `workflow_report` from 76,316 to 625; `config_show` from 52,645 to 467. Spilling never emits partial JSON, and a failed write falls back to the full inline payload rather than failing the call.
- **The `reporting` block is now read.** All four flags shipped since 0.1.0 but were referenced by no code, so there was no way to turn any of this output off: `return_mermaid_after_planning`, `return_full_redacted_config_after_planning`, and `return_reasoning_normalization` now gate their sections of `workflow_report`, and `return_updated_report_for_config_proposals` gates the report attached to `config_propose`/`config_approve`/`config_rollback_propose`. Defaults are unchanged, so behaviour only differs once a flag is switched off. `config_hash` and `validation` always survive, because exact-hash approval depends on them.
- **Locks no longer block forever.** `exclusive_lock` polls `LOCK_EX | LOCK_NB` against a deadline (default 120s) and raises the new `LockTimeout` naming the holding pid and how long it has held, instead of blocking indefinitely behind a wedged provider CLI whose own subprocess timeout is 1800s. The holder writes its identity into the lock file.
- **Recycled pids no longer look alive.** Job manifests record `worker_started_at` from the OS at spawn, and `_pid_is_alive` requires both the signal probe and a start-time match, so a crashed worker whose pid was reused is reclaimed instead of appearing to run forever. The probe is best-effort and degrades to the old behaviour when unavailable.
- **Configuration proposals fail loudly.** `propose_config` rejects dotted-path keys (which `deep_merge` would otherwise land as inert top-level junk) and unknown top-level sections. Nested keys stay unrestricted so new profiles and seats are still addable.
- **Human-sim manifests cannot self-contradict.** Recording `all_criteria_evidenced=true` while any scenario has not passed now raises instead of writing a manifest whose evidence flag disagrees with its own pending list.
- **Live seat visibility.** New `fusion watch [job-id] [--once] [--interval <s>]` renders per-seat status, model, and latency from the existing run store. Run as a Claude Code background Bash task it becomes an openable agent-view entry — the only route to seat progress in that pane, since an MCP server cannot register agent-view entries and the host Agent tool cannot target Grok or GPT seats.
- **Hermetic tests.** The runtime-isolation fixture is now `autouse`, so the suite no longer reads the developer's live `~/.claude/claude-fusion-drive/config.json`. It previously passed only in CI, where no runtime config exists; switching the active profile locally broke an unrelated assertion.
- Full suite: 370 passed, 1 skipped, 425 subtests.

## Claude Fusion Drive 0.1.3 (Claude Code edition) - 2026-08-02

- Added the **exaflop-reactor** preset: planning engine `exaflop_reactor` (panel GPT 5.6 sol ×2 xhigh via direct `openai_api` + Fable 5 xhigh, judge Grok 4.5, fuser Fable 5 xhigh) and execution engine `exaflop_mini` (subagents Grok 4.5 xhigh; completed work reviewed by a Grok 4.5 xhigh + GPT 5.6 sol high mini panel with a Grok 4.5 review judge, compressed and reported back to the orchestrator; auto-applies to dynamic workflows at review level `exaflop`). `openai_api` is now enabled by default.
- Intensity ladders in `fusion_ctl.py`: `preset up|down` steps off→low→medium→high; `review up|down` steps off→light→exaflop; `config` opens the plugin configuration. Statusline shows ladder state and the `⁵exa` profile slot.
- Added the user-level `/statusline-dev` skill for iterating on the statusline.
- Statusline readability redesign retained: labeled roles, one mark language, model family chips, colored effort superscripts.

## Claude Fusion Drive 0.1.2 (Claude Code edition) - 2026-08-02

- Added `statusline.py`, a Claude Code statusline showing the active profile, fusion topology (panel/judge/fuser with effective reasoning), provider sign-in state, mini-fuse on/off, live job and workflow status from the runtime dir, Braintrust link state, and configurable numbered profile slots.
- Added the light-duty **mini-fuse** configuration for subagent and adversarial-review summarization: `grok45-mini-panel`/`-judge`/`-fuser` seats (Grok 4.5, low reasoning, small output budgets), engine `mini_fuse`, profile `mini-fuse` with tight budgets, and subagent preset `mini-fuse`; toggled via seat `enabled` flags.
- Added `fusion_ctl.py` (`profile <slot|name>`, `mini-fuse on|off|status`, `slots`, `status`) — profile and mini-fuse changes go through the validated propose/approve configuration flow; hotkey slots live in `<state>/statusline.json`.
- Documented mini-fuse orchestration and statusline usage in the main skill. Claude Code keybindings cannot invoke shell commands, so profile switching uses `fusion_ctl.py` (e.g. a `fusion` shell wrapper or the `!` prompt escape) with the statusline slot legend.

## Claude Fusion Drive 0.1.1 (Claude Code edition) - 2026-08-02

- Fixed the approval-gate verdict nesting bug: `FusionDriveEngine.approval_gate` read `verdict`/`passed` off the orchestrator's wrapper dict instead of the nested gate result, so every gate auto-recorded FAIL — including 2/2 PASS receipts — and live workflows required manual `lifecycle_gate_record` transcription. Verdicts now derive from the inner gate dict (`PASS`, `NEEDS_WORK` when all negative reviewer verdicts are NEEDS_WORK with no deterministic blocks, otherwise `FAIL`). Added `tests/test_engine_gate_contract.py` running `approval_gate` through the real `FusionOrchestrator`, and corrected the engine test fake to the real wrapper shape.
- Cost governance: `_legacy_seat` no longer copies a template's per-model pricing table onto a seat retargeted to a different model (honest unknown instead of billing at the template model's rates), and `approval_threshold_usd` is now enforced by `BudgetTracker` — a deduplicated ledger warning under `hard_stop`/`warn_only`, a `BudgetExceeded` requiring host approval under `approval_then_hard_stop`. OpenRouter usage-cost accounting needs no request opt-in: the current API always returns `usage.cost`, which the response parser already consumes.
- Robustness: `approve_config` compare-and-swap now runs under `proposals/.config.lock` like every other CAS surface, and `subagent_fuse` derives its engine→profile mapping from configuration (preferring the active profile) instead of a hard-coded three-key dict that raised a bare `KeyError` for `xai_claude_oauth`/`subscription_oauth` presets.
- Added `bench/repin.py` to intentionally regenerate the fail-closed artifact pins after deliberate plugin-tree edits, and `scripts/braintrust_export.py` (stdlib-only) exporting jobs, per-seat ledger calls, and workflow gate records as Braintrust project-log events — local JSONL by default, `--upload` via the REST API with `BRAINTRUST_API_KEY`. Job events score on the engine gate receipt and preserve the historical recorded verdict in metadata.
- Full suite for this edition now reports 351 passed, 1 skipped, 425 subtests.

## Claude Fusion Drive 0.1.0 (Claude Code edition) - 2026-07-31

- Ported the host contract from Codex to Claude Code: the `claude_host` execution owner, `claude_code.TaskCreate` goal receipts (legacy `create_goal` lifecycle files remain readable), `.claude-plugin/plugin.json` packaging with the repo-root `.claude-plugin/marketplace.json` marketplace file, and `${CLAUDE_PLUGIN_ROOT}/mcp_server.py` MCP wiring.
- Switched the default active profile to `xai-claude-oauth`: exact Grok 4.5 through the direct xAI API plus Claude subscription OAuth seats, with no OpenRouter involvement. The `openrouter_api` and `openrouter_fusion_api` providers remain configured but ship `enabled: false` and are never a default or silent fallback; the OpenRouter-backed `maximum-intelligence` profile remains opt-in configuration.
- Replaced the GPT-5.6-sol host driver with `claude-fable-5` across host execution settings and subagent presets; the `grok-fusion-drive` preset drives at `max`.
- Reset the edition version to `0.1.0` while preserving the vendored inherited engine at `0.1.4`.
- Verified offline test parity with the upstream baseline of 334 passed, 1 skipped, 425 subtests; the full suite for this edition reports 345 passed, 1 skipped, 425 subtests.
- Marked the inherited benchmark and release evidence (Terminal-Bench, DeepSWE, direct-xAI receipts) as produced by the Codex edition and not yet re-run for this edition; no new benchmark results are claimed.

Entries below this line are inherited history from the Codex-hosted lineage.

## Unreleased

- Published a separate, checksummed limited-cost evidence repository with direct-xAI receipts, selected Terminal-Bench and DeepSWE outcomes, opt-in reproduction jigs, and explicit claim boundaries.
- Added a release-evidence matrix and benchmark protocol that keep task reward, fusion-gate verdicts, and current evidence-contract validation separate.
- Documented that the live campaign exercised direct xAI but not OpenRouter, and that one role-diverse Grok 4.5 panel is multi-agent deliberation rather than cross-model diversity.

## Claude Fusion Drive 0.1.2 - 2026-07-31

- Normalized Claude Code JSON output according to its headless contracts: ordinary `result`, canonical `structured_output`, final result envelopes in JSON sequences, and valid bare JSON are accepted, while null, empty, error, and malformed envelopes fail with content-free diagnostics.
- Moved OAuth attempt reservation to the subprocess dispatch boundary and now persists semantic-failure response receipts for timeouts, nonzero exits, and unusable output, with unknown cost and explicit usage completeness.
- Removed both `ANTHROPIC_API_KEY` and `XAI_API_KEY` from every OAuth child while retaining protected prompts, disabled tools/web/memory/subagents, provider locks, and no automatic ambiguous retry.
- Added the explicit `xai-claude-oauth` profile: two direct xAI Grok 4.5 panel personas, direct xAI Grok judge and serialized reviewers, Claude Fable 5 OAuth panel/fuser roles, and host-owned GPT-5.6-sol execution at `xhigh` after exact-plan confirmation.
- Extended doctor with API-environment-reference presence and `auth_value_accessed: false`, made a missing required API reference fail readiness without reading its value, and verified that the hybrid profile has no OpenRouter dependency or fallback.
- Extended profile-aware graphs, reasoning reports, auto-evaluation, topology/accounting coverage, and release identity to `0.1.2` while preserving the inherited engine at `0.1.4` and all prior runtime/cache artifacts.

## Claude Fusion Drive 0.1.1 - 2026-07-31

- Preserved the canonical API-backed `maximum-intelligence` default and added an explicitly selected `subscription-oauth` profile with two independent Grok 4.5 panel personas, Claude Fable 5 panel/fuser roles, a Grok 4.5 judge, and two serialized Grok approval reviewers.
- Corrected Grok CLI OAuth invocation to use a protected `0600` prompt file through `--prompt-file`, while retaining tool, web, memory, subagent, and API-key isolation.
- Preserved truthful `report_unknown` subscription accounting so unknown cost remains unknown without blocking the next call or being rendered as zero.
- Replaced the default lifecycle host tool with `codex_app.create_thread`, added project/thread guidance to host skills, and retained compatibility for legacy `create_goal` lifecycle receipts.
- Added durable idempotent `fuse_start` and `approval_gate_start` jobs plus `job_status`, hash-verified `job_result`, and recoverable `job_abort`, with persisted request/config hashes, worker state, sanitized failures, and no automatic redispatch.
- Made doctor, workflow graphs, gate reports, and auto-evaluation profile-aware; added selected-profile binary and host-tool readiness checks that never read credentials.
- Bumped the plugin manifest, runtime, and MCP identity to `0.1.1` and expanded the offline suite for the repaired transport, topology, lifecycle, accounting, reporting, and asynchronous recovery contracts.

## 0.1.4 - 2026-07-19

- Made the shipped maximum-intelligence topology frontier-only: Claude host and native handoff settings use GPT-5.6 Sol, while every direct xAI panel, judge, synthesizer, fallback, and adversarial-review seat uses Grok 4.5 at high effort.
- Removed all automatic Grok 4.3 and GPT-5.6 Terra defaults while preserving provider-neutral schemas and opt-in router configuration.
- Fixed deterministic evidence parsing so shell source echoed after a canonical `$ ` marker cannot be mistaken for the command's actual `[exit N]` result; real nonzero markers and output diagnostics still block.

## 0.1.3 - 2026-07-19

- Bound every host-workspace, command, test, and mutation claim to supplied mechanical evidence and made provider-tool isolation explicit.
- Added a trusted pre-execution plan-review contract that evaluates pending host plans without weakening completed-work evidence gates.
- Hardened the pinned Harbor/Pier benchmark bridge with deterministic resumable run IDs, 30-minute MCP tool timeouts, exact evidence contracts, and fail-fast campaigns.

## 0.1.2 - 2026-07-19

- Made budget recording exception-atomic and detached persisted accounting from mutable response containers.
- Blocked automatic redispatch after an invocation-bound reservation when billability is unknowable, and preflighted native-fallback provenance before additional provider spend.
- Tightened schema-version, canonical JSON, non-finite-number, and durable atomic-write validation.
- Clarified adversarial gate output so planned verification work is not confused with an unresolved blocking blind spot while every genuine blocker remains fail-closed.
- Added pinned, no-oracle Harbor Terminal-Bench 2.0 and Pier DeepSWE acceptance assets and evidence checks.
- Made the MCP entrypoint directly executable for current benchmark harnesses that flatten stdio command arguments.

## 0.1.1 - 2026-07-19

- Hardened provider usage and cost accounting, budget-ledger restoration, concurrent snapshot persistence, and post-response gate stop checks so integrity failures remain fail-closed across resume.
- Added complete short- and long-context fallback pricing for every direct Grok 4.3 and Grok 4.5 seat, with the higher rate tier applied above 200,000 input tokens.
- Added explicit synthesis `mode` and `author_seat` provenance so cached client-orchestrated and native OpenRouter artifacts cannot be confused during author-separation checks.
- Bound every cached panel, judge, synthesis, amendment, and gate result to an exact prompt invocation, reserved provider attempt, full response hash, private raw-response artifact, and ledger entry; native fallback markers now require matching attempt evidence.
- Refused redispatch when an exact raw response survived a crash before ledger commit, rejected panel caps that could omit required seats, and expanded deterministic gate parsing for standard test/build output plus structured CI failure summaries.
- Introduced internal budget-ledger snapshot schema v3. Pre-0.1.1 run directories remain preserved but are intentionally not resumable; restart with a new run ID because legacy ledgers and synthesis artifacts do not contain enough trustworthy information for a safe migration.

## 0.1.0 - 2026-07-19

- Initial Codex plugin marketplace package and bundled stdio MCP server.
- Direct xAI/OpenAI Responses, Anthropic Messages, OpenRouter chat/native Fusion, and generic OpenAI-compatible adapters.
- Independent panel, anonymous structured judge, minority-preserving synthesis, exact-hash adversarial gates, and amendment loop.
- Enforced concurrency, call/token/tool/cost/time budgets, retries, quality floor, degradation policy, kill switch, atomic evidence, and hash-checked resume.
- Displayable JSON Schema, validated private user overrides, safe environment/0600 secret indirection, provider diagnostics, and native Codex setup templates.
- Provider probes disable seat tools, tool policies, and local seat-level model fallback; OpenRouter Fusion probes are refused because one request can fan out to multiple inner models.
- Authenticated completion/model-discovery redirects are refused, and orchestrated HTTP-success semantic failures are persisted and accounted before fallback so budget latches remain authoritative.
- Each run ID has one cross-process active-owner lease; provider concurrency is not globally coordinated across distinct runs or processes.
- Profile and runtime validation reject duplicate panel, optional-panel, and reviewer entries plus required/optional panel overlap; every completed negative gate verdict overrides numeric quorum.
- Native Grok custom-agent templates are retained only as future-compatibility examples; tested Codex 0.145 defaults use Codex-native OpenAI executors/reviewers and external xAI Grok fusion seats.
- External Grok API/MCP participants are consistently described as seats rather than native Codex subagents, and Grok 4.5 cached-input fallback pricing is corrected to $0.50 per million tokens.
- Network-free unit suite and CI workflow.
