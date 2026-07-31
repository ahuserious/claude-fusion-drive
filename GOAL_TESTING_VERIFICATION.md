# Goal: Claude Fusion Drive — Testing and Verification Only

Created: 2026-07-31. Scope is STRICTLY testing and verification of the ported
`claude-fusion-drive` plugin. No feature work, no refactors beyond what a
failing check requires, no provider spend.

## Hard constraints

- No OpenRouter calls of any kind (account has no credit). The
  `openrouter_api` and `openrouter_fusion_api` providers stay `enabled: false`
  in the default configuration and are never live-tested.
- No paid provider calls at all during this campaign. Mechanical evidence only:
  pytest, stdio MCP smoke, packaging integrity, schema validation, CLI
  install verification.
- No secret values in any output, log, or artifact.
- Reference contracts: `CLAUDE_FUSION_DRIVE_PRD.md` (this repo), the validated
  Codex edition (`docs/` in ahuserious/relentless-inception-codex derivative),
  and the Grok edition marketplace layout.

## Acceptance criteria (all must hold on the current tree)

1. `pytest` fully green: parity with the upstream Codex-edition baseline
   (334 passed, 1 skipped, 425 subtests) or better.
2. Stdio MCP smoke: `initialize`, `tools/list`, `config_show`,
   `workflow_report`, `preset_list`, `gate_set_list` respond without error and
   with redacted configuration only.
3. Packaging integrity: root `.claude-plugin/marketplace.json` resolves to
   `plugins/claude-fusion-drive/.claude-plugin/plugin.json`; MCP manifest uses
   `${CLAUDE_PLUGIN_ROOT}`; all six skills have `SKILL.md`.
4. Canonical eight gates present in every gate set: synthesis, plan,
   pre_execution, subagent_pre_execution, subagent_post_execution,
   post_execution, final, summarize.
5. Default profile avoids OpenRouter entirely (`xai-claude-oauth`).
6. Bench pins match the current tree (fail-closed drift guard intact).
7. GitHub repo `ahuserious/claude-fusion-drive` contains the verified tree.
8. `claude plugin marketplace add` + `claude plugin install` succeed locally
   and `claude plugin list` shows the plugin.

## Loop protocol

Run checks → on failure, apply the smallest fix → rerun the full suite →
repeat until all acceptance criteria hold. After three identical failures of
the same check, stop, preserve the evidence below, and hand off for diagnosis
instead of retrying.

## Evidence log

- 2026-07-31: Upstream baseline (codex-fusion-drive): 334 passed, 1 skipped,
  425 subtests — green.
- 2026-07-31: Ported tree after host-contract adaptation: 334 passed,
  1 skipped, 425 subtests — green (parity reached).
- 2026-07-31: PRD required-tool gap closed (+10 tools: gate_set_list,
  provider_list, cost_estimate, config_history, config_rollback_propose,
  human_sim_plan/pause/resume/abort/report) with 11 new tests: 345 passed,
  1 skipped, 425 subtests — green. Bench pins recomputed.
- 2026-07-31: Stdio MCP smoke: 61 tools, zero PRD-required tools missing;
  gate_set_list/provider_list/cost_estimate/preset_resolve/config_history all
  OK; grok-fusion-drive driver resolves to claude_host claude-fable-5 max with
  an immutable preset hash; cost estimate reports known metered Grok bound and
  explicitly-unknown Claude subscription cost; no secret values in output.
