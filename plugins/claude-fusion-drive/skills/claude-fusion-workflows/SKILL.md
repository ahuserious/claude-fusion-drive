---
name: claude-fusion-workflows
description: Run, inspect, adapt, or author Claude Dynamic Workflows for opinion, fusion, validation, debate, parallel work, coordination, and best-of-N; use when repeatable graph orchestration is more useful than a turn-by-turn chat, and not when the task needs mid-run human decisions.
---

# Claude Fusion Workflows

Use this skill when the user asks to run one of the plugin's workflow graphs or
to create, inspect, edit, save, or troubleshoot a Claude Dynamic Workflow.

## Choose the graph

- `opinion`: two configured external perspectives, returned separately.
- `fusion`: two configured external drafts, configured fuser, then one native
  deliverer for evidence checks and any tool or file work.
- `auto-validate`: validator-first gate, expected RED baseline, native build,
  immutable-gate verification, and bounded repairs.
- `debate`: two configured external positions, bounded rebuttal rounds, then a
  configured judge.
- `parallel`: the same task in independent native worktrees, with no merge.
- `coordinate`: strict disjoint assignments, native worktree workers, then a
  native integrator.
- `best-of-n`: configurable external candidate fan-out, configured judge, then
  a native deliverer.

Plugin commands are namespaced, for example
`/claude-fusion-drive:fusion`. Pass a task as structured `args.task` when the
caller supports structured input; every shipped graph also accepts a raw string.

## Inspect and control runs

1. Run `/workflows` to list active and completed runs.
2. Select a run and press Enter to inspect phases, agents, recent tool calls,
   results, token totals, and elapsed time.
3. Use `p` to pause/resume, `x` to stop, and `r` to restart the selected agent.
4. Treat an external-seat proxy as one native agent row. Its `seat_run` result
   contains actual model, provider, reasoning, ledger, and artifact evidence;
   do not relabel that proxy row as the external model itself.

## Author or edit a graph

Follow [WORKFLOW_AUTHORING.md](../../docs/WORKFLOW_AUTHORING.md). In short:

1. Make `export const meta = { ... }` the first statement. Keep it a pure
   literal and use phase objects with `title` and `detail`.
2. Use only the workflow globals `agent`, `parallel`, `pipeline`, `phase`,
   `log`, and `args` plus ordinary JavaScript. The graph itself has no direct
   filesystem or shell access; delegate reads, writes, and commands to native
   agents.
3. External models are transparent proxy agents that call `seat_run` exactly
   once with `task`, configured `role`, configured `seat_index`, and one shared
   `graph_run_id` for the workflow invocation. Require a strict boolean
   `{ok,result,error}` envelope and stop before downstream fusion/judging on
   failure. Do not hardcode model names or silently slice model results.
   External seats advise; native agents own tools and writes.
4. Bound every caller-controlled fan-out and loop. Fail closed when required
   seats, gates, hashes, worktrees, or evidence are missing.
5. For write fan-out, set `isolation: 'worktree'` and define explicit ownership.

Before a generated run starts, use **View raw script** or `Ctrl+G` to inspect or
edit it. For a running or completed generated workflow, Claude receives the
session script path; ask Claude to open that file, edit it, and relaunch. To
save a successful generated graph, open `/workflows`, select it, press `s`, use
Tab to choose project `.claude/workflows/` or personal
`~/.claude/workflows/`, and press Enter. Edit this plugin's source workflows in
the plugin repository; save a project or personal copy when customization
should not modify the installed plugin.

## Interaction and permission boundary

Dynamic Workflows cannot ask arbitrary questions or obtain human sign-off
mid-run. Split a human-gated process into separate workflows, such as
`plan -> user approval -> execute -> verify`, and bind the approved artifact by
hash. Tool permission prompts can still pause agents; pre-allow the required
MCP and shell tools for unattended runs. Never describe a launch-time workflow
approval as an in-graph plan gate.

For sensitive or destructive operations, stop before the operation and return
an approval artifact. A later workflow may execute only after the user starts
it with that exact approved receipt.
