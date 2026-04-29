# Sluvo Backend Contracts

Version: 0.1
Date: 2026-04-24

Related detailed inventory:
- `doc/API_SHENLU_TOP.md` is the audited `api.shenlu.top` API map for Sluvo. It separates P0 direct-call contracts from OpenClaw API-key endpoints, legacy compatibility routes, admin routes, and callback-only routes.

## 1. Backend Source

Sluvo reuses the existing Shenlu FastAPI backend.

Local backend path:

```text
E:\ljtpc\work\AIdrama\backend
```

Do not create a duplicate backend inside Sluvo for MVP.

## 2. Contract Rule

Sluvo frontend should treat these APIs as backend contracts.

If behavior is unclear, inspect the backend source:

- `backend/routers/project_workspace.py`
- `backend/services/project_workspace_service.py`
- `backend/services/canvas_projection_service.py`
- `backend/routers/generate.py`
- `backend/routers/resource.py`
- `backend/routers/auth.py`

## 3. Auth Contract

Requests to protected APIs must include:

```http
Authorization: Bearer <shenlu_token>
```

Frontend token storage:

```text
localStorage.shenlu_token
```

Login uses the existing auth endpoint:

| Capability | Method | Path |
| --- | --- | --- |
| Email/password login | POST | `/api/auth/login` |

## 4. Project Workspace APIs

These are the recommended P0 Sluvo browser contracts. See `doc/API_SHENLU_TOP.md` for all production API paths and routing caveats.

| Capability | Method | Path |
| --- | --- | --- |
| Read full project workspace | GET | `/api/projects/{project_id}/workspace` |
| Create project | POST | `/api/projects` |
| Create episode | POST | `/api/projects/{project_id}/episodes` |
| Save episode script | PATCH | `/api/episodes/{episode_id}/script` |
| Patch asset | PATCH | `/api/assets/{asset_id}` |
| Patch storyboard shot | PATCH | `/api/storyboard-shots/{shot_id}` |
| Create asset image unit | POST | `/api/assets/{asset_id}/image-units` |
| Create shot image unit | POST | `/api/storyboard-shots/{shot_id}/image-units` |
| Create shot video unit | POST | `/api/storyboard-shots/{shot_id}/video-units` |
| Connect generation input | POST | `/api/generation-units/{target_unit_id}/inputs` |
| Run generation unit | POST | `/api/generation-units/{unit_id}/run` |
| Hide canvas projection node | POST | `/api/canvas/nodes/{node_id}/hide` |
| Restore canvas projection node | POST | `/api/canvas/nodes/{node_id}/restore` |

## 5. Domain Mapping

Sluvo product terms map to existing backend models.

| Sluvo Term | Backend Truth |
| --- | --- |
| Project | `Script` |
| Episode / script section | `Episode` |
| Asset | `SharedResource` |
| Asset version | `SharedResourceVersion` |
| Storyboard shot | `Panel` |
| Generation unit | `GenerationUnit` |
| Generation input | `GenerationUnitInput` |
| Media output | `MediaAsset` / `GenerationRecord` |
| Task state | `TaskJob` |
| Canvas workspace | `CanvasWorkspace` |
| Canvas node | `CanvasNode` |
| Canvas edge | `CanvasEdge` |

## 6. Data Ownership

Canvas layout may store:

- position
- size
- hidden state
- collapsed state
- selected view metadata
- ports and display hints

Canvas layout must not become the only truth for:

- script text
- asset list
- storyboard rows
- generated media
- task state
- billing state

## 7. New API Requests

If Sluvo needs a backend capability that does not exist:

1. Inspect the existing backend first.
2. Prefer adding a thin adapter to the existing backend.
3. Document the endpoint in this file.
4. Update `doc/API_DEVELOPMENT.md` if the frontend call pattern changes.

Do not create provider-specific browser calls as a workaround.
