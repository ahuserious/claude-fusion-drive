export const meta = {
  name: 'fusion',
  description: 'Generate two configured external drafts, fuse them, and produce one native deliverable',
  phases: [
    { title: 'Panel', detail: 'two independent configured external seats' },
    { title: 'Fuse', detail: 'configured fuser preserves consensus, divergence, and minority findings' },
    { title: 'Deliver', detail: 'native agent verifies evidence and performs any required tool or file work' },
  ],
}

const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'Develop the strongest evidence-grounded solution for the highest-impact open problem in this repository.'
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
  : `fusion-${Date.now().toString(36)}-${randomGraphSuffix}`

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

const runSeat = (role, seatIndex, seatTask, context) => {
  const seatArguments = { task: seatTask, role, seat_index: seatIndex, graph_run_id: graphRunId }
  if (context) seatArguments.context = context
  return agent(
    `You are a transparent external-seat proxy, not the task solver. Call the MCP tool seat_run exactly once with these arguments:\n${JSON.stringify(seatArguments)}\nIf the tool succeeds, return exactly {"ok":true,"result":<the complete seat_run result>,"error":null}. If the tool is unavailable, throws, or returns an error, return exactly {"ok":false,"result":null,"error":"<concise failure reason>"}. Do not answer from your own judgment, call another fusion tool, write files, or place a failure under ok=true.`,
    { label: `fusion:${role}:${seatIndex}`, phase: role === 'fuser' ? 'Fuse' : 'Panel', schema: seatEnvelopeSchema },
  )
}

phase('Panel')
log('Generating independent external drafts through configured routes.')
const drafts = await parallel([
  () => runSeat('panel', 0, `Solve independently. State assumptions, evidence, risks, and a concrete recommendation. Task: ${task}`),
  () => runSeat('panel', -1, `Solve independently using a genuinely different approach. State assumptions, evidence, risks, and a concrete recommendation. Task: ${task}`),
])

const liveDrafts = drafts.map(unwrapSeat).filter(result => result !== null)
if (liveDrafts.length < 2) {
  return { task, graph_run_id: graphRunId, status: 'panel-collapsed', drafts: liveDrafts, fused: null, final: null }
}
phase('Fuse')
const fusionContext = JSON.stringify({ task, drafts: liveDrafts })
const fusedEnvelope = await runSeat(
  'fuser',
  0,
  'Fuse the supplied independent drafts into one solution. Preserve supported minority findings; identify consensus, divergence, discarded claims, and the evidence for each final choice.',
  fusionContext,
)
const fused = unwrapSeat(fusedEnvelope)
if (fused === null) {
  return { task, graph_run_id: graphRunId, status: 'fuser-failed', drafts: liveDrafts, fused: null, final: null }
}

phase('Deliver')
const final = await agent(
  `Produce the final deliverable for the task below using the configured external fusion result as primary guidance. Inspect the repository or run checks with native tools when evidence is needed. If the task requires files, make only the requested changes and verify them. External seats are advisory and never write files; you own and must report every tool call and file change. Do not push, publish, or perform destructive actions.\n\nTASK:\n${task}\n\nFUSION RESULT:\n${JSON.stringify(fused)}`,
  { label: 'fusion:deliver', phase: 'Deliver' },
)

return { task, graph_run_id: graphRunId, status: 'complete', drafts: liveDrafts, fused, final }
