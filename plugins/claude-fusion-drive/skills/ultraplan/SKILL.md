---
name: ultraplan
description: Route "ultraplan" requests to the right Fusion Drive workflow — parse weight (light/medium/heavy/ultra/single-stream), topology (debate/draco/opinion/best-of-n), rounds, gates, staging fan-out, and optional execution handoff (e.g. "ultraplan heavy debate", "ultraplan this with a debate then execute with grok 4.5 subagents on high with verification gates").
---

# ultraplan — request router for fusion planning

Fires when the user says **ultraplan** (or `/fusion-drive ultraplan ...`). Parse
their phrasing into one workflow invocation plus, optionally, an execution
handoff. Never re-implement the pipeline inline — always drive the shipped
workflows so provenance, budgets, and receipts stay intact.

## 1. Parse the request

| Signal in the request | Maps to |
|---|---|
| `light` / `cheap` / `smoke` | `profile: "light"` |
| `medium` / default when unstated and context is heavy | `profile: "medium"` |
| `heavy` / `frontier` | `profile: "heavy"` (gates on) or `"heavy-nogate"` if they say no gates / fast |
| `ultra` / `ultra heavy` / `max` | `profile: "ultra"` |
| `single stream` / `fast` / `low latency` | `profile: "single-stream"` (`-gated` if gates requested) |
| `debate` / `N rounds` | workflow `plan-debate`, `rounds: N` (default 2) |
| `across repos` / names ≥2 codebases / "grab context from ..." | workflow `ultraplan`, `scopes: [...]` |
| plain fusion, no debate language | workflow `draco-fusion` |
| `opinion` / `A/B` / `side by side` | workflow `opinion` |
| `best of N` | workflow `best-of-n` |
| `no gates` / `skip review` | pick the `-nogate` profile twin |
| `then execute` / `execute with <model> subagents on <effort>` | after the plan: execution handoff (§4) |

Invoke via the Workflow tool with the plugin workflow's scriptPath, passing
`args: { task, profile, rounds?, scopes? }`. The task is the user's goal
verbatim — do not compress it.

## 2. When to fan out staging (the context rules)

Fan out **before** fusing whenever any of these hold — this is what the
`ultraplan` workflow automates:

- ≥ 2 repositories or ≥ ~50 files are in scope
- the needed context will not fit in ~25k tokens of curated bundle per seat
- the user says "grab / gather / bring in context from ..."

Staging explorers are **host subagents with real code tools** (Serena symbolic
reads, GitNexus, Grep). Fusion seats are tool-free by design — they deliberate
over what staging curates, which is what keeps verdicts receipt-bound. Codebase
knowledge tools therefore enter the pipeline ONLY at the Stage phase, never in
a seat.

## 3. The Context Bundle v1 contract (what belongs in the main window)

Staging output must be curated into bundles:
`{id, title, scope, interfaces, invariants, constraints, risks, open_questions, evidence(file:line-anchored)}`

- Target ≤ ~25k tokens per bundle, hard cap ~60k. Prefer several disjoint
  bundles over one big one — context diversity decorrelates panel errors.
- Total curated context > ~250k tokens → split into clusters; each cluster gets
  its own debate, then one meta-fuse. (The `ultraplan` workflow applies these
  thresholds automatically.)
- **Main-window rule:** the main agent keeps only (a) the fused plan and (b)
  the bundle index (ids/titles/scopes). Bundle bodies stay in subagent
  provenance. Raw exploration text in the main window is a defect: re-open a
  bundle from provenance instead. "Too much context" = any bundle body, any
  full-file dump, or staging narration reaching the main window.

## 4. Execution handoff ("... then execute with grok 4.5 subagents on high")

After the fused plan returns:

1. `mcp` tool `execution_start` records the handoff (owner, plan hash).
2. Spawn dev subagents per plan step with the requested model/effort — e.g.
   "grok 4.5 subagents on high" → subagent model grok-4.5, reasoning high.
   Parallelize only steps the plan marks independent.
3. Each completed step gets a verification pass: a separate verifier subagent
   re-runs the step's checkpoint from the plan and reports back; on request
   ("verification gates", "adversarial review") also run the MCP
   `adversarial_gate` / `approval_gate` on the artifact.
4. `execution_finish` closes the run; report plan → steps → verification
   verdicts with receipts.

## 5. Worked examples

- **"ultraplan heavy debate"** → workflow `plan-debate`,
  `args: {task, profile: "heavy", rounds: 2}`.
- **"ultraplan this across serverA and clientB, 3 rounds, no gates"** →
  workflow `ultraplan`,
  `args: {task, scopes: ["serverA", "clientB"], rounds: 3, profile: "heavy-nogate"}`.
- **"ultraplan this with a debate then execute with grok 4.5 subagents on high
  with dynamic workflows and verification gates"** → workflow `plan-debate`
  (`profile: "heavy"`), then §4 handoff with grok-4.5/high dev subagents, a
  verifier subagent per step, and `adversarial_gate` on the final artifact.
- **"quick ultraplan, single stream"** → workflow `draco-fusion`,
  `args: {task, profile: "single-stream"}`.

Ambiguity rule: unstated weight on a small task → `single-stream`; unstated
weight on a context-heavy task → `medium` for exploration, and say one line
about how to rerun heavier (`profile: "heavy"`).
