# Contributing

Keep changes surgical and evidence-backed. New provider features must include request/response parsing tests without real network calls. New configuration fields must be documented in the matching schema (`config.schema.json` for the inherited engine, `fusion-drive.schema.json` for the control plane), represented in the shipped default or an example, and either enforced by runtime code or explicitly labeled informational.

Before submitting a change:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugins/claude-fusion-drive
python3 -m json.tool plugins/claude-fusion-drive/config/default.json >/dev/null
python3 -m json.tool plugins/claude-fusion-drive/config/fusion-drive.default.json >/dev/null
python3 -m json.tool plugins/claude-fusion-drive/schemas/config.schema.json >/dev/null
python3 -m json.tool plugins/claude-fusion-drive/schemas/fusion-drive.schema.json >/dev/null
```

Do not commit credentials, `.env` files, runtime outputs, or user overrides. Do not weaken exact-hash gates, author/reviewer separation, default retention controls, or the external-seat/workspace boundary without an explicit security review.
