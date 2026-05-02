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

2026-05-02 update: Sluvo now has its own backend tables and `/api/sluvo/*` route surface inside the existing AIdrama backend. It still reuses Shenlu `User`, `Team`, `TeamMemberLink`, token auth, and infrastructure, but Sluvo project/canvas truth no longer uses `Script`, `CanvasWorkspace`, `CanvasNode`, or `CanvasEdge` as the primary data model.

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

## 4. Sluvo Standalone APIs

These are the primary browser contracts for the standalone Sluvo product line.

| Capability | Method | Path |
| --- | --- | --- |
| Create Sluvo project | POST | `/api/sluvo/projects` |
| List Sluvo projects | GET | `/api/sluvo/projects` |
| Read Sluvo project | GET | `/api/sluvo/projects/{project_id}` |
| Patch Sluvo project | PATCH | `/api/sluvo/projects/{project_id}` |
| Soft-delete Sluvo project | DELETE | `/api/sluvo/projects/{project_id}` |
| Read main canvas | GET | `/api/sluvo/projects/{project_id}/canvas` |
| Patch canvas snapshot/viewport | PATCH | `/api/sluvo/canvases/{canvas_id}` |
| Create node | POST | `/api/sluvo/canvases/{canvas_id}/nodes` |
| Patch node | PATCH | `/api/sluvo/canvases/{canvas_id}/nodes/{node_id}` |
| Create edge | POST | `/api/sluvo/canvases/{canvas_id}/edges` |
| Patch edge | PATCH | `/api/sluvo/canvases/{canvas_id}/edges/{edge_id}` |
| Batch save canvas | POST | `/api/sluvo/canvases/{canvas_id}/batch` |
| List/add project members | GET/POST | `/api/sluvo/projects/{project_id}/members` |
| Patch/remove project member | PATCH/DELETE | `/api/sluvo/projects/{project_id}/members/{user_id}` |
| Create canvas Agent session | POST | `/api/sluvo/projects/{project_id}/agent/sessions` |
| Read canvas Agent session | GET | `/api/sluvo/agent/sessions/{session_id}` |
| Send Agent message/proposed action | POST | `/api/sluvo/agent/sessions/{session_id}/messages` |
| Approve Agent action | POST | `/api/sluvo/agent/actions/{action_id}/approve` |
| Cancel Agent action | POST | `/api/sluvo/agent/actions/{action_id}/cancel` |

All IDs are encoded with the existing Shenlu `encode_id` scheme. Canvas, node, and edge updates support `expectedRevision`; stale writes return `409`.

Frontend write mapping:
- Home prompt creation stores the prompt in a `note` canvas node with `data.prompt` and `data.body`.
- Direct canvas cards map to supported backend node types: text/note, image, video, audio, upload, generation, and group.
- The frontend writes a compatibility `snapshot` on every batch save, but structured node and edge rows remain the primary store.
- Agent endpoints exist in the contract but are not called by the current frontend milestone.

## 5. Legacy Project Workspace APIs

These routes remain available for compatibility with earlier Sluvo planning and Shenlu project workspace experiments, but they are no longer the primary Sluvo standalone contract.

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

## 6. Domain Mapping

Sluvo standalone product terms map to new `sluvo_*` backend models.

| Sluvo Term | Backend Truth |
| --- | --- |
| Project | `SluvoProject` |
| Project member | `SluvoProjectMember` |
| Canvas | `SluvoCanvas` |
| Canvas node | `SluvoCanvasNode` |
| Canvas edge | `SluvoCanvasEdge` |
| Canvas asset | `SluvoCanvasAsset` |
| Agent session | `SluvoAgentSession` |
| Agent event | `SluvoAgentEvent` |
| Agent action | `SluvoAgentAction` |
| Canvas mutation/audit log | `SluvoCanvasMutation` |
| User/account/team | existing `User`, `Team`, `TeamMemberLink` |

## 7. Data Ownership

Canvas layout stores:

- position
- size
- hidden state
- collapsed state
- selected view metadata
- ports and display hints
- node data/config/style
- snapshot JSON for recovery and frontend compatibility

Canvas layout must not depend on old Shenlu project truth for:

- `Script`
- `Episode`
- `Panel`
- `SharedResource`
- legacy `CanvasWorkspace/CanvasNode/CanvasEdge`

## 8. New API Requests

If Sluvo needs a backend capability that does not exist:

1. Inspect the existing backend first.
2. Prefer adding a thin adapter to the existing backend.
3. Document the endpoint in this file.
4. Update `doc/API_DEVELOPMENT.md` if the frontend call pattern changes.

Do not create provider-specific browser calls as a workaround.
