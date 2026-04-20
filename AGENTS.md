# quick_tools guidance

## Scope
- Keep every tool small, direct, and installable with minimal friction.
- Prefer standard library solutions unless an external dependency clearly pays for itself.
- Do not add features "just in case". Add only what the CLI actually needs.

## CLI design
- Default to a single top-level entrypoint: `quick-tools`.
- Subcommands should stay sparse and predictable.
- Keep flags to a minimum. If a behavior can be sensible by default, do that instead of adding a flag.
- Error messages should be short and actionable, not verbose tracebacks.

## Runtime behavior
- Favor portability across local and remote machines.
- Do not assume a desktop session or browser is available on the machine running the command.
- Prefer explicit, inspectable behavior over hidden automation.

## Dependencies
- Keep the package lightweight.
- Avoid heavyweight frameworks for simple servers or CLIs.
- Optional integrations are acceptable only when failure is clean and the core tool still works without them.

## Code style
- Match the existing code style in the repo.
- Choose readable implementations over clever ones.
- Keep comments rare and only where they materially improve clarity.
