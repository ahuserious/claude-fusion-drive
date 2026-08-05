export const meta = {
  name: 'best-of-n',
  description: 'Generate N configured external candidates, judge them, and have a native agent deliver the selected solution',
  phases: [
    { title: 'Generate', detail: 'configured panel routes generate independent candidates with cycling enabled' },
    { title: 'Select', detail: 'configured judge compares candidates against explicit criteria' },
    { title: 'Deliver', detail: 'native agent verifies and materializes the selected result' },
  ],
}

const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'Propose the best evidence-grounded solution to the highest-impact open problem in this repository.'
const taskInput = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.task === 'string'
    ? inputArgs.task
    : typeof inputArgs === 'string'
      ? inputArgs
      : defaultTask
)
const task = taskInput.trim() || defaultTask
const requestedCandidates = inputArgs && typeof inputArgs === 'object' ? Number(inputArgs.n) : Number.NaN
const candidateCount = Number.isInteger(requestedCandidates) ? Math.min(8, Math.max(2, requestedCandidates)) : 4
const suppliedGraphRunId = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.graph_run_id === 'string'
    ? inputArgs.graph_run_id.trim()
    : ''
)
const validGraphRunId = /^[A-Za-z0-9][A-Za-z0-9-]{0,127}$/
const randomGraphSuffix = `${Math.random().toString(36).slice(2)}000000000000`.slice(0, 12)
const graphRunId = validGraphRunId.test(suppliedGraphRunId)
  ? suppliedGraphRunId
  : `best-of-n-${Date.now().toString(36)}-${randomGraphSuffix}`

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

const runSeat = (role, seatIndex, seatTask, context, cycle, phaseName) => {
  const seatArguments = { task: seatTask, role, seat_index: seatIndex, graph_run_id: graphRunId }
  if (context) seatArguments.context = context
  if (cycle) seatArguments.cycle = true
  return agent(
    `You are a transparent external-seat proxy. Call the MCP tool seat_run exactly once with these arguments:\n${JSON.stringify(seatArguments)}\nIf the tool succeeds, return exactly {"ok":true,"result":<the complete seat_run result>,"error":null}. If the tool is unavailable, throws, or returns an error, return exactly {"ok":false,"result":null,"error":"<concise failure reason>"}. Do not solve or judge from your own knowledge, call another fusion tool, write files, or place a failure under ok=true.`,
    { label: `best-of-n:${role}:${seatIndex}`, phase: phaseName, schema: seatEnvelopeSchema },
  )
}

phase('Generate')
log(`Generating ${candidateCount} independently routed candidates.`)
const candidates = await parallel(
  Array.from({ length: candidateCount }, (_, index) => () => runSeat(
    'panel',
    index,
    `Candidate ${index + 1} of ${candidateCount}: solve independently. Optimize for correctness, evidence, simplicity, and explicit failure handling. Do not imitate another candidate. Task: ${task}`,
    null,
    true,
    'Generate',
  )),
)
const liveCandidates = candidates.map(unwrapSeat).filter(result => result !== null)
if (liveCandidates.length < candidateCount) {
  return { task, graph_run_id: graphRunId, status: 'candidate-collapse', requested: candidateCount, candidates: liveCandidates, selection: null, final: null }
}

phase('Select')
const selectionEnvelope = await runSeat(
  'judge',
  -1,
  'Select the strongest candidate using correctness, evidence, simplicity, realistic failure handling, and task fit. Identify the winner, preserved ideas from other candidates, rejected claims, and unresolved risks. Do not vote-count.',
  JSON.stringify({ task, candidates: liveCandidates }),
  false,
  'Select',
)
const selection = unwrapSeat(selectionEnvelope)
if (selection === null) {
  return { task, graph_run_id: graphRunId, status: 'judge-failed', requested: candidateCount, candidates: liveCandidates, selection: null, final: null }
}

phase('Deliver')
const final = await agent(
  `Deliver the selected best-of-N solution for the task. Treat the configured judge result as primary guidance, but inspect repository evidence and run checks yourself. If files are required, make only task-scoped changes and verify them. External seats never write files; you own and must report all tool calls and changes. Do not push, publish, or perform destructive actions.\n\nTASK:\n${task}\n\nSELECTION:\n${JSON.stringify(selection)}`,
  { label: 'best-of-n:deliver', phase: 'Deliver' },
)

return { task, graph_run_id: graphRunId, status: 'complete', requested: candidateCount, candidates: liveCandidates, selection, final }
