export const meta = {
  name: 'debate',
  description: 'Run a bounded two-seat external debate and send the transcript to a configured judge',
  phases: [
    { title: 'Open', detail: 'two configured panel routes state independent positions' },
    { title: 'Rebut', detail: 'bounded alternating rebuttals receive the accumulated transcript' },
    { title: 'Verdict', detail: 'configured judge rules on claims and evidence rather than vote count' },
  ],
}

const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'Debate the strongest and weakest architectural choice in the current repository.'
const taskInput = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.task === 'string'
    ? inputArgs.task
    : typeof inputArgs === 'string'
      ? inputArgs
      : defaultTask
)
const task = taskInput.trim() || defaultTask
const requestedRounds = inputArgs && typeof inputArgs === 'object' ? Number(inputArgs.rounds) : Number.NaN
const rounds = Number.isInteger(requestedRounds) ? Math.min(5, Math.max(1, requestedRounds)) : 3
const suppliedGraphRunId = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.graph_run_id === 'string'
    ? inputArgs.graph_run_id.trim()
    : ''
)
const validGraphRunId = /^[A-Za-z0-9][A-Za-z0-9-]{0,127}$/
const randomGraphSuffix = `${Math.random().toString(36).slice(2)}000000000000`.slice(0, 12)
const graphRunId = validGraphRunId.test(suppliedGraphRunId)
  ? suppliedGraphRunId
  : `debate-${Date.now().toString(36)}-${randomGraphSuffix}`

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

const unwrapSeat = (envelope) => (
  envelope
  && typeof envelope === 'object'
  && envelope.ok === true
  && envelope.result !== null
  && typeof envelope.result !== 'undefined'
    ? envelope.result
    : null
)

const runSeat = (role, seatIndex, seatTask, context, label, phaseName) => {
  const seatArguments = { task: seatTask, role, seat_index: seatIndex, graph_run_id: graphRunId }
  if (context) seatArguments.context = context
  return agent(
    `You are a transparent external-seat proxy. Call the MCP tool seat_run exactly once with these arguments:\n${JSON.stringify(seatArguments)}\nIf the tool succeeds, return exactly {"ok":true,"result":<the complete seat_run result>,"error":null}. If the tool is unavailable, throws, or returns an error, return exactly {"ok":false,"result":null,"error":"<concise failure reason>"}. Do not debate from your own judgment, call another fusion tool, write files, or place a failure under ok=true.`,
    { label, phase: phaseName, schema: seatEnvelopeSchema },
  )
}

phase('Open')
log(`Opening a ${rounds}-round debate through two configured external routes.`)
const openings = await parallel([
  () => runSeat('panel', 0, `Argue the strongest affirmative position on the question. Ground every claim and state falsifiers. Question: ${task}`, null, 'debate:affirmative:1', 'Open'),
  () => runSeat('panel', -1, `Argue the strongest skeptical or alternative position on the question. Ground every claim and state falsifiers. Question: ${task}`, null, 'debate:skeptic:1', 'Open'),
])
const openingResults = openings.map(unwrapSeat)
const transcript = [
  { round: 1, side: 'affirmative', result: openingResults[0] },
  { round: 1, side: 'skeptic', result: openingResults[1] },
]
if (openingResults.some(result => result === null)) {
  return { task, graph_run_id: graphRunId, status: 'opening-collapsed', rounds, transcript, verdict: null }
}

for (let round = 2; round <= rounds; round += 1) {
  phase('Rebut')
  const affirmativeContext = JSON.stringify({ question: task, transcript })
  const affirmativeEnvelope = await runSeat(
    'panel',
    0,
    `Round ${round}: answer the strongest opposing evidence, concede valid points, and improve the affirmative position.`,
    affirmativeContext,
    `debate:affirmative:${round}`,
    'Rebut',
  )
  const affirmative = unwrapSeat(affirmativeEnvelope)
  transcript.push({ round, side: 'affirmative', result: affirmative })
  if (affirmative === null) {
    return { task, graph_run_id: graphRunId, status: 'rebuttal-failed', failed_round: round, failed_side: 'affirmative', rounds, transcript, verdict: null }
  }

  const skepticContext = JSON.stringify({ question: task, transcript })
  const skepticEnvelope = await runSeat(
    'panel',
    -1,
    `Round ${round}: answer the strongest affirmative evidence, concede valid points, and improve the skeptical or alternative position.`,
    skepticContext,
    `debate:skeptic:${round}`,
    'Rebut',
  )
  const skeptic = unwrapSeat(skepticEnvelope)
  transcript.push({ round, side: 'skeptic', result: skeptic })
  if (skeptic === null) {
    return { task, graph_run_id: graphRunId, status: 'rebuttal-failed', failed_round: round, failed_side: 'skeptic', rounds, transcript, verdict: null }
  }
}

phase('Verdict')
const verdictEnvelope = await runSeat(
  'judge',
  0,
  'Issue one evidence-grounded verdict. Resolve claims individually, preserve valid dissent, identify unresolved uncertainty, and do not decide by vote count.',
  JSON.stringify({ question: task, transcript }),
  'debate:judge',
  'Verdict',
)
const verdict = unwrapSeat(verdictEnvelope)
if (verdict === null) {
  return { task, graph_run_id: graphRunId, status: 'judge-failed', rounds, transcript, verdict: null }
}

return { task, graph_run_id: graphRunId, status: 'complete', rounds, transcript, verdict }
