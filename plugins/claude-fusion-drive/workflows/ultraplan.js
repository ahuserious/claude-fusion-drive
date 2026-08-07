export const meta = {
  name: 'ultraplan',
  description: 'Context-heavy planning: fan out staging explorers, curate Context Bundles, per-seat debate, fused plan',
  phases: [
    { title: 'Stage', detail: 'parallel host explorers sweep the named scopes with real code tools' },
    { title: 'Curate', detail: 'findings become Context Bundles v1; assignment decides per-seat context and fan-out' },
    { title: 'Debate', detail: 'fusion panel debates with per-seat bundles; clusters debate independently' },
    { title: 'Fuse', detail: 'one executable plan; only the plan and bundle index reach the caller' },
  ],
}

// ---------------------------------------------------------------------------
// Context Bundle v1 — the curation contract.
//
// A bundle is the ONLY shape staging output may take on its way into a fusion
// seat. Raw exploration text never reaches a seat or the main window:
//   { id, title, scope,            — repo/path globs this bundle covers
//     interfaces, invariants,      — what the plan must respect
//     constraints, risks,          — hard limits and known hazards
//     open_questions,              — what exploration could NOT resolve
//     evidence }                   — condensed excerpts, file:line anchored
//
// Budgets (chars ≈ tokens*4): TARGET_BUNDLE 100k chars (~25k tok) per seat,
// HARD_BUNDLE 240k chars (~60k tok). If total curated context exceeds
// CLUSTER_SPLIT (~1M chars ≈ 250k tok), the curator splits into clusters and
// each cluster gets its own debate before a meta-fuse — that is the "fan out
// individual fusions" rule, applied automatically instead of by feel.
// ---------------------------------------------------------------------------
const TARGET_BUNDLE_CHARS = 100000
const HARD_BUNDLE_CHARS = 240000
const CLUSTER_SPLIT_CHARS = 1000000

const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'Produce the best executable plan for the highest-impact open problem in this repository.'
const rawTask = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.task === 'string'
    ? inputArgs.task
    : typeof inputArgs === 'string' ? inputArgs : defaultTask
)
const task = rawTask.trim() || defaultTask

const scopes = (
  inputArgs && typeof inputArgs === 'object' && Array.isArray(inputArgs.scopes) && inputArgs.scopes.length
    ? inputArgs.scopes.map(String).slice(0, 6)
    : ['the current repository']
)
const roundsRaw = Number(inputArgs && typeof inputArgs === 'object' ? inputArgs.rounds : NaN)
const rounds = Number.isFinite(roundsRaw) ? Math.min(3, Math.max(1, Math.trunc(roundsRaw))) : 1
const profile = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.profile === 'string' && inputArgs.profile.trim()
    ? inputArgs.profile.trim()
    : null
)
const suppliedRunId = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.graph_run_id === 'string'
    ? inputArgs.graph_run_id.trim() : ''
)
const validRunId = /^[A-Za-z0-9][A-Za-z0-9-]{0,127}$/
const graphRunId = validRunId.test(suppliedRunId) ? suppliedRunId : `ultraplan-${scopes.length}scope`

const seatEnvelopeSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['ok', 'result', 'error'],
  properties: { ok: { type: 'boolean' }, result: {}, error: { type: ['string', 'null'] } },
}
const unwrap = (envelope) => (
  envelope && typeof envelope === 'object' && envelope.ok === true
    && envelope.result !== null && typeof envelope.result !== 'undefined'
    ? envelope.result : null
)
const runSeat = (role, seatIndex, phaseName, label, seatTask, context) => {
  const seatArguments = { task: seatTask, role, seat_index: seatIndex, graph_run_id: graphRunId }
  if (profile) seatArguments.profile = profile
  if (context) seatArguments.context = context
  return agent(
    `You are a transparent seat proxy, not the task solver. Call the MCP tool seat_run exactly once with these arguments:\n${JSON.stringify(seatArguments)}\nIf it succeeds, return exactly {"ok":true,"result":<the complete seat_run result>,"error":null}. Otherwise return exactly {"ok":false,"result":null,"error":"<concise reason>"}. Never answer from your own judgment and never place a failure under ok=true.`,
    { label, phase: phaseName, schema: seatEnvelopeSchema },
  )
}

phase('Stage')
log(`Staging: ${scopes.length} explorer(s) sweeping scopes with host code tools.`)
// Host subagents with REAL tools (Serena/GitNexus/Read/Grep). This is the only
// layer allowed to touch code; fusion seats stay tool-free and receipt-bound.
const findings = await parallel(scopes.map((scope, index) => () => agent(
  `You are a staging explorer for a multi-codebase planning run. Sweep: ${scope}\n\nPLANNING TASK (for relevance filtering):\n${task}\n\nUse code tools (prefer symbolic overviews over full-file reads). Return CONDENSED findings only — the interfaces, invariants, constraints, risks, and open questions a planner must know, each with file:line anchors. No full file dumps, no narration. Hard cap your return at ~${Math.floor(TARGET_BUNDLE_CHARS / 1000)}k characters.`,
  { label: `ultraplan:stage:${index}`, phase: 'Stage' },
)))

phase('Curate')
const curated = await agent(
  `You are the context curator. Convert raw staging findings into Context Bundle v1 JSON and decide the fan-out.\n\nTASK:\n${task}\n\nSCOPES:\n${JSON.stringify(scopes)}\n\nRAW FINDINGS:\n${findings.map((f, i) => `--- explorer ${i} ---\n${typeof f === 'string' ? f : JSON.stringify(f)}`).join('\n')}\n\nReturn JSON: {"bundles":[{"id","title","scope","interfaces":[],"invariants":[],"constraints":[],"risks":[],"open_questions":[],"evidence"}],"clusters":[["bundle-id",...]],"dropped":"what you cut and why"}.\nRules: each bundle <= ${HARD_BUNDLE_CHARS} chars (target ${TARGET_BUNDLE_CHARS}); prefer several small disjoint bundles over one large one (context diversity decorrelates panel errors); if total exceeds ${CLUSTER_SPLIT_CHARS} chars, split into multiple clusters — each cluster becomes its own fusion. Never invent evidence; unresolved items belong in open_questions.`,
  { label: 'ultraplan:curator', phase: 'Curate' },
)

// Normalize defensively: a curator that fails to produce the contract shape
// degrades to one cluster of raw-finding bundles rather than losing the run.
let bundles = []
let clusters = []
const curatedObject = (typeof curated === 'string')
  ? (() => { try { return JSON.parse(curated) } catch { return null } })()
  : curated
if (curatedObject && Array.isArray(curatedObject.bundles) && curatedObject.bundles.length) {
  bundles = curatedObject.bundles.map((bundle, index) => ({ id: String(bundle.id ?? `b${index}`), ...bundle }))
  const rawClusters = Array.isArray(curatedObject.clusters) ? curatedObject.clusters : []
  clusters = rawClusters
    .map((ids) => (Array.isArray(ids) ? ids.map(String).filter((id) => bundles.some((b) => b.id === id)) : []))
    .filter((ids) => ids.length)
  if (!clusters.length) clusters = [bundles.map((b) => b.id)]
} else {
  bundles = findings.map((finding, index) => ({
    id: `raw${index}`,
    title: `raw findings: ${scopes[index] ?? index}`,
    scope: scopes[index] ?? String(index),
    evidence: String(typeof finding === 'string' ? finding : JSON.stringify(finding)).slice(0, HARD_BUNDLE_CHARS),
  }))
  clusters = [bundles.map((b) => b.id)]
}
log(`Curated ${bundles.length} bundle(s) into ${clusters.length} cluster(s).`)

const bundleById = new Map(bundles.map((bundle) => [bundle.id, bundle]))
const PANEL_SEATS = 3

const debateCluster = async (clusterIds, clusterIndex) => {
  const clusterBundles = clusterIds.map((id) => bundleById.get(id)).filter(Boolean)
  // Per-seat context: round-robin the bundles so seats argue from DIFFERENT
  // evidence — the judge and fuser see the union and surface the gaps.
  const perSeat = Array.from({ length: PANEL_SEATS }, (unused, seatIndex) => (
    clusterBundles.filter((unused2, bundleIndex) => bundleIndex % PANEL_SEATS === seatIndex)
  ))
  const draftEnvelopes = await parallel(perSeat.map((seatBundles, seatIndex) => () => runSeat(
    'panel', seatIndex, 'Debate', `ultraplan:c${clusterIndex}:draft:${seatIndex}`,
    `Independently produce an executable plan for the slice of the system your context bundles cover. Number the steps; each carries action, evidence (cite bundle ids), risk, verification checkpoint, rollback. List what you could NOT verify from your bundles.\n\nPLANNING TASK:\n${task}`,
    JSON.stringify({ bundles: seatBundles.length ? seatBundles : clusterBundles }),
  )))
  let positions = draftEnvelopes.map(unwrap).filter((position) => position !== null)
  if (!positions.length) return null
  for (let round = 1; round <= rounds; round += 1) {
    const dossier = JSON.stringify({ positions: positions.map((position, i) => ({ id: `[${i + 1}]`, plan: position })) })
    const revisedEnvelopes = await parallel(positions.map((unused, seatIndex) => () => runSeat(
      'panel', seatIndex, 'Debate', `ultraplan:c${clusterIndex}:r${round}:${seatIndex}`,
      `Debate round ${round}/${rounds}. You are position [${seatIndex + 1}]. Attack the other positions from YOUR bundles' evidence; revise yours only where an attack lands. Keep defensible minority positions. Return your full revised plan.`,
      dossier + '\n' + JSON.stringify({ all_bundles: clusterBundles }),
    )))
    const revised = revisedEnvelopes.map(unwrap)
    positions = positions.map((position, i) => (revised[i] !== null ? revised[i] : position))
  }
  const judgeEnvelope = await runSeat(
    'judge', 0, 'Debate', `ultraplan:c${clusterIndex}:judge`,
    'Compare the debated positions. Return compact JSON only with keys consensus, contradictions, partial_coverage, unique_insights, minority_findings, blind_spots, final_guidance. Do NOT write the final plan.',
    JSON.stringify({ task, positions, bundle_ids: clusterIds }),
  )
  return { clusterIds, positions, judge: unwrap(judgeEnvelope) }
}

phase('Debate')
const clusterResults = (await parallel(clusters.map((ids, index) => () => debateCluster(ids, index))))
  .filter((result) => result !== null)
if (!clusterResults.length) {
  return { task, status: 'panel-collapsed', graph_run_id: graphRunId, clusters: clusters.length, final: null }
}

phase('Fuse')
const fuserEnvelope = await runSeat(
  'fuser', 0, 'Fuse', 'ultraplan:fuser',
  clusterResults.length > 1
    ? 'META-FUSE: several independent cluster debates follow, each covering a different slice of the system. Write ONE executable plan that sequences the slices, resolves cross-cluster contradictions on evidence, and preserves supported minority positions as alternatives with trigger conditions. Return only the plan.'
    : 'Write the final executable plan from the debated positions and judge analysis. No voting or splicing; preserve supported minority positions as alternatives with trigger conditions. Number steps with action, risk, verification checkpoint, rollback. Return only the plan.',
  JSON.stringify({ task, cluster_results: clusterResults }),
)
const fused = unwrap(fuserEnvelope)
if (fused === null) {
  return { task, status: 'fuser-failed', graph_run_id: graphRunId, clusters: clusterResults.length, final: null }
}

// Main-window contract: the caller receives the PLAN and a bundle INDEX
// (ids/titles/scopes) — never bundle bodies. Anyone needing a bundle's content
// re-opens it from provenance instead of re-inflating the main context.
return {
  task,
  status: 'complete',
  graph_run_id: graphRunId,
  final: typeof fused === 'string' ? fused : (fused.final_answer ?? fused),
  provenance: {
    scopes,
    bundle_index: bundles.map((bundle) => ({ id: bundle.id, title: bundle.title, scope: bundle.scope })),
    clusters: clusters.length,
    debate_rounds: rounds,
    profile: profile ?? '(active profile)',
  },
}
