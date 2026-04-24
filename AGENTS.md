# Sluvo Development Notes

## Project Goal

Sluvo is a standalone infinite canvas and AI workflow frontend for Shenlu comic / short-drama creation.

The product should feel independent, but it must reuse the existing Shenlu backend instead of creating a separate backend for MVP.

Primary local paths:
- Sluvo frontend repository: `E:\ljtpc\work\Sluvo`
- Existing Shenlu backend repository: `E:\ljtpc\work\AIdrama\backend`

## Read Before Changing Code

When working in this repository, read these files first:
1. `AGENTS.md`
2. `doc/PRD.md`
3. `doc/API_DEVELOPMENT.md`
4. `doc/DEVELOPMENT.md`
5. `doc/UI_REQUIREMENTS.md`
6. `doc/FRONTEND_ARCHITECTURE.md`
7. `doc/BACKEND_CONTRACTS.md`

If backend behavior is unclear, inspect the existing backend in `E:\ljtpc\work\AIdrama\backend` instead of guessing.

## Architecture Decision

Sluvo is a new frontend surface.

Backend strategy:
- Reuse the existing FastAPI backend from `AIdrama`.
- Reuse existing auth, team permissions, project workspace, canvas projection, asset, storyboard, generation, task, billing, and OSS systems.
- Do not create a new Sluvo backend unless explicitly requested.

Frontend API rule:
- Frontend code should call relative API paths like `/api/projects/{id}/workspace`.
- Do not hard-code `http://127.0.0.1:8000` or production backend hosts inside components or stores.
- In local development, use the dev server proxy to forward `/api` to the existing backend.
- In production, use Nginx or the platform gateway to forward `sluvo.shenlu.top/api/*` to the existing backend.

## Auth Rules

Sluvo should reuse Shenlu user authentication:
- Token key: `shenlu_token`
- Request header: `Authorization: Bearer <token>`
- Backend permission chain remains the existing Shenlu chain.

Do not invent a new token format, login storage key, or user model without explicit approval.

## Recommended Frontend Stack

Use a new frontend app under this repository.

Recommended default:
- Vue 3
- Vite
- Pinia
- Vue Router
- Fetch-based API client

Canvas engine:
- Start with Vue Flow if the first MVP is graph-oriented.
- Evaluate tldraw / Konva / PixiJS only if freeform drawing becomes more important than executable workflow graph behavior.

## Implementation Boundaries

Sluvo may own:
- Infinite canvas UI
- Node and edge presentation
- Node inspector
- Task drawer
- Template drawer
- API client wrappers
- Project list and project open flow

Existing backend owns:
- Users and teams
- Projects, currently backed by `Script`
- Episodes
- Shared resources and versions
- Storyboard shots, currently backed by `Panel`
- Generation units and inputs
- Generation records
- Task jobs
- Billing and points
- Provider dispatch and polling
- OSS upload and file storage

Canvas layout should not become the only source of truth for project content.

## Development Commands

Typical local development:

```powershell
# Existing backend
cd E:\ljtpc\work\AIdrama\backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000

# Sluvo frontend, after the app is scaffolded
cd E:\ljtpc\work\Sluvo
npm install
npm run dev
```

Use a Vite dev proxy so `/api` requests from the Sluvo dev server reach `http://127.0.0.1:8000`.

## Documentation Rules

Update `doc/API_DEVELOPMENT.md` when:
- API proxy strategy changes
- Auth storage changes
- Backend base path changes
- New Sluvo-specific API wrappers are added
- Production deployment routing changes

Update `doc/DEVELOPMENT.md` when:
- local startup commands change
- dev ports change
- setup requirements change

Update `doc/UI_REQUIREMENTS.md` when:
- product interaction rules change
- node types or task states change
- copywriting rules change

Update `doc/FRONTEND_ARCHITECTURE.md` when:
- frontend stack changes
- route structure changes
- source directory ownership changes

Update `doc/BACKEND_CONTRACTS.md` when:
- Sluvo depends on a new backend endpoint
- endpoint payload or ownership changes
- model mapping changes

Update `doc/PRD.md` when:
- Product scope changes
- MVP node types change
- Feature status changes
- Major milestones change

Update `doc/CHANGELOG_DEV.md` for every non-trivial implementation or documentation task.

## Prohibited

- Do not modify `E:\ljtpc\work\AIdrama\frontend1` for Sluvo work.
- Do not duplicate backend provider logic inside Sluvo.
- Do not make Sluvo store project truth only in local canvas JSON.
- Do not use generated build output, archives, or dependency folders as source of truth.
- Do not save edited files in non-UTF-8 encodings.
