# Sluvo

This directory is reserved for the Sluvo product line: a standalone infinite canvas and AI workflow surface for comic and short-drama creation.

Current status:
- Product planning lives in `doc/`.
- Runtime implementation has not started here yet.
- The recommended implementation path is a standalone frontend subsite, such as `sluvo.shenlu.top`, that reuses the existing Shenlu backend, auth, project workspace, asset, generation, and task systems.

Development docs:
- `AGENTS.md`: repository rules for Codex and future agents.
- `doc/PRD.md`: product requirements and scope.
- `doc/API_DEVELOPMENT.md`: how the Sluvo frontend should call the existing Shenlu backend APIs.
- `doc/DEVELOPMENT.md`: local setup and verification workflow.
- `doc/UI_REQUIREMENTS.md`: product UI and interaction rules.
- `doc/FRONTEND_ARCHITECTURE.md`: recommended frontend structure.
- `doc/BACKEND_CONTRACTS.md`: backend API and model contracts reused from Shenlu.
- `doc/CHANGELOG_DEV.md`: development changelog.

