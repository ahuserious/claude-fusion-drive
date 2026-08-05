export const meta = {
  name: 'opinion',
  description: 'Ask two configured external seats for independent perspectives without merging them',
  phases: [
    { title: 'Perspectives', detail: 'two independent configured panel seats, no merge' },
  ],
}

const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'Assess the current repository and identify its highest-impact design decision.'
const taskInput = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.task === 'string'
    ? inputArgs.task
    : typeof inputArgs === 'string'
      ? inputArgs
      : defaultTask
)
const task = taskInput.trim() || defaultTask
const suppliedGraphRunId = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.graph_run_id === 'string'
    ? inputArgs.graph_run_id.trim()
    : ''
)
const validGraphRunId = /^[A-Za-z0-9][A-Za-z0-9-]{0,127}$/
const randomGraphSuffix = `${Math.random().toString(36).slice(2)}000000000000`.slice(0, 12)
const graphRunId = validGraphRunId.test(suppliedGraphRunId)
  ? suppliedGraphRunId
  : `opinion-${Date.now().toString(36)}-${randomGraphSuffix}`

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

const seatError = (envelope) => (
  envelope && envelope.ok === false && typeof envelope.error === 'string' && envelope.error.trim()
    ? envelope.error.trim()
    : 'The external seat returned an invalid or failed result envelope.'
)

const runSeat = (seatIndex) => agent(
  `You are a transparent external-seat proxy, not the opinion author. Call the MCP tool seat_run exactly once with these arguments:\n${JSON.stringify({ task: `Give an independent, evidence-grounded opinion on this task: ${task}`, role: 'panel', seat_index: seatIndex, graph_run_id: graphRunId })}\nIf the tool succeeds, return exactly {"ok":true,"result":<the complete seat_run result>,"error":null}. If the tool is unavailable, throws, or returns an error, return exactly {"ok":false,"result":null,"error":"<concise failure reason>"}. Do not answer from your own judgment, call another fusion tool, write files, or place a failure under ok=true.`,
  { label: `opinion:seat:${seatIndex}`, phase: 'Perspectives', schema: seatEnvelopeSchema },
)

phase('Perspectives')
log('Requesting two independent configured external perspectives.')
const views = await parallel([
  () => runSeat(0),
  () => runSeat(-1),
])
const viewResults = views.map(unwrapSeat)

return {
  task,
  graph_run_id: graphRunId,
  status: viewResults.every(result => result !== null) ? 'complete' : 'seat-failed',
  merged: false,
  views: [
    { seat_index: 0, result: viewResults[0], error: viewResults[0] === null ? seatError(views[0]) : null },
    { seat_index: -1, result: viewResults[1], error: viewResults[1] === null ? seatError(views[1]) : null },
  ],
}
