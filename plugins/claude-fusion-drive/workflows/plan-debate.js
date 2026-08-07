export const meta = {
  name: 'plan-debate',
  description: 'N-round planning debate: independent plans, adversarial rebuttal rounds, judge, fused plan',
  phases: [
    { title: 'Draft', detail: 'independent plans from every panel seat' },
    { title: 'Debate', detail: 'N adversarial rebuttal rounds; positions revised only on evidence' },
    { title: 'Judge', detail: 'compact JSON diagnosis of the surviving positions' },
    { title: 'Fuse', detail: 'one executable plan preserving supported minority positions' },
  ],
}

// Seat composition, models, billing, and hyperparameters all live in the drive
// config (active or per-call profile) — this script only shapes the DAG, so
// switching tier (light/medium/heavy/ultra) never changes debate mechanics.
const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'Produce the best executable plan for the highest-impact open problem in this repository.'
const rawTask = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.task === 'string'
    ? inputArgs.task
    : typeof inputArgs === 'string' ? inputArgs : defaultTask
)
const task = rawTask.trim() || defaultTask

const configuredRounds = Number(inputArgs && typeof inputArgs === 'object' ? inputArgs.rounds : NaN)
// 1..4 debate rounds; default 2. Diminishing returns beyond that — positions
// either converge or the disagreement is real and belongs in front of the judge.
const rounds = Number.isFinite(configuredRounds) ? Math.min(4, Math.max(1, Math.trunc(configuredRounds))) : 2

const configuredSeats = Number(inputArgs && typeof inputArgs === 'object' ? inputArgs.panel_seats : NaN)
const panelSeats = Number.isFinite(configuredSeats) ? Math.min(5, Math.max(2, Math.trunc(configuredSeats))) : 3

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
const graphRunId = validRunId.test(suppliedRunId) ? suppliedRunId : `plan-debate-${rounds}r-${panelSeats}s`

const seatEnvelopeSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['ok', 'result', 'error'],
  properties: {
    ok: { type: 'boolean' },
    result: {},
    error: { type: ['string', 'null'] },
  },
}

const unwrap = (envelope) => (
  envelope && typeof envelope === 'object' && envelope.ok === true
    && envelope.result !== null && typeof envelope.result !== 'undefined'
    ? envelope.result
    : null
)

const runSeat = (role, seatIndex, phaseName, label, seatTask, context) => {
  const seatArguments = { task: seatTask, role, seat_index: seatIndex, graph_run_id: graphRunId }
  if (profile) seatArguments.profile = profile
  if (context) seatArguments.context = context
  return agent(
    `You are a transparent seat proxy, not the task solver. Call the MCP tool seat_run exactly once with these arguments:\n${JSON.stringify(seatArguments)}\nIf it succeeds, return exactly {"ok":true,"result":<the complete seat_run result>,"error":null}. If the tool is unavailable, throws, or returns an error, return exactly {"ok":false,"result":null,"error":"<concise reason>"}. Never answer from your own judgment, never call another fusion tool, and never place a failure under ok=true.`,
    { label, phase: phaseName, schema: seatEnvelopeSchema },
  )
}

phase('Draft')
log(`Drafting ${panelSeats} independent plans (${rounds} debate round(s) to follow).`)
const draftEnvelopes = await parallel(Array.from({ length: panelSeats }, (unused, index) => () => runSeat(
  'panel', index, 'Draft', `plan-debate:draft:${index}`,
  `Independently produce an executable plan. Number the steps; for each give the action, the evidence it rests on, the risk, and a verification checkpoint. State assumptions and rollback points. You have not seen any other panelist's plan.\n\nPLANNING TASK:\n${task}`,
)))

let positions = draftEnvelopes
  .map((envelope, index) => ({ seat: index, position: unwrap(envelope) }))
  .filter((entry) => entry.position !== null)

if (positions.length < 2) {
  return {
    task,
    status: 'panel-collapsed',
    graph_run_id: graphRunId,
    rounds_requested: rounds,
    rounds_completed: 0,
    live_seats: positions.length,
    final: null,
    note: `Only ${positions.length} of ${panelSeats} draft seats returned; a debate needs at least 2 positions.`,
  }
}

phase('Debate')
let roundsCompleted = 0
for (let round = 1; round <= rounds; round += 1) {
  const anonymised = positions.map((entry, index) => ({ position: `[${index + 1}]`, plan: entry.position }))
  const rebuttalContext = JSON.stringify({ task, round, positions: anonymised })
  const rebuttalEnvelopes = await parallel(positions.map((entry, index) => () => runSeat(
    'panel', entry.seat, 'Debate', `plan-debate:round${round}:seat${index}`,
    `Debate round ${round} of ${rounds}. You are position [${index + 1}]. Attack the OTHER plans: name concrete failure modes, missing steps, and unverified assumptions. Then revise YOUR plan only where an attack on it actually lands — do not converge for agreement's sake, and keep any minority position you can still defend with evidence. Return your full revised plan.`,
    rebuttalContext,
  )))
  const revised = rebuttalEnvelopes.map(unwrap)
  // A seat that fails mid-debate keeps its last defended position rather than
  // silently dropping out — losing a position mid-debate biases the outcome.
  positions = positions.map((entry, index) => (
    revised[index] !== null ? { seat: entry.seat, position: revised[index] } : entry
  ))
  roundsCompleted = round
}

phase('Judge')
const anonymisedFinal = positions.map((entry, index) => ({ position: `[${index + 1}]`, plan: entry.position }))
const judgeEnvelope = await runSeat(
  'judge', 0, 'Judge', 'plan-debate:judge',
  'Compare the surviving debate positions and return compact JSON only, with keys consensus, contradictions, partial_coverage, unique_insights, minority_findings, blind_spots, final_guidance. Do NOT write the final plan.',
  JSON.stringify({ task, rounds_completed: roundsCompleted, positions: anonymisedFinal }),
)
const judgeAnalysis = unwrap(judgeEnvelope)
if (judgeAnalysis === null) {
  log('Judge seat failed — fusing on the debated positions alone rather than losing the run.')
}

phase('Fuse')
const fuserEnvelope = await runSeat(
  'fuser', 0, 'Fuse', 'plan-debate:fuser',
  'Write the final executable plan. Use the debated positions as primary evidence and the judge analysis as guidance. Do not vote, average, or splice; preserve supported minority positions as explicit alternatives with their trigger conditions. Number the steps; each carries its action, risk, verification checkpoint, and rollback. Return only the plan.',
  JSON.stringify({ task, positions: anonymisedFinal, judge_analysis: judgeAnalysis }),
)
const fused = unwrap(fuserEnvelope)
if (fused === null) {
  return {
    task,
    status: 'fuser-failed',
    graph_run_id: graphRunId,
    rounds_requested: rounds,
    rounds_completed: roundsCompleted,
    live_seats: positions.length,
    final: null,
  }
}

return {
  task,
  status: 'complete',
  graph_run_id: graphRunId,
  final: typeof fused === 'string' ? fused : (fused.final_answer ?? fused),
  provenance: {
    rounds_requested: rounds,
    rounds_completed: roundsCompleted,
    panel_seats: panelSeats,
    positions_live: positions.length,
    profile: profile ?? '(active profile)',
    judge: judgeAnalysis === null ? 'failed (fused without judge)' : 'ok',
  },
}
