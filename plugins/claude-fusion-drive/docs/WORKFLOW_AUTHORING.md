# Claude Fusion Drive Workflow Authoring

Claude Dynamic Workflows are JavaScript orchestration graphs executed by the
Claude workflow runtime. Claude Code renders their phases and agents in the
built-in `/workflows` TUI while the main session remains responsive. The
official runtime reference is
[Dynamic workflows](https://code.claude.com/docs/en/workflows).

## Shipped graphs

| Command | Graph | Writes |
| --- | --- | --- |
| `/claude-fusion-drive:opinion` | two configured external panel seats | none |
| `/claude-fusion-drive:fusion` | two panel seats -> configured fuser -> native deliverer | native deliverer only when the task requires it |
| `/claude-fusion-drive:auto-validate` | gate author -> RED baseline -> builder -> SHA-checked gate -> bounded repairs | native agents only |
| `/claude-fusion-drive:debate` | two positions -> bounded rebuttals -> configured judge | none |
| `/claude-fusion-drive:parallel` | N native worktree workers, no merge | isolated worktrees |
| `/claude-fusion-drive:coordinate` | strict assignment plan -> native worktree workers -> native integrator | isolated workers and verified integration |
| `/claude-fusion-drive:best-of-n` | N configured candidates -> configured judge -> native deliverer | native deliverer only when required |

The external routes are resolved by Fusion Drive configuration at run time.
The graph files intentionally contain roles and seat indices, not model names.
The proxy result provides requested and actual model/provider/reasoning evidence.

## File contract

A plugin workflow lives under the plugin-root `workflows/` directory and is
invoked as `/<plugin-name>:<meta.name>`. The metadata export must be the first
statement and a pure literal:

```js
export const meta = {
  name: 'example',
  description: 'One sentence describing the complete graph',
  phases: [
    { title: 'Map', detail: 'discover bounded independent units' },
    { title: 'Work', detail: 'run one isolated native agent per unit' },
  ],
}
```

The body is ordinary JavaScript with top-level `await`. The supported runtime
surface used by these assets is:

- `agent(prompt, options)` for one native Claude subagent;
- `parallel([() => agent(...), ...])` for explicit concurrent branches;
- `pipeline(items, stage, ...)` for a per-item fan-out or staged lane;
- `phase(title)` to update the progress graph;
- `log(message)` for a short progress note;
- global `args`, which is `undefined`, structured data, or a raw string.

Do not import Node modules or access the filesystem or shell from the graph
body. The runtime intentionally denies direct graph I/O. A native `agent()`
must perform repository reads, tool calls, writes, and commands.

Normalize task input without assuming a CLI encoding:

```js
const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'Inspect the current repository and report the highest-impact risk.'
const taskInput = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.task === 'string'
    ? inputArgs.task
    : typeof inputArgs === 'string'
      ? inputArgs
      : defaultTask
)
const task = taskInput.trim() || defaultTask
```

Always provide a useful no-argument fallback. Clamp caller-controlled counts;
the shipped graphs cap worker/candidate fan-out at 8, debate rounds at 5, and
auto-validation repairs at 5.

## External-seat proxy contract

External providers do not become native Claude workflow agents. Spawn a native
proxy agent whose only job is to call the Fusion Drive MCP tool `seat_run` once
and return a strict success/failure envelope. The tool contract is:

```text
required: task
optional: context, profile, seat_name,
          role = panel | judge | fuser | verifier,
          seat_index, cycle, resume_run_id, graph_run_id
```

Use indices `0` and `-1` for a two-route opinion or fusion panel. For a
configurable best-of-N panel, use `role: 'panel'`, `seat_index: i`, and
`cycle: true`. Do not put model names in graph files: configuration owns model,
provider, reasoning, budget, and fallback selection.

Generate one valid `graph_run_id` per workflow invocation and pass it to every
external seat in that graph. It must match
`[A-Za-z0-9][A-Za-z0-9-]{0,127}`. Reusing the same ID intentionally reuses the
same profile/config-bound aggregate budget ledger; changing the bound profile
or configuration fails closed. Call reservations are serialized before
dispatch while provider calls remain parallel. Tokens, cost, and approval
thresholds are recorded after each response and latch later dispatches.

A proxy prompt must say all of the following:

1. call `seat_run` exactly once with the supplied object;
2. return `{ok:true,result:<complete tool result>,error:null}` on success or
   `{ok:false,result:null,error:<reason>}` on any tool failure;
3. do not answer using the proxy's own judgment;
4. do not call another fusion workflow or write files;
5. never put a failure under a truthy or string-valued `ok` field.

This keeps provenance honest. `/workflows` shows a native proxy row, while the
tool result records the actual external route and artifact evidence. Check
`ok === true` before unwrapping; stop before any fuser, judge, or deliverer when
a required seat fails. Do not silently slice model results on external graph
edges. The workflow result keeps the complete top-level model text while full
internal receipts and aggregate-ledger entries remain available at the exposed
artifact paths.

## Write isolation and integration

Any independent native writer must use `isolation: 'worktree'`. A parallel graph
returns every worktree result without merging. A coordinate graph first emits a
strict assignment object containing unique id, objective, owned paths,
dependencies, and mechanical acceptance criteria. Its final native integrator
must inspect the real worktree diffs, reject ownership overlap or scope drift,
apply changes in dependency order, and run combined checks. Workflow assets do
not commit, push, publish, or mutate remotes.

## Validator-first gate

`auto-validate` enforces this sequence:

1. Validator writes a task-specific executable gate before implementation.
2. Validator runs it against the untouched state; the task-specific check must
   be RED rather than failing because the gate is malformed.
3. Validator computes SHA-256 of the final gate.
4. Builder implements under an explicit prohibition on modifying the gate.
5. An independent verifier hashes the gate, runs it, and hashes it again.
6. Any hash mismatch fails closed immediately. A failing but unchanged gate may
   trigger only the configured, clamped number of repair attempts.

The immutability boundary is prompt plus independent SHA verification, not an
OS-level read-only mount. A defective gate requires a new run; the builder must
never repair its own acceptance criteria.

## No mid-run human input

Dynamic Workflows do not support arbitrary user input while the graph is
running. Only tool permission prompts may pause an agent. A human plan gate
must therefore be split across commands:

```text
plan workflow -> user reviews and approves exact plan hash
              -> execution workflow consumes approved receipt
              -> verification workflow
```

Do not fake a human approval with another agent. In unattended `claude -p` or
Agent SDK runs, unavailable permissions fail according to configured policy;
pre-allow the MCP and shell tools the graph legitimately needs.

## Inspect, edit, and save

Run `/workflows` to list runs. The progress view exposes phases, agents, token
totals, elapsed time, prompts, recent tool calls, and results. Its principal
controls are Enter/right to drill in, Escape/left to go back, `p` to
pause/resume, `x` to stop, `r` to restart an agent, and `s` to save a generated
script.

Before launch, choose **View raw script** or press `Ctrl+G` to open the proposed
script in the editor. Every run also has a script under its Claude session
directory; ask Claude for that path, edit it, and relaunch when iterating.

To save a generated graph, select its run in `/workflows`, press `s`, use Tab to
choose either project `.claude/workflows/` or personal
`~/.claude/workflows/`, and press Enter. Project files are shared with the
repository; personal files are local and available across projects. Plugin
workflows belong in this repository's plugin-root `workflows/` directory and
remain namespaced by the plugin name.

## Review checklist

Before shipping a graph, verify:

- metadata is the first pure-literal statement and phase titles match calls;
- task input handles `args.task`, raw strings, and missing args;
- every fan-out and loop is bounded;
- external proxies use configured roles/indices and contain no model names;
- external seats never write files;
- every independent native writer is worktree-isolated;
- collapse, missing evidence, failed gates, and changed hashes fail closed;
- no stage assumes arbitrary mid-run user input;
- no graph promises a merge, write, or human approval it does not perform.
