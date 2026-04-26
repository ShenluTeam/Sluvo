# Sluvo

This repository hosts the Sluvo product line: a standalone infinite canvas and AI workflow surface for comic and short-drama creation.

Current status:
- Product planning lives in `doc/`.
- A runnable local frontend MVP now lives in `apps/sluvo-web`.
- The MVP currently uses mock data and does not call the real backend yet.
- The recommended production path remains a standalone frontend subsite, such as `sluvo.shenlu.top`, that reuses the existing Shenlu backend, auth, project workspace, asset, generation, and task systems.

Development docs:
- `AGENTS.md`: repository rules for Codex and future agents.
- `doc/PRD.md`: product requirements and scope.
- `doc/API_DEVELOPMENT.md`: how the Sluvo frontend should call the existing Shenlu backend APIs.
- `doc/DEVELOPMENT.md`: local setup and verification workflow.
- `doc/UI_REQUIREMENTS.md`: product UI and interaction rules.
- `doc/FRONTEND_ARCHITECTURE.md`: recommended frontend structure.
- `doc/BACKEND_CONTRACTS.md`: backend API and model contracts reused from Shenlu.
- `doc/CHANGELOG_DEV.md`: development changelog.

## Local commands

From the repository root:

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

App-specific commands are also available under `apps/sluvo-web`.
