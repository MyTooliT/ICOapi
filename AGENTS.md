Follow the coding standards in ~/dev/coding-standards/AGENTS.md.
Deviations from them:
- `.github/workflows/hardware-tests.yaml` uses the self-hosted RevPi runner in this public repo. Accepted: the runner is guarded by running only for PRs and commits of the maintainers, and the workflow is disabled (manual trigger only).
