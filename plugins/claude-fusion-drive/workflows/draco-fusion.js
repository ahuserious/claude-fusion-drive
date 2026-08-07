export const meta = {
  name: 'draco-fusion',
  description: 'Independent panel, compact JSON judge, generative fuser — returns one synthesized answer',
  phases: [
    { title: 'Panel', detail: 'four independent seats, no seat sees another' },
    { title: 'Judge', detail: 'compact JSON diagnosis only, never the final answer' },
    { title: 'Fuse', detail: 'generative synthesis preserving supported minority findings' },
  ],
}

// Seat composition is owned by ~/.claude/claude-fusion-drive/config.json (engine
// draco_fusion). Naming seats here rather than models keeps provider pins, effort,
// and token ceilings in one validated place instead of duplicated in the script.
const ENGINE = 'draco_fusion'
const PANEL_SEATS = [
  'draco-panel-sol-codex',
  'draco-panel-grok45',
  'draco-panel-fable5',
  'draco-panel-deepseek-v4-pro',
]
const JUDGE_SEAT = 'draco-judge-gemini'
const FUSER_SEAT = 'draco-fuser-minimax'
const MIN_LIVE_SEATS = 3

const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'State and solve the highest-impact open problem in this repository, with evidence.'
const rawTask = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.task === 'string'
    ? inputArgs.task
    : typeof inputArgs === 'string' ? inputArgs : defaultTask
)
const task = rawTask.trim() || defaultTask

const suppliedRunId = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.graph_run_id === 'string'
    ? inputArgs.graph_run_id.trim() : ''
)
const validRunId = /^[A-Za-z0-9][A-Za-z0-9-]{0,127}$/
const graphRunId = validRunId.test(suppliedRunId) ? suppliedRunId : `draco-fusion-${PANEL_SEATS.length}seat`

// Every seat subagent answers with this envelope, so a failed seat is an explicit
// ok:false rather than a plausible-looking answer the subagent invented itself.
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

// The seat proxy exists so the large panel/judge JSON stays inside the subagent's
// context. Only what this workflow returns reaches the main conversation.
const runSeat = (seatName, role, phaseName, seatTask, context) => {
  const seatArguments = { engine: ENGINE, seat: seatName, role, task: seatTask, graph_run_id: graphRunId }
  if (context) seatArguments.context = context
  return agent(
    `You are a transparent seat proxy, not the task solver. Call the MCP tool seat_run exactly once with these arguments:\n${JSON.stringify(seatArguments)}\nIf it succeeds, return exactly {"ok":true,"result":<the complete seat_run result>,"error":null}. If the tool is unavailable, throws, or returns an error, return exactly {"ok":false,"result":null,"error":"<concise reason>"}. Never answer from your own judgment, never call another fusion tool, never write files, and never place a failure under ok=true.`,
    { label: `draco:${role}:${seatName}`, phase: phaseName, schema: seatEnvelopeSchema },
  )
}

phase('Panel')
log(`Running ${PANEL_SEATS.length} independent panel seats (no seat sees another).`)
const panelEnvelopes = await parallel(PANEL_SEATS.map((seatName) => () => runSeat(
  seatName,
  'panel',
  'Panel',
  `Solve this independently. State assumptions, the evidence for each claim, failure modes, residual uncertainty, and a concrete recommendation. You have not seen and must not infer any other panelist's answer. Favor correctness over agreement.\n\nTASK:\n${task}`,
)))

const panelReports = panelEnvelopes
  .map((envelope, index) => ({ seat: PANEL_SEATS[index], report: unwrap(envelope) }))
  .filter((entry) => entry.report !== null)

if (panelReports.length < MIN_LIVE_SEATS) {
  return {
    task,
    status: 'panel-collapsed',
    graph_run_id: graphRunId,
    live_seats: panelReports.length,
    min_live_seats: MIN_LIVE_SEATS,
    final: null,
    note: `Only ${panelReports.length} of ${PANEL_SEATS.length} seats returned; below min_live_seats.`,
  }
}

// Anonymised so the judge weighs arguments rather than model reputation.
const anonymisedPanel = panelReports.map((entry, index) => ({
  panelist: `[${index + 1}]`,
  report: entry.report,
}))

phase('Judge')
const judgeEnvelope = await runSeat(
  JUDGE_SEAT,
  'judge',
  'Judge',
  'Compare the panel reports and return compact JSON only, with keys consensus, contradictions, partial_coverage, unique_insights, minority_findings, blind_spots, verification_priorities, final_guidance. Do NOT write the final answer. Return only JSON — no chain-of-thought, no hidden reasoning, no <think> blocks.',
  JSON.stringify({ task, panel: anonymisedPanel }),
)
const judgeAnalysis = unwrap(judgeEnvelope)
if (judgeAnalysis === null) {
  log('Judge seat failed — fusing on raw panel evidence alone rather than losing the run.')
}

phase('Fuse')
const fuserEnvelope = await runSeat(
  FUSER_SEAT,
  'fuser',
  'Fuse',
  'Write the final answer to the original task. Use the panel reports as primary evidence and the judge analysis as guidance. Do not majority-vote, average, splice passages, or blindly obey the judge — preserve supported minority findings and resolve contradictions on evidence. Your answer must stand alone: do not mention the panel, the judge, seats, or model names unless methodology was explicitly requested. Return only the final visible answer, with no chain-of-thought, scratchpad text, or <think> blocks.',
  JSON.stringify({ task, panel: anonymisedPanel, judge_analysis: judgeAnalysis }),
)
const fused = unwrap(fuserEnvelope)
if (fused === null) {
  return {
    task,
    status: 'fuser-failed',
    graph_run_id: graphRunId,
    live_seats: panelReports.length,
    judge_ok: judgeAnalysis !== null,
    final: null,
  }
}

// Only the synthesized answer plus compact provenance crosses back into the main
// conversation — the panel reports and judge JSON stay in the subagents.
return {
  task,
  status: 'complete',
  graph_run_id: graphRunId,
  final: typeof fused === 'string' ? fused : (fused.final_answer ?? fused),
  provenance: {
    panel_seats: panelReports.map((entry) => entry.seat),
    seats_live: `${panelReports.length}/${PANEL_SEATS.length}`,
    judge_seat: judgeAnalysis === null ? `${JUDGE_SEAT} (failed)` : JUDGE_SEAT,
    fuser_seat: FUSER_SEAT,
  },
}
