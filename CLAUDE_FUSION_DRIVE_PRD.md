# Claude Fusion Drive — Build Prompt / PRD

Status: canonical build prompt, 2026-07-31.
Lineage: Claude Code-first edition of Fusion Drive, derived from Relentless Inception and the two validated sibling editions (Codex Fusion Drive, Grok Fusion Drive).

---

## Mission

Claude Fusion Drive is a Claude Code-first planning and verification plugin derived from Relentless Inception. It keeps the inherited multi-model provider/orchestration core, then adds a schema-driven control plane for explicit reasoning normalization, separately configurable fusion engines, confirmation-backed execution lifecycle, per-subagent presets, OAuth-safe CLI adapters, provider batching honesty, rescue, human-simulated users, and deterministic auto-evaluation — all adapted to Claude Code's actual host contracts.

## Host contract (Claude Code)

Claude Fusion Drive targets Claude Code as the host, not Codex and not Grok Build. Every inherited capability must be re-expressed through Claude Code's real primitives:

- Plugin + marketplace layout installable into Claude Code, with uniquely named skills as the slash-menu surface.
- Skills (`SKILL.md`) for the user-facing entry points; expected surface: `/claude-fusion-drive`, `/claude-fusion-drive-config`, `/claude-fusion-drive-review`, `/claude-fusion-drive-rescue`, `/human-sim-users`, `/auto-eval` (mirror the validated Codex skill surface unless a Claude host contract dictates otherwise).
- Native Claude Code subagents (agent definitions + the Agent/Task mechanism) for `native-no-fusion` and all native execution modes, including worktree isolation, tool allow/deny lists, model and effort selection, and background execution.
- Hooks for lifecycle enforcement where the host supports it.
- An MCP control-plane server (or equivalent in-plugin runtime) exposing the required `config_*`, `workflow_report`, `preset_*`, `gate_set_*`, `provider_*`, `cost_estimate`, and `human_sim_*` tools.
- Claude Code permission modes and confirmation prompts as the consent boundary for paid fusion, external writes, and execution.
- Claude subscription/OAuth seats via the native host session or isolated CLI subprocess adapters; API seats via provider APIs or OpenRouter. OAuth children must scrub `ANTHROPIC_API_KEY` and `XAI_API_KEY` so API credentials cannot silently override a requested subscription path.
- The Codex host's thread-creation lifecycle step must be replaced by the Claude Code equivalent (goal/session/task receipt recorded before `pre_execution` can pass).

Do not copy Codex- or Grok-specific behavior blindly. Where the two validated editions disagree with a Claude Code host contract, the Claude Code contract wins and the deviation is documented.

## Canonical verification gates

The canonical eight gates are:

1. `synthesis`
2. `plan`
3. `pre_execution`
4. `subagent_pre_execution`
5. `subagent_post_execution`
6. `post_execution`
7. `final`
8. `summarize`

A phase gate can remain an optional Relentless Inception compatibility feature, but it must not replace one of those eight. The full evidence contract per gate is defined in the mandatory section below.

## Verified reference repositories

- Relentless Inception for Codex — https://github.com/ahuserious/relentless-inception-codex
- Codex Fusion Deliberation reference — https://github.com/ahuserious/relentless-inception-codex/blob/main/docs/FUSION_DELIBERATION.md
- Relentless Inception for Grok — https://github.com/ahuserious/relentless-inception-grok
- Grok Fusion Deliberation reference — https://github.com/ahuserious/relentless-inception-grok/blob/main/docs/FUSION_DELIBERATION.md

Local study material on this machine:

- Codex Fusion Drive (validated Codex edition, schema-v2 control plane, requirement matrix, tests): `/Users/DanBot/Documents/Codex/2026-07-30/is/codex-fusion-drive/`
- Grok Fusion Drive (validated Grok Build edition, Rust MCP runtime, marketplace layout): `/Users/DanBot/Documents/Codex/2026-07-30/is/grok-fusion-drive/`
- Original Claude Relentless Inception skill/plugin (consolidates goal, batch-create-eval, exaflop, gigaprompt; source of Human Sim Users, Auto Eval, rescue, and the optional phase gate): installed `relentless-inception` plugin and `~/.claude/skills/relentless-inception`; canonical copy at `/Users/DanBot/hyperfrequency/neuro-quant-agent-skills/neuro-code/relentless-inception/`
- TrustedRouter fusion benchmark artifact: the user's published benchmark Artifact (retrieve via the Artifact list)
- Current official OpenRouter Fusion documentation and current official Claude Code plugin, subagent, hook, MCP, and permission documentation: fetch live at build time; do not rely on training data.

---

## MANDATORY FUSION, SUBAGENT, VERIFICATION, AND HUMAN-SIM CONFIGURATION

Claude Fusion Drive must expose the complete workflow topology as configurable product state. Do not reduce configuration to one active model or one global fusion toggle.

The configuration system must independently control:

1. Top-level workflow fusion
2. Per-subagent execution mode
3. Per-subagent fusion preset
4. Subagents that deliberately run without fusion
5. Grok 4.5 subagents and all-Grok fusion groups
6. Verification and approval gate sets
7. Human-simulated-user campaigns
8. Auto-evaluation and release evidence
9. Provider route, authentication mode, budget, reasoning, and data-egress policy
10. Native Claude tool access and worktree isolation

### REFERENCE IMPLEMENTATIONS

Study and preserve the best validated architecture and documentation from:

- https://github.com/ahuserious/relentless-inception-codex
- https://github.com/ahuserious/relentless-inception-codex/blob/main/docs/FUSION_DELIBERATION.md
- https://github.com/ahuserious/relentless-inception-grok
- https://github.com/ahuserious/relentless-inception-grok/blob/main/docs/FUSION_DELIBERATION.md
- The locally installed Codex Fusion Drive plugin
- The original Claude Relentless Inception skill
- Batch Create Eval
- Gigaprompt
- Exaflop
- Human Sim Users
- Auto Eval
- TrustedRouter fusion benchmark artifact
- Current official OpenRouter Fusion documentation
- Current official Claude Code plugin, subagent, hook, MCP, and permission documentation

Do not copy platform-specific behavior blindly. Adapt every capability to Claude Code's actual host contracts.

### CONFIGURATION CHANGE WORKFLOW

Configuration changes must be transactional and reviewable.

Required flow:

1. Read the complete merged configuration.
2. Produce the current workflow report.
3. Translate the requested change into the smallest merge-style proposal.
4. Validate the candidate against its schema and invariants.
5. Generate:
   - proposal SHA-256
   - exact change set
   - complete redacted candidate configuration
   - updated Mermaid workflow
   - requested/effective model and reasoning table
   - affected workflow and subagent presets
   - affected gate sets
   - batch/concurrency consequences
   - estimated cost consequences
   - privacy and data-egress consequences
6. Ask the user to approve that exact proposal hash.
7. Apply it only after exact-hash approval.
8. If the base configuration changed, invalidate the proposal and generate a new one.

`config_set` must never bypass proposal validation or final approval.

A configuration approval changes settings only. It must not create a goal, launch paid fusion, authorize execution, start a subagent, or mutate a repository.

Required tools:

- config_show
- config_get
- config_validate
- config_propose
- config_approve
- config_history
- config_rollback_propose
- workflow_report
- preset_list
- preset_resolve
- gate_set_list
- provider_list
- provider_models
- provider_test
- cost_estimate

Every configuration display must redact credentials and identities. Store only environment-variable names, provider-route names, and explicitly supported CLI/OAuth modes.

### WORKFLOW FUSION ENGINES

Provide independently selectable workflow engines.

1. `canonical-in-harness`

   Genuine client-orchestrated cross-model fusion:

   - strongest Claude model
   - exact GPT 5.6 Sol
   - exact Grok 4.5
   - independent first passes
   - anonymized comparative judgment
   - strongest configured synthesizer
   - three live seats required by default
   - minority findings preserved
   - maximum fusion depth one

2. `claude-native`

   Claude host with fresh-context native Claude subagents.

   This is multi-agent Claude deliberation, not cross-provider fusion. Report that distinction explicitly.

3. `all-grok-4.5`

   - two or more independently prompted Grok 4.5 panel seats
   - Grok 4.5 judge
   - Grok 4.5 synthesizer
   - all requested at maximum supported reasoning
   - requested `xhigh` must be reported as effective `high` when that is the xAI provider ceiling
   - no smaller Grok substitution
   - minimum two independent live seats

4. `claude-grok`

   - strongest Claude panelist
   - one or more Grok 4.5 panelists
   - configurable Claude or Grok judge
   - strongest Claude synthesizer by default
   - independent Grok verification gates

5. `xai-claude-oauth`

   - direct xAI API for exact Grok 4.5
   - native Claude Code subscription/OAuth for Claude seats
   - no OpenRouter involvement
   - API spend and subscription usage reported separately

6. `subscription-oauth`

   Explicit CLI/subscription-backed microbatch mode.

   Report unknown subscription usage honestly. Do not describe serialized CLI invocations as provider Batch API calls or guaranteed discounted batching.

7. `openrouter-fusion`

   Native server-managed `openrouter/fusion`.

   Its analysis models, judge model, reasoning, and router settings must have a separate configuration block. Do not inherit or copy in-harness panel settings implicitly.

8. `trusted-router`

   Explicit trusted-router configuration with documented endpoint, provider trust, model selection, provenance, cost, and egress policy.

9. `single-model`

   One exact configured model with no fusion. This must be available for simple work, baselines, cost control, and benchmark comparison.

No engine may silently become another engine. Fallbacks require named, explicit configuration and must be displayed before execution.

### SUBAGENT EXECUTION MODES

Every material subagent or subagent batch must select one of these modes:

1. `native-no-fusion`

   A normal Claude Code subagent using one configured Claude model.

   Configuration includes:

   - agent definition
   - model
   - requested effort
   - tools and disallowed tools
   - preloaded skills
   - maximum turns
   - foreground/background behavior
   - worktree isolation
   - writable scope
   - evidence obligations
   - pre/post gate policy

2. `external-single-model`

   One external model call used as a reasoning or review seat.

   It receives only an immutable evidence packet. It does not receive Claude filesystem or shell capabilities.

3. `pre-fused-subagent`

   Run a fusion preset first, then give the fused result and immutable evidence packet to one native Claude implementation subagent.

4. `per-subagent-fusion`

   Each assigned unit runs its own bounded panel → judge → synthesis workflow before returning a result.

5. `shared-batch-fusion`

   Several related subagents work independently, then one shared fusion combines their outputs.

6. `review-only-fusion`

   The subagent executes normally without planning fusion, but its output is reviewed by a configured fusion or adversarial gate.

7. `no-agent`

   The main Claude session performs the work directly. Verification gates may still apply.

The workflow must not assume every subagent needs fusion. Fusion and non-fusion subagents must coexist in one run.

### PER-SUBAGENT CONFIGURATION

Each subagent assignment must resolve to an immutable preset hash containing:

- preset name and version
- execution mode
- driver owner and driver model
- driver requested/effective reasoning
- worker engine
- exact worker models
- panel, judge, and synthesizer seats when fused
- native tools and denied tools
- allowed skills
- MCP access
- worktree/isolation setting
- maximum turns
- concurrency
- batch mode
- timeout
- retry ceiling
- fusion-depth ceiling
- provider and transport
- cost budget
- token budget
- egress policy
- gate set
- required pre-execution evidence
- required post-execution evidence
- result schema
- completion criteria

Changing the preset after dispatch must not rewrite the historical assignment. Every subagent receipt must retain the exact preset hash used.

### DEFAULT SUBAGENT PRESETS

Provide at least:

- `claude-native-smartest`
- `claude-native-reviewer`
- `claude-native-worktree-builder`
- `canonical-in-harness`
- `claude-grok-fusion`
- `all-grok-4.5`
- `grok-fusion-drive`
- `grok-4.5-single`
- `grok-4.5-researcher`
- `grok-4.5-adversarial-reviewer`
- `grok-4.5-security-reviewer`
- `grok-gated-claude-builder`
- `fusion-plan-native-execute`
- `native-execute-fusion-review`
- `human-sim-native`
- `human-sim-fused`
- `auto-eval-review-only`
- `single-model-baseline`

`grok-fusion-drive` for the Claude edition should mean:

- strongest native Claude model as host driver
- configurable all-Grok-4.5 worker fusion
- Grok 4.5 approval gates
- bounded microbatch execution
- maximum fusion depth one
- exact provider/model provenance
- no weaker Grok fallback

Allow the user to create additional named presets conversationally through the exact-hash configuration proposal workflow.

### GROK SUBAGENT CONFIGURATION

Grok usage must support multiple independently configurable patterns:

- one Grok 4.5 reasoning seat
- multiple role-diverse Grok 4.5 seats
- all-Grok-4.5 fusion
- Grok 4.5 as judge
- Grok 4.5 as synthesizer
- Grok 4.5 as adversarial gate reviewer
- Grok 4.5 research-only seat
- Grok 4.5 security critic
- Grok 4.5 evidence auditor
- Grok-gated Claude implementation
- Claude-gated Grok reasoning
- mixed Claude/GPT/Grok fusion
- direct xAI API route
- explicitly selected Grok CLI/OAuth route
- explicitly selected OpenRouter Grok route

Every Grok configuration must expose:

- exact model identifier
- provider and transport
- requested reasoning
- effective reasoning
- tool availability
- whether it is native, API, CLI, or router-backed
- external-data egress
- timeout and retry policy
- concurrency
- call/token/cost budget
- gate role
- author/reviewer separation

Whenever Grok is used, exact Grok 4.5 is the default and required model. If Grok 4.5 is unavailable, fail closed unless the user explicitly approves another exact model through a configuration proposal.

### SUBAGENT GATES

Every material subagent batch must support:

`subagent_pre_execution`

Required evidence:

- exact subagent scope
- acceptance criteria
- immutable input artifact hash
- resolved preset hash
- tool and path policy
- cost and egress policy
- dependency boundaries

`subagent_post_execution`

Required evidence:

- subagent result
- changed artifact hashes
- tool errors
- tests and verification
- acceptance-criteria coverage
- unresolved findings
- cost and provenance
- whether the subagent stayed inside scope

A post-execution PASS cannot compensate for a missing pre-execution gate when that gate was required.

### CANONICAL VERIFICATION GATES

Implement these eight canonical stages:

1. `synthesis`

   Evidence:
   - all raw panel artifacts
   - judge artifact
   - synthesis artifact and SHA-256
   - provenance
   - minority findings

2. `plan`

   Evidence:
   - requirements trace
   - architecture/workflow report
   - risk analysis
   - test strategy
   - budget and egress estimate

3. `pre_execution`

   Evidence:
   - exact confirmed plan
   - confirmation receipt
   - repository and scope boundaries
   - selected execution profile
   - branch/worktree policy

4. `subagent_pre_execution`

   Evidence:
   - subagent scope
   - preset hash
   - tool policy
   - expected output and verification

5. `subagent_post_execution`

   Evidence:
   - subagent result
   - tool errors
   - verification
   - scope compliance

6. `post_execution`

   Evidence:
   - exact diff or output hashes
   - test commands and results
   - requirement coverage
   - human-sim results where applicable
   - security and performance evidence

7. `final`

   Evidence:
   - all current gate verdicts
   - cost ledger
   - provider/model provenance
   - release evidence
   - limitations
   - unresolved dissent

8. `summarize`

   Evidence:
   - durable decisions
   - current hashes
   - completed and pending verification
   - open risks
   - next action
   - resume instructions

Relentless Inception's phase gate may remain as an optional compatibility gate for multi-phase projects, but the above eight are the canonical Fusion Drive contract.

### GATE SETS

Provide named, independently configurable gate sets:

- `grok45-parallel-approval`
- `grok45-serialized-approval`
- `grok45-oauth-serialized-approval`
- `claude-independent-approval`
- `mixed-claude-grok-approval`
- `three-provider-approval`
- `mechanical-only`
- `human-sim-release`
- `high-risk-release`
- `review-disabled` only where explicitly allowed and visibly unsafe

The smartest default should require two independent Grok 4.5 reviewers, requested `xhigh`, effective `high`, both reviewing the same immutable artifact.

Mixed-provider gate sets must support Claude, GPT 5.6 Sol, and Grok 4.5 reviewers with configurable unanimity or quorum.

Any completed FAIL, blocking NEEDS_WORK, reproducible mechanical failure, missing required evidence, author/reviewer conflict, or changed artifact hash blocks progression regardless of numeric quorum.

### HUMAN-SIMULATED-USER TESTING

Human Sim Users must be a first-class configurable campaign system, not a generic instruction to "test the UI."

Before creating a campaign, collect or explicitly default:

- operating systems
- browsers and browser versions
- desktop/mobile/tablet devices
- viewports, zoom levels, and orientation
- personas and expertise levels
- locales and input methods
- accessibility standard
- keyboard-only behavior
- screen-reader expectations
- focus order and focus visibility
- UI/UX reference states
- allowed and forbidden console warnings
- allowed and forbidden network failures
- server and telemetry expectations
- latency and responsiveness budgets
- memory, CPU, bundle, and throughput budgets
- authentication and authorization cases
- privacy and data-egress cases
- injection and hostile-input cases
- empty, malformed, boundary, concurrent, offline, and partial-failure data
- permission to create accounts
- permission to send messages
- permission to mutate external services
- permission to incur charges

Do not invent pass/fail budgets when they would materially change the result. Ask the user or mark them explicitly as proposed defaults.

Each human-sim scenario must configure:

- persona
- platform/runtime
- viewport/device
- starting state
- exact actions
- expected observable result
- accessibility assertions
- console/network/log assertions
- performance budget
- privacy/security assertions
- allowed external side effects
- assigned subagent mode
- optional fusion preset
- evidence capture requirements
- retry and handoff policy

Human-sim campaigns must allow mixed execution:

- ordinary native Claude test agents
- fused planning followed by native execution
- Grok 4.5 adversarial personas
- cross-model accessibility review
- non-fused browser workers for cost control
- fused result evaluation
- independent final verification

The loop must be driven by a persisted campaign manifest, never an unbounded shell loop.

Required human-sim tools:

- human_sim_questions
- human_sim_create
- human_sim_plan
- human_sim_record
- human_sim_status
- human_sim_pause
- human_sim_resume
- human_sim_abort
- human_sim_goal_record
- human_sim_report

For each iteration, persist:

- scenario ID
- persona
- resolved subagent preset hash
- observable evidence
- screenshots/video where appropriate
- console and network output
- accessibility results
- performance measurements
- errors
- acceptance-criteria state
- stalled agents
- repair applied
- current artifact hash
- cost and provenance

Completion requires:

- zero open errors
- every acceptance criterion evidenced
- no stalled subagents
- all required scenarios passing
- accessibility requirements passing
- performance budgets passing
- security/privacy scenarios passing
- external-write tests either passing with authorization or explicitly skipped
- post-execution and final gates passing on the current artifact

After three identical failures by default, preserve evidence and hand off for diagnosis instead of retrying forever.

Allow an optional separate long-running Claude goal for human-sim work, but create it only after explicit confirmation.

### AUTO-EVALUATION

Auto Eval must compare claims against supplied mechanical evidence rather than judging polish.

It must evaluate:

- requirement coverage
- unsupported completion claims
- test adequacy
- evidence freshness
- artifact-hash consistency
- regression risk
- minority findings
- human-sim coverage
- accessibility
- performance
- security
- cost/provenance completeness

Auto Eval must be usable:

- after individual subagents
- after fused batches
- after implementation
- after human-sim campaigns
- as part of the final release gate
- against the strongest single-model benchmark baseline

### WORKFLOW REPORT

Before the user approves a plan or configuration, return a complete report containing:

- selected workflow profile
- Mermaid workflow graph
- complete redacted merged configuration
- workflow engine
- panel, judge, and synthesizer
- requested/effective models and reasoning
- all subagent assignments
- which subagents use fusion
- which subagents do not use fusion
- immutable preset hashes
- Grok subagent topology
- all eight gates
- required evidence per gate
- gate reviewer topology and quorum
- human-sim campaign plan
- auto-eval plan
- provider/authentication routes
- API versus subscription usage
- cost and remaining budgets
- data-egress implications
- known unavailable capabilities
- exact plan hash

Do not execute until the exact plan and required configuration proposals have been confirmed.

### ADDITIONAL ACCEPTANCE TESTS

Add tests proving:

- one workflow can mix fused and non-fused subagents
- different subagents can use different fusion presets
- multiple Grok 4.5 fusion configurations resolve independently
- all-Grok fusion differs from mixed-provider fusion
- OpenRouter Fusion remains separate from in-harness fusion
- native Claude agents remain separate from external API seats
- subagent presets are immutable after dispatch
- preset hashes are recorded in pre/post gate receipts
- changed artifacts invalidate prior gate passes
- requested Grok `xhigh` is reported as effective `high`
- unavailable Grok 4.5 fails closed
- no weaker-model substitution occurs
- human-sim scenarios can bind fused or non-fused workers
- human-sim campaigns survive restart/resume
- repeated identical failures stop with preserved evidence
- auto-eval blocks unsupported completion claims
- configuration changes cannot authorize execution
- no secret values appear in reports, artifacts, logs, or repositories

### DEFINITION OF DONE ADDITION

Claude Fusion Drive is not complete until a clean installed session demonstrates:

1. A top-level canonical three-model fusion.
2. A native Claude subagent without fusion.
3. A subagent using canonical cross-model fusion.
4. A subagent using all-Grok-4.5 fusion.
5. A Grok 4.5 review-only subagent.
6. Two different subagent presets in one workflow.
7. Passing subagent pre/post gates with immutable hashes.
8. A failing gate correctly blocking progression.
9. A repaired artifact invalidating the old quorum and passing a new quorum.
10. A human-sim campaign mixing fused and non-fused workers.
11. Human-sim restart/resume.
12. Auto-eval over the final evidence.
13. Complete redacted workflow/configuration reporting.
14. Exact model, reasoning, provider, cost, and artifact provenance.
