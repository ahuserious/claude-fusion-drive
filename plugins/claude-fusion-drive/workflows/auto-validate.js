export const meta = {
  name: 'auto-validate',
  description: 'Write a validator-first acceptance gate, prove RED, build, and repair through a bounded immutable-gate loop',
  phases: [
    { title: 'Gate', detail: 'native validator writes the acceptance gate and proves baseline RED' },
    { title: 'Build', detail: 'native builder implements without editing the gate' },
    { title: 'Verify', detail: 'independent native verifier checks gate SHA before and after execution' },
    { title: 'Repair', detail: 'bounded native fix loop uses gate failures without changing the gate' },
  ],
}

const inputArgs = typeof args === 'undefined' ? undefined : args
const defaultTask = 'Implement and verify the smallest safe fix for the highest-impact failing behavior in this repository.'
const taskInput = (
  inputArgs && typeof inputArgs === 'object' && typeof inputArgs.task === 'string'
    ? inputArgs.task
    : typeof inputArgs === 'string'
      ? inputArgs
      : defaultTask
)
const task = taskInput.trim() || defaultTask
const requestedMaxFixes = inputArgs && typeof inputArgs === 'object'
  ? Number(inputArgs.max_fixes)
  : Number.NaN
const maxFixes = Number.isInteger(requestedMaxFixes)
  ? Math.min(5, Math.max(0, requestedMaxFixes))
  : 2

const gateSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['gate_path', 'gate_sha256', 'baseline_red', 'baseline_exit_code', 'baseline_output'],
  properties: {
    gate_path: { type: 'string' },
    gate_sha256: { type: 'string' },
    baseline_red: { type: 'boolean' },
    baseline_exit_code: { type: 'integer' },
    baseline_output: { type: 'string' },
  },
}
const buildSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['summary', 'files_changed', 'commands_run', 'reported_gate_exit_code'],
  properties: {
    summary: { type: 'string' },
    files_changed: { type: 'array', items: { type: 'string' } },
    commands_run: { type: 'array', items: { type: 'string' } },
    reported_gate_exit_code: { type: 'integer' },
  },
}
const verificationSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['before_sha256', 'after_sha256', 'passed', 'exit_code', 'gate_output'],
  properties: {
    before_sha256: { type: 'string' },
    after_sha256: { type: 'string' },
    passed: { type: 'boolean' },
    exit_code: { type: 'integer' },
    gate_output: { type: 'string' },
  },
}

phase('Gate')
log('Authoring the acceptance gate before implementation.')
const gate = await agent(
  `You are the validator and act before any builder. Read the repository and translate the task into a deterministic acceptance gate. Write a unique executable gate under .claude/fusion-drive/gates/. The gate must test observable requirements, not implementation trivia. Run it against the untouched baseline: it must fail for the task-specific reason (RED), not because the gate is broken. Compute SHA-256 of the final gate file only after that run. Do not implement the task. Return the exact gate path, SHA, exit code, and bounded output.\n\nTASK:\n${task}`,
  { label: 'auto-validate:gate-author', phase: 'Gate', schema: gateSchema },
)
if (!gate || !gate.baseline_red || gate.baseline_exit_code === 0) {
  return { task, status: 'invalid-baseline', max_fixes: maxFixes, gate: gate || null, attempts: [] }
}

phase('Build')
let buildReport = await agent(
  `Implement the task in the current repository and run focused checks. The acceptance gate already exists at ${gate.gate_path} with immutable SHA-256 ${gate.gate_sha256}. You MUST NOT edit, replace, regenerate, rename, chmod, or delete that gate. Treat it as read-only criteria. Do not push or publish. Return an exact file/change/test report.\n\nTASK:\n${task}`,
  { label: 'auto-validate:build', phase: 'Build', schema: buildSchema },
)

const attempts = []
for (let attempt = 0; attempt <= maxFixes; attempt += 1) {
  phase('Verify')
  const verification = await agent(
    `Independently verify the implementation. Before running anything, compute SHA-256 of ${gate.gate_path}; run that exact gate; then compute SHA-256 again. The expected immutable SHA is ${gate.gate_sha256}. Do not edit the gate or implementation. Set passed true only when the gate exits zero and both hashes equal the expected SHA. Return bounded gate output.\n\nTASK:\n${task}\n\nBUILDER REPORT:\n${JSON.stringify(buildReport).slice(0, 12000)}`,
    { label: `auto-validate:gate-check:${attempt}`, phase: 'Verify', schema: verificationSchema },
  )
  attempts.push({ attempt, build_report: buildReport || null, verification: verification || null })

  const gateUnchanged = Boolean(
    verification
      && verification.before_sha256 === gate.gate_sha256
      && verification.after_sha256 === gate.gate_sha256,
  )
  if (!gateUnchanged) {
    return { task, status: 'gate-mutated', max_fixes: maxFixes, gate, attempts }
  }
  if (verification.passed && verification.exit_code === 0) {
    return { task, status: 'passed', max_fixes: maxFixes, gate, attempts }
  }
  if (attempt === maxFixes) break

  phase('Repair')
  buildReport = await agent(
    `Repair only the implementation defects demonstrated by the immutable acceptance gate. Gate path: ${gate.gate_path}. Expected SHA-256: ${gate.gate_sha256}. You MUST NOT edit, replace, regenerate, rename, chmod, or delete the gate. Inspect the failure evidence, make the smallest safe fix, and rerun focused checks. Do not push or publish.\n\nTASK:\n${task}\n\nFAILURE EVIDENCE:\n${JSON.stringify(verification).slice(0, 12000)}`,
    { label: `auto-validate:repair:${attempt + 1}`, phase: 'Repair', schema: buildSchema },
  )
}

return { task, status: 'failed', max_fixes: maxFixes, gate, attempts }
