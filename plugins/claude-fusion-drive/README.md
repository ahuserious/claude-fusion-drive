# Claude Fusion Drive plugin bundle

The Claude Code plugin entrypoint is `.claude-plugin/plugin.json`; MCP configuration is `.mcp.json`. The schema-v2 runtime is in `claude_fusion_drive`, while `relentless_inception` is the preserved provider/fusion engine inherited under its original license.

Use `/claude-fusion-drive` for the full plan-confirm-thread-execute lifecycle.
The canonical API-backed `maximum-intelligence` profile remains the default;
the subscription-only Grok/Claude workflow is selected explicitly as
`subscription-oauth`. The direct-xAI plus Claude OAuth workflow is selected
explicitly as `xai-claude-oauth` and has no OpenRouter route or fallback.
Prefer durable `fuse_start` and `approval_gate_start` jobs, polling with
`job_status` and retrieving results with `job_result`.

Use `/claude-fusion-drive-config` for exact-hash configuration proposals and
approval. New lifecycles bind to `claude_code.TaskCreate`; legacy
`create_goal` receipts remain compatible.
