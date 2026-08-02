# Changelog

## Unreleased (0.1.1)

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
