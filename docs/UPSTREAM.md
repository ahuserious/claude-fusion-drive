# Upstream provenance

Claude Fusion Drive 0.1.0 is the Claude Code edition of the following lineage:

1. Relentless Inception 0.1.4 (`ahuserious/relentless-inception-codex`) — the inherited multi-model deliberation engine, vendored in this repository as the `relentless_inception` package from `https://github.com/ahuserious/relentless-inception-codex`, source commit `0cb3dec` at the time the first derivative was created. The inherited engine remains at version 0.1.4.
2. `codex-fusion-drive` 0.1.2 — the validated Codex edition, which added the schema-v2 Fusion Drive control plane, OAuth CLI adapters, durable asynchronous jobs, rescue, human simulation, and deterministic auto-evaluation on a Codex host. Its recorded benchmark and release evidence is retained here as inherited upstream evidence.
3. `claude-fusion-drive` 0.1.0 — this repository, the Claude Code edition at `https://github.com/ahuserious/claude-fusion-drive`. The host contract moved from Codex thread creation to Claude Code goal/task receipts (`claude_code.TaskCreate`), packaging moved to `.claude-plugin` with `${CLAUDE_PLUGIN_ROOT}` MCP wiring, and the default active profile is `xai-claude-oauth`.

The internal Python package name `relentless_inception` is retained to keep inherited behavior and regression coverage identifiable. New behavior resides in `claude_fusion_drive`. The original `LICENSE`, `NOTICE.md`, security documentation, and source notices remain in this repository.
