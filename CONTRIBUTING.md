# Contributing To TestForge

Thanks for helping improve TestForge.

## Development Setup

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Run checks:

```bash
python -m compileall run_cli.py src cli tests examples
python -m pytest tests/unit/ -q
```

## What Good Contributions Look Like

- Keep changes scoped.
- Add or update unit tests for behavior changes.
- Prefer existing patterns in `src/cli/`.
- Preserve clear failure reasons and evidence capture.
- Do not save raw passwords, tokens, or API keys.
- Make browser actions verifiable, not just executable.

## Useful Areas

- New ExplorerAgent extraction tools
- Better VerifierAgent assertions
- More robust local-model JSON planning
- Site-specific test-plan generation
- Safer auth recovery
- Report templates
- CI-friendly non-interactive runner

## Pull Request Checklist

- [ ] The change has a clear user-facing purpose.
- [ ] Unit tests pass.
- [ ] New behavior is covered by tests where practical.
- [ ] README or docs are updated when commands or behavior change.
- [ ] No secrets or local-only paths are committed.

## Coding Style

- Use structured data instead of parsing prose when possible.
- Prefer Playwright semantic locators and stable refs.
- Keep user-facing CLI output concise and actionable.
- When a task fails, return a useful reason and save evidence where possible.
