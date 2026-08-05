export const meta = {
  name: 'coordinate',
  description: 'Create strict disjoint assignments, execute them in native worktrees, and integrate verified results',
  phases: [
    { title: 'Plan', detail: 'native coordinator emits a strict disjoint assignment graph' },
    { title: 'Work', detail: 'one native worktree-isolated agent per assignment' },
    { title: 'Integrate', detail: 'native integrator checks ownership, diffs, and tests before applying results' },
  ],
}

const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'Plan and implement the smallest complete improvement to the current repository with disjoint work ownership.'
const taskInput = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.task === 'string'
    ? inputArgs.task
    : typeof inputArgs === 'string'
      ? inputArgs
      : defaultTask
)
const task = taskInput.trim() || defaultTask
const requestedWorkers = inputArgs && typeof inputArgs === 'object' ? Number(inputArgs.workers) : Number.NaN
const maxWorkers = Number.isInteger(requestedWorkers) ? Math.min(8, Math.max(2, requestedWorkers)) : 4

const assignmentSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['summary', 'assignments'],
  properties: {
    summary: { type: 'string' },
    assignments: {
      type: 'array',
      minItems: 1,
      maxItems: maxWorkers,
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['id', 'objective', 'owned_paths', 'dependencies', 'acceptance_criteria'],
        properties: {
          id: { type: 'string' },
          objective: { type: 'string' },
          owned_paths: { type: 'array', minItems: 1, items: { type: 'string' } },
          dependencies: { type: 'array', items: { type: 'string' } },
          acceptance_criteria: { type: 'array', minItems: 1, items: { type: 'string' } },
        },
      },
    },
  },
}
const workerSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['assignment_id', 'worktree', 'summary', 'files_changed', 'tests', 'ready_to_integrate'],
  properties: {
    assignment_id: { type: 'string' },
    worktree: { type: 'string' },
    summary: { type: 'string' },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests: { type: 'array', items: { type: 'string' } },
    ready_to_integrate: { type: 'boolean' },
  },
}
const integrationSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['status', 'integrated_assignments', 'files_changed', 'tests', 'unresolved'],
  properties: {
    status: { enum: ['integrated', 'partial', 'blocked'] },
    integrated_assignments: { type: 'array', items: { type: 'string' } },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests: { type: 'array', items: { type: 'string' } },
    unresolved: { type: 'array', items: { type: 'string' } },
  },
}

phase('Plan')
log('Mapping a strict assignment graph before any implementation.')
const plan = await agent(
  `Inspect the repository and decompose the task into at most ${maxWorkers} independently implementable assignments. This is planning only: do not edit files. Each assignment must have a unique id, explicit objective, non-overlapping owned_paths, dependencies by id, and mechanical acceptance criteria. If safe disjoint ownership is impossible, return one assignment.\n\nTASK:\n${task}`,
  { label: 'coordinate:assignment-plan', phase: 'Plan', schema: assignmentSchema },
)
if (!plan || !Array.isArray(plan.assignments) || plan.assignments.length === 0) {
  return { task, status: 'planning-failed', plan: plan || null, worker_reports: [], integration: null }
}

phase('Work')
const workerReports = await pipeline(
  plan.assignments,
  assignment => agent(
    `Execute exactly this assignment in your isolated worktree. You own only the listed paths; do not edit another assignment's paths, commit, push, publish, or merge. Read dependencies for context but do not modify their ownership. Run the listed acceptance checks and return exact evidence.\n\nOVERALL TASK:\n${task}\n\nASSIGNMENT:\n${JSON.stringify(assignment)}`,
    { label: `coordinate:worker:${assignment.id}`, phase: 'Work', isolation: 'worktree', schema: workerSchema },
  ),
)

phase('Integrate')
const integration = await agent(
  `Integrate only verified coordinate-workflow results into the current repository. Inspect every reported worktree and diff yourself. Confirm each changed path belongs to that assignment and that assignments are disjoint. Apply ready results in dependency order, run combined checks, and stop with partial or blocked status on overlap, missing worktrees, failed checks, or scope drift. Do not push or publish.\n\nTASK:\n${task}\n\nPLAN:\n${JSON.stringify(plan).slice(0, 24000)}\n\nWORKER REPORTS:\n${JSON.stringify(workerReports).slice(0, 36000)}`,
  { label: 'coordinate:integrator', phase: 'Integrate', schema: integrationSchema },
)

return { task, status: integration ? integration.status : 'blocked', plan, worker_reports: workerReports.filter(Boolean), integration: integration || null }
