# Claude Fusion Drive

Claude Fusion Drive is a Claude Code-first planning and verification plugin derived from Relentless Inception. It keeps the inherited multi-model provider/orchestration core, then adds a schema-v2 control plane for explicit reasoning normalization, separately configurable Fusion engines, confirmation-backed execution lifecycle, per-subagent presets, OAuth-safe CLI adapters, provider batching, rescue, simulated users, and deterministic auto-evaluation.

## Fusion Harness and Fusion Drive

[disler/fusion-harness](https://github.com/disler/fusion-harness) is a
standalone Pi extension. It ships `/opinion`, `/fusion`, and `/auto-validate`,
spawns clean-room `pi --mode json -p` children, and owns a custom split-column
widget and footer. Its video presented `/debate`, `/parallel`, and `/coordinate`
as **build-it patterns**, not as commands shipped by that upstream repository.

Claude Fusion Drive 0.2.0 implements those three patterns, adds `best-of-n`, and
ships all seven as namespaced Claude Dynamic Workflows. It uses Claude Code's
native workflow graph and agent views instead of claiming an arbitrary Pi-style
widget API. Configured frontier-model seats run through the Fusion Drive MCP;
native Claude agents retain host tools, worktree isolation, and responsibility
for any workspace changes.

## Workflow commands

| Command | Result |
| --- | --- |
| `/claude-fusion-drive:opinion` | Two configured external perspectives, no merge |
| `/claude-fusion-drive:fusion` | Two external drafts, configured fusion, then one native deliverer |
| `/claude-fusion-drive:auto-validate` | Validator-first RED gate, native build, immutable-gate verification, bounded repair |
| `/claude-fusion-drive:debate` | Two configured positions, bounded rebuttals, one configured verdict |
| `/claude-fusion-drive:parallel` | N native worktree workers, retaining every result with no merge |
| `/claude-fusion-drive:coordinate` | Strict assignment graph, isolated native workers, verified integration |
| `/claude-fusion-drive:best-of-n` | N configured candidates, configured judge, one native deliverer |

Each command accepts a plain task or a structured argument object. Examples:

```text
/claude-fusion-drive:opinion Assess this API boundary
/claude-fusion-drive:fusion {"task":"Design the smallest safe migration"}
/claude-fusion-drive:auto-validate {"task":"Fix the failing parser","max_fixes":2}
/claude-fusion-drive:debate {"task":"Monolith or services?","rounds":3}
/claude-fusion-drive:parallel {"task":"Prototype the fix","workers":4}
/claude-fusion-drive:coordinate {"task":"Implement the approved plan","workers":3}
/claude-fusion-drive:best-of-n {"task":"Find the strongest design","n":5}
```

Open `/workflows` to inspect the native progress graph, phases, agent prompts,
recent tools, results, tokens, and elapsed time. Use Enter/right to drill in,
Escape/left to return, `p` to pause or resume, `x` to stop, `r` to restart an
agent, and `s` to save a generated workflow. See
[Workflow authoring](plugins/claude-fusion-drive/docs/WORKFLOW_AUTHORING.md) for the graph contract,
argument limits, write isolation, and fail-closed review checklist.

## Output, status, and provenance

MCP calls keep terminal output quiet: the human-facing text is a bounded status
or result summary, while the bounded machine receipt remains in
`structuredContent`. Oversized receipts are saved in full at a private artifact
path; the structured response carries that path plus size and section metadata
instead of flooding context or returning malformed truncated JSON.

External workflow rows are transparent native proxies. A proxy calls `seat_run`
once and returns a strict boolean success/failure envelope; it is not itself
the external model. Every external graph invocation shares one durable,
profile/config-bound budget ledger, so separate nodes cannot reset call,
token, cost, or approval thresholds. The receipt
records the selected seat, provider, transport, requested model/reasoning,
actual response evidence, cost ledger, and artifact directory. `seat_run`
rejects native `claude_host` seats: external seats are tool-free and cannot use
host MCP, shell, or workspace writes, while native `agent()` nodes own those
actions. Complete model text remains available to downstream graph nodes rather
than being silently sliced; bulky duplicate evidence remains artifact-backed.

The plugin ships a clean `subagentStatusLine` for workflow-agent rows. The
two-line `statusline.py` can also show Fusion Drive state plus the host model,
context use, cost, and duration, but Claude's main `statusLine` is a user-global
setting. Enable or compose it explicitly; installing the plugin does not
replace an existing main status line.

## Manual-first operation and upgrades

Enabling the plugin does not automatically launch a workflow, spend on an
external seat, write files, or install the global status line. Run a namespaced
command explicitly, inspect its script and resolved configuration, and approve
the workflow launch under the current Claude permission mode. Shell, web, and
MCP calls outside the allowlist may still prompt. Workflows that contain native
builders or integrators may write within their documented isolation boundary;
external seats never do.

Claude Code loads plugin manifests, workflow commands, and MCP tool definitions
for the current session. After installing or upgrading Fusion Drive, finish or
stop active workflow runs and start a new Claude Code session before validating
the version. Otherwise the current session can retain an older command or MCP
surface while files on disk already report 0.2.0. Dynamic Workflow pause/resume
is current-session state; durable Fusion Drive receipts remain on disk, but a
restarted host does not migrate an in-memory workflow run across versions.

## Default xai-claude-oauth workflow

| Role | Model | Requested effort | Effective transport effort |
|---|---|---:|---:|
| Panel | xAI Grok 4.5 | `xhigh` | `high` (`provider_ceiling`) |
| Panel | xAI Grok 4.5 | `xhigh` | `high` (`provider_ceiling`) |
| Panel | Claude Fable 5 (subscription OAuth) | `xhigh` | `max` |
| Judge | xAI Grok 4.5 | `xhigh` | `high` (`provider_ceiling`) |
| Fuser | Claude Fable 5 (subscription OAuth) | `xhigh` | `max` |
| Approval reviewers | xAI Grok 4.5, serialized | `xhigh` | `high` (`provider_ceiling`) |
| Grok Fusion Drive host driver | claude-fable-5 | `max` | host-owned `max` |

The direct xAI Grok 4.5 interface does not expose a literal `xhigh` value. The plugin preserves `xhigh` as the requested intelligence intent, sends `high`, and reports the normalization instead of overstating the wire behavior. Claude subscription OAuth seats likewise record the requested `xhigh` and its effective `max` mapping.

Aggregate `max_reasoning_tokens` and `max_wall_seconds` are `null`. Per-request timeouts, retries, call/token/cost ceilings, abort switches, rescue bounds, and approval gates remain active.

## Fusion engines

- `in_harness`: plugin-owned independent panel, anonymous GPT judge, and GPT generative fuser.
- `subscription_oauth`: explicitly selected subscription-only panel with two independent Grok 4.5 personas plus Claude Fable 5, a Grok 4.5 judge, and a Claude Fable 5 fuser.
- `xai_claude_oauth`: explicitly selected hybrid panel with two direct xAI Grok 4.5 personas plus Claude Fable 5 OAuth, a direct xAI Grok judge, a Claude OAuth fuser, and serialized direct xAI Grok plan reviewers. It has no OpenRouter route or fallback.
- `openrouter_fusion`: independent `openrouter/fusion` settings for analysis models, server judge, reasoning, and fallback. It does not inherit the in-harness panel block.
- `all_grok_4_5`: two Grok panel seats, one Grok judge, and one Grok fuser, with the selected approval gate set inherited.

`xai-claude-oauth` is the default active profile: exact Grok 4.5 through the
direct xAI API plus Claude subscription OAuth seats, with no OpenRouter route
or fallback. It requires the `XAI_API_KEY` environment reference while Claude
remains on subscription OAuth. The OpenRouter-backed `maximum-intelligence`
profile and the `subscription-oauth` profile remain separate opt-in
configuration and are never used as silent fallbacks; the `openrouter_api` and
`openrouter_fusion_api` providers ship `enabled: false`.

## Gates

The configured stages are `synthesis`, `plan`, `pre_execution`, `subagent_pre_execution`, `subagent_post_execution`, `post_execution`, `final`, and `summarize`.

Planning stops after the plan gate. The host returns the plan, Mermaid graph, and full redacted effective configuration, then waits for explicit confirmation. When the user subsequently asks to execute, the Claude Code host creates the goal task with `claude_code.TaskCreate` and records its goal receipt before the pre-execution gate can pass. Legacy lifecycle files bound to `create_goal` remain readable.

## OAuth and batching

The plugin supports isolated tool-free Claude Code and Grok CLI subprocess adapters. Grok receives its protected `0600` prompt through `--prompt-file`; Claude receives the same isolated prompt through stdin. Every OAuth child removes both `ANTHROPIC_API_KEY` and `XAI_API_KEY` so API credentials cannot silently override the requested subscription OAuth path. Tokens, account emails, X handles, cookies, and keychain paths are never read or stored.

Claude result envelopes are normalized without exposing rejected content:
ordinary `result` text, canonical schema-backed `structured_output`, final
result envelopes in JSON sequences, and valid bare JSON are supported. Failed
or unusable calls retain an unknown-cost response receipt whose diagnostics
contain only output type, length, hash, exit status, and error category.

Batch behavior is transport-specific:

- OpenAI and Anthropic API configurations can prepare and explicitly submit their documented provider Batch API jobs.
- xAI Grok 4.5 cannot use the xAI Batch API.
- OpenRouter uses bounded microbatching and provider caching; no undocumented async discount is claimed.
- Claude/Grok subscription OAuth uses serialized isolated subprocesses and is not described as an API batch discount.

Subscription calls use `unknown_cost_policy: report_unknown`. Unknown
subscription cost remains explicitly unknown, increments the unknown-call
ledger, and does not become a fabricated `$0.00` charge or block the next call.

## Durable asynchronous fusion

`fuse_start` and `approval_gate_start` return durable job receipts immediately
after explicit external-usage confirmation. Callers provide a stable
idempotency key and normally use `job_wait` for one bounded wait plus a
hash-verified result; `job_status` and `job_result` remain available for manual
inspection. `job_abort` writes the recoverable inherited kill switch; it
does not force-kill an in-flight provider call.

Each private job directory persists the immutable request/configuration hashes,
worker state, sanitized failure receipt, and result hash. Replaying the same key
returns the original job. A conflicting request, configuration drift, or an
orphaned worker fails closed and is never automatically redispatched.

## Skills

- `/claude-fusion-drive`
- `/claude-fusion-drive-config`
- `/claude-fusion-drive-review`
- `/claude-fusion-drive-rescue`
- `/human-sim-users`
- `/auto-eval`

## Layout

- `plugins/claude-fusion-drive/config/fusion-drive.default.json`: schema-v2 defaults.
- `plugins/claude-fusion-drive/schemas/fusion-drive.schema.json`: documented schema.
- `plugins/claude-fusion-drive/claude_fusion_drive/`: control-plane runtime.
- `plugins/claude-fusion-drive/relentless_inception/`: vendored inherited engine.
- `tests/`: inherited regression coverage plus Fusion Drive requirement tests.
- `docs/REQUIREMENT_MATRIX.md`: objective-to-evidence map.

## Security boundary

Remote models never receive host credentials and never own workspace execution. API/provider calls can incur cost. Batch submission, provider tests, OAuth completion tests, external writes, repo merges, destructive actions, and Claude Code goal-task creation require explicit confirmation or host action.

## Attribution

This project is a derivative of `ahuserious/relentless-inception-codex` 0.1.4, ported through the validated Codex edition `codex-fusion-drive` 0.1.2. The inherited license and notices are preserved. See `docs/UPSTREAM.md`.
