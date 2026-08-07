from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "plugins" / "claude-fusion-drive" / "workflows"
EXPECTED_PHASES = {
    "opinion": ["Perspectives"],
    "fusion": ["Panel", "Fuse", "Deliver"],
    "draco-fusion": ["Panel", "Judge", "Fuse"],
    "plan-debate": ["Draft", "Debate", "Judge", "Fuse"],
    "ultraplan": ["Stage", "Curate", "Debate", "Fuse"],
    "auto-validate": ["Gate", "Build", "Verify", "Repair"],
    "debate": ["Open", "Rebut", "Verdict"],
    "parallel": ["Work"],
    "coordinate": ["Plan", "Work", "Integrate"],
    "best-of-n": ["Generate", "Select", "Deliver"],
}

NODE_INSPECTOR = r"""
const fs = require('fs')
const vm = require('vm')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor

const path = process.argv[1]
const runtimeArgs = JSON.parse(process.argv[2])
const source = fs.readFileSync(path, 'utf8')
const metaPrefix = 'export const meta = '
if (!source.startsWith(metaPrefix)) throw new Error('meta must be the first statement')
const firstBreak = source.indexOf('\n\n')
if (firstBreak < 0) throw new Error('meta must be separated from the workflow body')
const metaLiteral = source.slice(metaPrefix.length, firstBreak).trim()
const meta = vm.runInNewContext(`(${metaLiteral})`, Object.create(null), { timeout: 100 })
const executable = source.replace(/^export const meta\s*=/, 'const meta =')
const workflow = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', executable)

const trace = { agents: [], phases: [], logs: [] }
let gateCheckCount = 0

async function agent(prompt, options = {}) {
  const record = { prompt, options }
  trace.agents.push(record)
  const label = options.label || ''

  if (label === 'auto-validate:gate-author') {
    return {
      gate_path: '.claude/fusion-drive/gates/mock-gate.sh',
      gate_sha256: 'gate-sha',
      baseline_red: true,
      baseline_exit_code: 1,
      baseline_output: 'expected RED',
    }
  }
  if (label === 'auto-validate:build' || label.startsWith('auto-validate:repair:')) {
    return {
      summary: label,
      files_changed: ['src/example.py'],
      commands_run: ['test-command'],
      reported_gate_exit_code: 1,
    }
  }
  if (label.startsWith('auto-validate:gate-check:')) {
    gateCheckCount += 1
    const mutated = Boolean(runtimeArgs && runtimeArgs.__test_mutate_gate)
    const failures = Number(runtimeArgs && runtimeArgs.__test_fail_gate_checks) || 0
    const passed = !mutated && gateCheckCount > failures
    return {
      before_sha256: 'gate-sha',
      after_sha256: mutated ? 'changed-gate-sha' : 'gate-sha',
      passed,
      exit_code: passed ? 0 : 1,
      gate_output: passed ? 'PASS' : 'FAIL',
    }
  }
  if (label === 'coordinate:assignment-plan') {
    return {
      summary: 'two disjoint assignments',
      assignments: [
        {
          id: 'implementation',
          objective: 'implement behavior',
          owned_paths: ['src/'],
          dependencies: [],
          acceptance_criteria: ['focused test passes'],
        },
        {
          id: 'documentation',
          objective: 'document behavior',
          owned_paths: ['docs/'],
          dependencies: ['implementation'],
          acceptance_criteria: ['documentation is accurate'],
        },
      ],
    }
  }
  if (label.startsWith('coordinate:worker:')) {
    const assignmentId = label.slice('coordinate:worker:'.length)
    return {
      assignment_id: assignmentId,
      worktree: `/tmp/${assignmentId}`,
      summary: `completed ${assignmentId}`,
      files_changed: [assignmentId === 'implementation' ? 'src/example.py' : 'docs/example.md'],
      tests: ['focused test passes'],
      ready_to_integrate: true,
    }
  }
  if (label === 'coordinate:integrator') {
    return {
      status: 'integrated',
      integrated_assignments: ['implementation', 'documentation'],
      files_changed: ['src/example.py', 'docs/example.md'],
      tests: ['combined checks pass'],
      unresolved: [],
    }
  }
  if (label.startsWith('parallel:worker:')) {
    const worker = Number(label.slice('parallel:worker:'.length))
    return {
      worker,
      worktree: `/tmp/parallel-${worker}`,
      summary: `worker ${worker}`,
      files_changed: [`worker-${worker}.txt`],
      tests: ['mock check'],
      risks: [],
    }
  }
  if (prompt.includes('MCP tool seat_run exactly once')) {
    const failedLabels = Array.isArray(runtimeArgs && runtimeArgs.__test_fail_external_labels)
      ? runtimeArgs.__test_fail_external_labels
      : []
    const truthyLabels = Array.isArray(runtimeArgs && runtimeArgs.__test_truthy_external_labels)
      ? runtimeArgs.__test_truthy_external_labels
      : []
    if (failedLabels.includes(label)) {
      return { ok: false, result: null, error: `mock external failure for ${label}` }
    }
    if (truthyLabels.includes(label)) {
      return { ok: 'true', result: { content: `invalid truthy result for ${label}` }, error: null }
    }
    return { ok: true, result: { content: `mock external result for ${label}` }, error: null }
  }
  return `mock result for ${label}`
}

async function parallel(tasks) {
  return Promise.all(tasks.map(task => task()))
}

async function pipeline(items, ...stages) {
  return Promise.all(items.map(async item => {
    let value = item
    for (let index = 0; index < stages.length; index += 1) {
      value = index === 0 ? await stages[index](item) : await stages[index](value, item)
    }
    return value
  }))
}

function phase(title) { trace.phases.push(title) }
function log(message) { trace.logs.push(message) }

workflow(agent, parallel, pipeline, phase, log, runtimeArgs)
  .then(result => process.stdout.write(JSON.stringify({ meta, trace, result })))
  .catch(error => {
    process.stderr.write(error.stack || String(error))
    process.exitCode = 1
  })
"""


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute Dynamic Workflow fixtures")
    return node


def _inspect(name: str, args: Any) -> dict[str, Any]:
    completed = subprocess.run(
        [_node(), "-e", NODE_INSPECTOR, str(WORKFLOWS / f"{name}.js"), json.dumps(args)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return json.loads(completed.stdout)


def _seat_call(record: dict[str, Any]) -> dict[str, Any]:
    match = re.search(r"arguments:\n(\{.*\})\nIf the tool", record["prompt"])
    assert match, record["prompt"]
    return json.loads(match.group(1))


def _external_proxy_records(inspected: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        record
        for record in inspected["trace"]["agents"]
        if "MCP tool seat_run exactly once" in record["prompt"]
    ]


def test_workflow_metadata_and_javascript_execute_through_runtime_wrapper() -> None:
    assert {path.stem for path in WORKFLOWS.glob("*.js")} == set(EXPECTED_PHASES)

    seen_names: set[str] = set()
    for name, expected_phases in EXPECTED_PHASES.items():
        inspected = _inspect(name, {"task": "inspect the repository"})
        meta = inspected["meta"]
        assert set(meta) == {"name", "description", "phases"}
        assert meta["name"] == name
        assert meta["name"] not in seen_names
        seen_names.add(meta["name"])
        assert meta["description"].strip()
        assert [item["title"] for item in meta["phases"]] == expected_phases
        assert all(set(item) == {"title", "detail"} and item["detail"].strip() for item in meta["phases"])
        assert set(inspected["trace"]["phases"]) <= set(expected_phases)


@pytest.mark.parametrize("name", sorted(EXPECTED_PHASES))
def test_task_normalization_accepts_raw_strings_and_rejects_blank_tasks(name: str) -> None:
    raw = _inspect(name, "  explicit raw task  ")
    assert raw["result"]["task"] == "explicit raw task"

    blank = _inspect(name, {"task": "   "})
    assert blank["result"]["task"].strip()
    assert blank["result"]["task"] != "explicit raw task"


def test_external_proxy_routes_are_semantic_and_model_agnostic() -> None:
    opinion = _inspect("opinion", {"task": "compare approaches"})
    opinion_calls = [_seat_call(record) for record in opinion["trace"]["agents"]]
    assert [(call["role"], call["seat_index"]) for call in opinion_calls] == [
        ("panel", 0),
        ("panel", -1),
    ]
    assert opinion["result"]["merged"] is False

    fusion = _inspect("fusion", {"task": "fuse approaches"})
    fusion_proxy_records = [record for record in fusion["trace"]["agents"] if "seat_run" in record["prompt"]]
    fusion_calls = [_seat_call(record) for record in fusion_proxy_records]
    assert [(call["role"], call["seat_index"]) for call in fusion_calls] == [
        ("panel", 0),
        ("panel", -1),
        ("fuser", 0),
    ]
    assert fusion_calls[-1]["context"]
    assert fusion["trace"]["agents"][-1]["options"]["label"] == "fusion:deliver"

    for inspected in (opinion, fusion):
        for record in inspected["trace"]["agents"]:
            assert "model" not in record["options"]
            assert not re.search(
                r"\b(?:gpt-|claude-|grok-|sonnet|opus|fable|terra)\w*",
                record["prompt"],
                re.IGNORECASE,
            )


@pytest.mark.parametrize(
    ("name", "extra_args"),
    [
        ("opinion", {}),
        ("fusion", {}),
        ("debate", {"rounds": 2}),
        ("best-of-n", {"n": 3}),
    ],
)
def test_external_workflow_propagates_one_explicit_graph_run_id(
    name: str,
    extra_args: dict[str, Any],
) -> None:
    graph_run_id = "Graph-Run-42"
    inspected = _inspect(
        name,
        {"task": "trace one graph", "graph_run_id": f"  {graph_run_id}  ", **extra_args},
    )
    calls = [_seat_call(record) for record in _external_proxy_records(inspected)]

    assert calls
    assert {call["graph_run_id"] for call in calls} == {graph_run_id}
    assert inspected["result"]["graph_run_id"] == graph_run_id


def test_external_workflow_generates_valid_collision_resistant_graph_run_ids() -> None:
    first = _inspect("fusion", {"task": "generate one id", "graph_run_id": "invalid id"})
    second = _inspect("fusion", {"task": "generate another id", "graph_run_id": "   "})
    graph_run_id_pattern = re.compile(r"^fusion-[a-z0-9]+-[a-z0-9]{12}$")

    assert graph_run_id_pattern.fullmatch(first["result"]["graph_run_id"])
    assert graph_run_id_pattern.fullmatch(second["result"]["graph_run_id"])
    assert first["result"]["graph_run_id"] != second["result"]["graph_run_id"]


@pytest.mark.parametrize("name", ["opinion", "fusion", "debate", "best-of-n"])
def test_external_proxies_require_strict_result_envelopes(name: str) -> None:
    inspected = _inspect(name, {"task": "inspect proxy contracts", "rounds": 1, "n": 2})

    for record in _external_proxy_records(inspected):
        schema = record["options"]["schema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["required"] == ["ok", "result", "error"]
        assert schema["properties"]["ok"] == {"type": "boolean"}
        assert schema["properties"]["error"] == {"type": ["string", "null"]}
        assert 'return exactly {"ok":true' in record["prompt"]
        assert 'return exactly {"ok":false' in record["prompt"]
        assert "place a failure under ok=true" in record["prompt"]


def test_external_seat_contexts_never_silently_truncate_model_results() -> None:
    expected_unbounded_contexts = {
        "fusion": [
            (
                "const fusionContext = JSON.stringify({ task, drafts: liveDrafts })",
                "JSON.stringify({ task, drafts: liveDrafts }).slice(",
            ),
            (
                "FUSION RESULT:\\n${JSON.stringify(fused)}",
                "JSON.stringify(fused).slice(",
            ),
        ],
        "debate": [
            (
                "const affirmativeContext = JSON.stringify({ question: task, transcript })",
                "JSON.stringify({ question: task, transcript }).slice(",
            ),
            (
                "const skepticContext = JSON.stringify({ question: task, transcript })",
                "JSON.stringify({ question: task, transcript }).slice(",
            ),
            (
                "JSON.stringify({ question: task, transcript }),",
                "JSON.stringify({ question: task, transcript }).slice(",
            ),
        ],
        "best-of-n": [
            (
                "JSON.stringify({ task, candidates: liveCandidates }),",
                "JSON.stringify({ task, candidates: liveCandidates }).slice(",
            ),
            (
                "SELECTION:\\n${JSON.stringify(selection)}",
                "JSON.stringify(selection).slice(",
            ),
        ],
    }

    for name, context_contracts in expected_unbounded_contexts.items():
        source = (WORKFLOWS / f"{name}.js").read_text(encoding="utf-8")
        for expected_context, forbidden_truncation in context_contracts:
            assert expected_context in source
            assert forbidden_truncation not in source


def test_opinion_does_not_treat_a_failed_envelope_as_a_live_view() -> None:
    inspected = _inspect(
        "opinion",
        {"task": "compare", "__test_fail_external_labels": ["opinion:seat:0"]},
    )

    assert inspected["result"]["status"] == "seat-failed"
    assert inspected["result"]["views"][0]["result"] is None
    assert "mock external failure" in inspected["result"]["views"][0]["error"]
    assert inspected["result"]["views"][1]["result"] is not None


@pytest.mark.parametrize(
    ("failure_key", "failure_label"),
    [
        ("__test_fail_external_labels", "fusion:panel:0"),
        ("__test_truthy_external_labels", "fusion:panel:0"),
    ],
)
def test_fusion_collapses_before_fuser_on_failed_or_non_boolean_ok_panel(
    failure_key: str,
    failure_label: str,
) -> None:
    inspected = _inspect("fusion", {"task": "fuse", failure_key: [failure_label]})
    labels = [record["options"]["label"] for record in inspected["trace"]["agents"]]

    assert inspected["result"]["status"] == "panel-collapsed"
    assert len(inspected["result"]["drafts"]) == 1
    assert labels == ["fusion:panel:0", "fusion:panel:-1"]
    assert "fusion:fuser:0" not in labels
    assert "fusion:deliver" not in labels


def test_fusion_does_not_deliver_when_fuser_fails() -> None:
    inspected = _inspect(
        "fusion",
        {"task": "fuse", "__test_fail_external_labels": ["fusion:fuser:0"]},
    )
    labels = [record["options"]["label"] for record in inspected["trace"]["agents"]]

    assert inspected["result"]["status"] == "fuser-failed"
    assert labels == ["fusion:panel:0", "fusion:panel:-1", "fusion:fuser:0"]
    assert "fusion:deliver" not in labels


def test_debate_runs_bounded_rebuttals_then_a_configured_judge() -> None:
    inspected = _inspect("debate", {"task": "choose an architecture", "rounds": 2})
    calls = [_seat_call(record) for record in inspected["trace"]["agents"]]
    assert inspected["result"]["rounds"] == 2
    assert len(inspected["result"]["transcript"]) == 4
    assert [(call["role"], call["seat_index"]) for call in calls[:4]] == [
        ("panel", 0),
        ("panel", -1),
        ("panel", 0),
        ("panel", -1),
    ]
    assert (calls[-1]["role"], calls[-1]["seat_index"]) == ("judge", 0)
    assert calls[-1]["context"]


def test_debate_stops_before_rebuttal_and_judge_when_an_opening_fails() -> None:
    inspected = _inspect(
        "debate",
        {
            "task": "choose an architecture",
            "rounds": 3,
            "__test_fail_external_labels": ["debate:skeptic:1"],
        },
    )
    labels = [record["options"]["label"] for record in inspected["trace"]["agents"]]

    assert inspected["result"]["status"] == "opening-collapsed"
    assert labels == ["debate:affirmative:1", "debate:skeptic:1"]
    assert inspected["result"]["verdict"] is None


@pytest.mark.parametrize(
    ("failed_label", "failed_side", "expected_labels"),
    [
        (
            "debate:affirmative:2",
            "affirmative",
            ["debate:affirmative:1", "debate:skeptic:1", "debate:affirmative:2"],
        ),
        (
            "debate:skeptic:2",
            "skeptic",
            [
                "debate:affirmative:1",
                "debate:skeptic:1",
                "debate:affirmative:2",
                "debate:skeptic:2",
            ],
        ),
    ],
)
def test_debate_stops_before_judge_when_a_rebuttal_fails(
    failed_label: str,
    failed_side: str,
    expected_labels: list[str],
) -> None:
    inspected = _inspect(
        "debate",
        {
            "task": "choose an architecture",
            "rounds": 3,
            "__test_fail_external_labels": [failed_label],
        },
    )
    labels = [record["options"]["label"] for record in inspected["trace"]["agents"]]

    assert inspected["result"]["status"] == "rebuttal-failed"
    assert inspected["result"]["failed_round"] == 2
    assert inspected["result"]["failed_side"] == failed_side
    assert labels == expected_labels
    assert "debate:judge" not in labels


def test_best_of_n_cycles_configured_panel_indices_before_judging() -> None:
    inspected = _inspect("best-of-n", {"task": "generate candidates", "n": 3})
    proxy_records = [record for record in inspected["trace"]["agents"] if "seat_run" in record["prompt"]]
    calls = [_seat_call(record) for record in proxy_records]
    candidates = calls[:3]
    assert [(call["role"], call["seat_index"], call["cycle"]) for call in candidates] == [
        ("panel", 0, True),
        ("panel", 1, True),
        ("panel", 2, True),
    ]
    assert calls[3]["role"] == "judge"
    assert "cycle" not in calls[3]
    assert inspected["trace"]["agents"][-1]["options"]["label"] == "best-of-n:deliver"


def test_best_of_n_collapses_before_judge_when_any_requested_candidate_fails() -> None:
    inspected = _inspect(
        "best-of-n",
        {
            "task": "generate candidates",
            "n": 3,
            "__test_fail_external_labels": ["best-of-n:panel:1"],
        },
    )
    labels = [record["options"]["label"] for record in inspected["trace"]["agents"]]

    assert inspected["result"]["status"] == "candidate-collapse"
    assert len(inspected["result"]["candidates"]) == 2
    assert labels == ["best-of-n:panel:0", "best-of-n:panel:1", "best-of-n:panel:2"]
    assert not any(label.startswith("best-of-n:judge:") for label in labels)
    assert "best-of-n:deliver" not in labels


def test_best_of_n_does_not_deliver_when_judge_fails() -> None:
    inspected = _inspect(
        "best-of-n",
        {
            "task": "generate candidates",
            "n": 3,
            "__test_fail_external_labels": ["best-of-n:judge:-1"],
        },
    )
    labels = [record["options"]["label"] for record in inspected["trace"]["agents"]]

    assert inspected["result"]["status"] == "judge-failed"
    assert labels[-1] == "best-of-n:judge:-1"
    assert "best-of-n:deliver" not in labels


def test_parallel_and_coordinate_writers_use_worktree_isolation() -> None:
    parallel_run = _inspect("parallel", {"task": "implement independently", "workers": 3})
    workers = parallel_run["trace"]["agents"]
    assert len(workers) == 3
    assert all(record["options"]["isolation"] == "worktree" for record in workers)
    assert parallel_run["result"]["merged"] is False

    coordinate = _inspect("coordinate", {"task": "split and integrate", "workers": 4})
    planner = coordinate["trace"]["agents"][0]
    schema = planner["options"]["schema"]
    assert schema["additionalProperties"] is False
    assignment = schema["properties"]["assignments"]["items"]
    assert assignment["additionalProperties"] is False
    assert assignment["required"] == [
        "id",
        "objective",
        "owned_paths",
        "dependencies",
        "acceptance_criteria",
    ]
    coordinate_workers = [
        record for record in coordinate["trace"]["agents"]
        if record["options"]["label"].startswith("coordinate:worker:")
    ]
    assert len(coordinate_workers) == 2
    assert all(record["options"]["isolation"] == "worktree" for record in coordinate_workers)
    assert coordinate["result"]["integration"]["status"] == "integrated"


def test_auto_validate_orders_red_gate_before_build_and_bounds_repairs() -> None:
    inspected = _inspect(
        "auto-validate",
        {"task": "fix behavior", "max_fixes": 2, "__test_fail_gate_checks": 2},
    )
    labels = [record["options"]["label"] for record in inspected["trace"]["agents"]]
    assert labels == [
        "auto-validate:gate-author",
        "auto-validate:build",
        "auto-validate:gate-check:0",
        "auto-validate:repair:1",
        "auto-validate:gate-check:1",
        "auto-validate:repair:2",
        "auto-validate:gate-check:2",
    ]
    assert inspected["result"]["status"] == "passed"
    assert inspected["result"]["gate"]["baseline_red"] is True
    assert len(inspected["result"]["attempts"]) == 3

    bounded = _inspect(
        "auto-validate",
        {"task": "never passes", "max_fixes": 999, "__test_fail_gate_checks": 999},
    )
    bounded_labels = [record["options"]["label"] for record in bounded["trace"]["agents"]]
    assert bounded["result"]["status"] == "failed"
    assert bounded["result"]["max_fixes"] == 5
    assert len([label for label in bounded_labels if ":repair:" in label]) == 5
    assert len([label for label in bounded_labels if ":gate-check:" in label]) == 6


def test_auto_validate_fails_closed_when_gate_sha_changes() -> None:
    inspected = _inspect(
        "auto-validate",
        {"task": "fix behavior", "max_fixes": 5, "__test_mutate_gate": True},
    )
    labels = [record["options"]["label"] for record in inspected["trace"]["agents"]]
    assert inspected["result"]["status"] == "gate-mutated"
    assert len(inspected["result"]["attempts"]) == 1
    assert not any(":repair:" in label for label in labels)
