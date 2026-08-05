# Claude Fusion Drive plugin bundle

The Claude Code plugin entrypoint is `.claude-plugin/plugin.json`; MCP configuration is `.mcp.json`. The schema-v2 runtime is in `claude_fusion_drive`, while `relentless_inception` is the preserved provider/fusion engine inherited under its original license.

## 0.2.0 workflow surface

The upstream [fusion-harness](https://github.com/disler/fusion-harness) is a Pi
extension with three shipped commands (`/opinion`, `/fusion`, and
`/auto-validate`) and its own split-column widget/footer. Its `/debate`,
`/parallel`, and `/coordinate` examples were presented as **build-it patterns**,
not shipped upstream commands. This plugin implements those patterns plus
`best-of-n` through Claude's supported Dynamic Workflow runtime and native
`/workflows` TUI; it does not install the Pi renderer or claim a custom widget
API inside Claude Code.

| Namespaced command | Important arguments | Behavior |
| --- | --- | --- |
| `/claude-fusion-drive:opinion` | `task` | Two configured external views, no merge |
| `/claude-fusion-drive:fusion` | `task` | Two external drafts, configured fuser, native delivery |
| `/claude-fusion-drive:auto-validate` | `task`, `max_fixes` | Validator-first immutable gate and bounded repairs |
| `/claude-fusion-drive:debate` | `task`, `rounds` | Bounded two-position debate and configured verdict |
| `/claude-fusion-drive:parallel` | `task`, `workers` | Native isolated workers, no merge |
| `/claude-fusion-drive:coordinate` | `task`, `workers` | Disjoint work graph, isolated work, verified integration |
| `/claude-fusion-drive:best-of-n` | `task`, `n` | Configured candidates and judge, native delivery |

Examples:

```text
/claude-fusion-drive:opinion Review the proposed cache boundary
/claude-fusion-drive:debate {"task":"Choose the storage model","rounds":2}
/claude-fusion-drive:parallel {"task":"Prototype independent fixes","workers":3}
/claude-fusion-drive:best-of-n {"task":"Select the safest migration","n":4}
```

Run `/workflows` to view phases, agents, prompts, recent tools, results, token
totals, and elapsed time. Enter/right drills in, Escape/left returns, `p`
pauses/resumes, `x` stops, `r` restarts an agent, and `s` saves a generated
script. The full authoring and safety contract is in
[Workflow authoring](docs/WORKFLOW_AUTHORING.md).

## Rendering and evidence boundary

MCP tools return a concise human summary in `content` and retain the bounded
machine receipt in `structuredContent`. When a full receipt exceeds the inline
budget, the response identifies its private artifact path, size, and sections;
the receipt is not silently truncated into invalid JSON.

An external row in `/workflows` is a native Claude proxy that calls `seat_run`
exactly once and returns a strict boolean success/failure envelope. Every
external graph shares one durable, profile/config-bound budget ledger, so its
nodes cannot reset call, token, cost, or approval thresholds. The external seat
remains tool-free and cannot use Claude host MCP, shell, or workspace writes.
Its receipt records configured and actual route evidence, reasoning, cost, and
artifacts. Complete model text remains available to downstream graph nodes;
duplicate evidence stays artifact-backed. Native `agent()` nodes—not the
external model—own repository inspection, worktree writes, integration, and
verification. `seat_run` rejects a native `claude_host` seat so this provenance
boundary cannot be blurred.

`settings.json` installs only the supported `subagentStatusLine`, producing
clean native workflow-agent rows. The optional two-line `statusline.py` parses
Claude's host payload and adds live Fusion Drive state, but the main
`statusLine` belongs to user-global Claude settings. It must be enabled or
composed explicitly and must not overwrite an existing status line during
plugin installation.

## Manual-first and session lifetime

Installing or enabling the plugin does not auto-run these graphs, dispatch an
external seat, modify a repository, or select the main status line. Invoke a
workflow deliberately, inspect its script and resolved profile, and approve
the workflow launch under the current Claude permission mode. Shell, web, and
MCP calls outside the allowlist may still prompt. Native writer workflows state
their worktree and integration behavior; external seats never write.

Claude Code snapshots plugin commands and MCP definitions into the current
session. After an install or 0.2.0 upgrade, stop or finish active workflows and
start a new Claude Code session before checking the surface. A still-open
session may use older tool definitions while the files on disk show the newer
version. Native Dynamic Workflow pause/resume is tied to that session; durable
Fusion Drive artifacts remain available after restart, but the in-memory run is
not migrated across versions.

Use `/claude-fusion-drive` for the full plan-confirm-thread-execute lifecycle.
The direct-xAI plus Claude OAuth `xai-claude-oauth` profile is the shipped
default and has no OpenRouter route or fallback. The API-backed
`maximum-intelligence` profile remains explicit opt-in. The subscription-only
Grok/Claude workflow is selected explicitly as `subscription-oauth`.
Prefer durable `fuse_start` and `approval_gate_start` jobs, waiting with
`job_wait`; `job_status` and `job_result` remain available for manual
inspection.

Use `/claude-fusion-drive-config` for exact-hash configuration proposals and
approval. New lifecycles bind to `claude_code.TaskCreate`; legacy
`create_goal` receipts remain compatible.
