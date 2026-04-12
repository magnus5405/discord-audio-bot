# Contributing

Thanks for helping improve Discord Audio Bot.

## Issues and pull requests

- **Bugs or feature ideas** — open an issue with what you expected, what happened, and your environment (TUI-logs, OS, Python version if running from source, release version if using a Windows build). 
- **Pull requests** — small, focused changes are easier to review. Describe the problem and the approach in the PR body.

## Development setup

1. **Clone** the repository and create a virtual environment (Python **3.11+**).
2. **Install** the package in editable mode: `pip install -e .`
3. **FFmpeg** must be on `PATH` when developing from source (see [README.md](README.md#prerequisites)).

Full prerequisites, `.env` / `settings.json`, and run modes are documented in the [Development](README.md#development) section of the README.

## Checks before you push

Run formatters, linter, type checker, and tests (same expectations as [copilot-instructions](.github/copilot-instructions.md#git-workflow)):

```bash
ruff check src/ tests/
mypy src/ --ignore-missing-imports --strict
pytest
```

## Git conventions

- **Commits** — present tense; say what changed and why.
- **Branches** — `feature/…` or `fix/…` as appropriate.

## License

By contributing, you agree that your contributions are licensed under the same terms as the project ([MIT](LICENSE)).
