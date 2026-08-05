export const meta = {
  name: 'parallel',
  description: 'Run the same task in multiple native worktree-isolated agents and retain every result without merging',
  phases: [
    { title: 'Work', detail: 'independent native agents work in isolated worktrees' },
  ],
}

const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'Independently diagnose and fix the highest-impact failing behavior in the current repository.'
const taskInput = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.task === 'string'
    ? inputArgs.task
    : typeof inputArgs === 'string'
      ? inputArgs
      : defaultTask
)
const task = taskInput.trim() || defaultTask
const requestedWorkers = inputArgs && typeof inputArgs === 'object' ? Number(inputArgs.workers) : Number.NaN
const workerCount = Number.isInteger(requestedWorkers) ? Math.min(8, Math.max(2, requestedWorkers)) : 2
const reportSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['worker', 'worktree', 'summary', 'files_changed', 'tests', 'risks'],
  properties: {
    worker: { type: 'integer' },
    worktree: { type: 'string' },
    summary: { type: 'string' },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests: { type: 'array', items: { type: 'string' } },
    risks: { type: 'array', items: { type: 'string' } },
  },
}

phase('Work')
log(`Running ${workerCount} independent native workers with no merge stage.`)
const results = await parallel(
  Array.from({ length: workerCount }, (_, index) => () => agent(
    `Worker ${index + 1} of ${workerCount}: complete the task independently in your isolated worktree. Inspect before editing, make only task-scoped changes, run relevant checks, and do not coordinate with or copy another worker. Do not commit, push, publish, or alter other worktrees. Return the exact worktree path and evidence.\n\nTASK:\n${task}`,
    { label: `parallel:worker:${index + 1}`, phase: 'Work', isolation: 'worktree', schema: reportSchema },
  )),
)

return { task, merged: false, worker_count: workerCount, results: results.filter(Boolean) }
