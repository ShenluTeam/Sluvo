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
| List deleted Sluvo projects | GET | `/api/sluvo/projects?includeDeleted=true` |
| Read Sluvo project | GET | `/api/sluvo/projects/{project_id}` |
| Patch Sluvo project | PATCH | `/api/sluvo/projects/{project_id}` |
| Soft-delete Sluvo project | DELETE | `/api/sluvo/projects/{project_id}` |
| Restore Sluvo project | POST | `/api/sluvo/projects/{project_id}/restore` |
| Permanently delete Sluvo project | DELETE | `/api/sluvo/projects/{project_id}/permanent` |
| Read main canvas | GET | `/api/sluvo/projects/{project_id}/canvas` |
| Patch canvas snapshot/viewport | PATCH | `/api/sluvo/canvases/{canvas_id}` |
| Create node | POST | `/api/sluvo/canvases/{canvas_id}/nodes` |
| Patch node | PATCH | `/api/sluvo/canvases/{canvas_id}/nodes/{node_id}` |
| Create edge | POST | `/api/sluvo/canvases/{canvas_id}/edges` |
| Patch edge | PATCH | `/api/sluvo/canvases/{canvas_id}/edges/{edge_id}` |
| Batch save canvas | POST | `/api/sluvo/canvases/{canvas_id}/batch` |
| Upload canvas asset | POST | `/api/sluvo/canvases/{canvas_id}/assets/upload` |
| Upload canvas asset as base64 | POST | `/api/sluvo/canvases/{canvas_id}/assets/upload/base64` |
| List/add project members | GET/POST | `/api/sluvo/projects/{project_id}/members` |
| Patch/remove project member | PATCH/DELETE | `/api/sluvo/projects/{project_id}/members/{user_id}` |
| Create canvas Agent session | POST | `/api/sluvo/projects/{project_id}/agent/sessions` |
| List project Agent sessions | GET | `/api/sluvo/projects/{project_id}/agent/sessions` |
| Create Agent workflow run | POST | `/api/sluvo/projects/{project_id}/agent/runs` |
| List project Agent workflow runs | GET | `/api/sluvo/projects/{project_id}/agent/runs` |
| Read Agent workflow run timeline | GET | `/api/sluvo/agent/runs/{run_id}` |
| Continue Agent workflow run | POST | `/api/sluvo/agent/runs/{run_id}/continue` |
| Confirm Agent media cost | POST | `/api/sluvo/agent/runs/{run_id}/confirm-cost` |
| Retry Agent workflow step | POST | `/api/sluvo/agent/steps/{step_id}/retry` |
| Read canvas Agent session | GET | `/api/sluvo/agent/sessions/{session_id}` |
| Send Agent message/proposed action | POST | `/api/sluvo/agent/sessions/{session_id}/messages` |
| Analyze text node locally | POST | `/api/sluvo/projects/{project_id}/text-node/analyze` |
| Approve Agent action | POST | `/api/sluvo/agent/actions/{action_id}/approve` |
| Cancel Agent action | POST | `/api/sluvo/agent/actions/{action_id}/cancel` |
| List/create user Agent templates | GET/POST | `/api/sluvo/agents` |
| Read/update/delete user Agent template | GET/PATCH/DELETE | `/api/sluvo/agents/{agent_id}` |
| Publish Agent to community | POST | `/api/sluvo/agents/{agent_id}/community/publish` |
| List community Agents | GET | `/api/sluvo/community/agents` |
| Read community Agent detail | GET | `/api/sluvo/community/agents/{publication_id}` |
| Fork community Agent | POST | `/api/sluvo/community/agents/{publication_id}/fork` |
| Unpublish community Agent | POST | `/api/sluvo/community/agents/{publication_id}/unpublish` |
| List community canvases | GET | `/api/sluvo/community/canvases` |
| Read community canvas detail | GET | `/api/sluvo/community/canvases/{publication_id}` |
| Publish project to community | POST | `/api/sluvo/projects/{project_id}/community/publish` |
| Fork community canvas | POST | `/api/sluvo/community/canvases/{publication_id}/fork` |
| Unpublish community canvas | POST | `/api/sluvo/community/canvases/{publication_id}/unpublish` |

Project payloads include `firstImageUrl` when the project has at least one active image asset. The frontend may use this as the recent-project cover; if no first image exists, project cards should not invent a showcase cover.

Community canvas list responses are public and return card metadata only. Community detail and fork require `shenlu_token`. Publishing stores a snapshot of the source canvas; later source-project edits do not alter the community version until the user publishes again. Fork creates a new Sluvo project and references the original OSS media URLs instead of copying large media files.

All IDs are encoded with the existing Shenlu `encode_id` scheme. Canvas, node, and edge updates support `expectedRevision`; stale writes return `409`.

Frontend write mapping:
- Home prompt creation stores the prompt in a `note` canvas node with `data.prompt` and `data.body`.
- Direct canvas cards map to supported backend node types: text/note, image, video, audio, upload, generation, and group.
- The frontend writes a compatibility `snapshot` on every batch save, but structured node and edge rows remain the primary store.
- Upload nodes persist media through `SluvoCanvasAsset` and existing `storage_object`; `blob:` preview URLs are never valid backend truth.
- Uploaded Sluvo media is stored in OSS by user namespace and Sluvo project: `users/{namespace}/sluvo/projects/{project}/canvases/{canvas}/{images|videos|audio}/...`.
- Sluvo uploads enforce the existing user storage quota path; the default free-user capacity is `5GB`. Duplicate uploads in the same user/project scope can reuse an existing OSS object by `sha256 + user_id + project_id`.
- Canvas Agent endpoints are called by the current canvas milestone. Messages create proposed actions; approving an action applies its batch-compatible `patch` through the existing canvas save path and records `SluvoCanvasMutation` with Agent session/action IDs. Project session listing returns recent events/actions so the frontend can restore project-local Agent history.
- `agentProfile: "auto"` is the default 创作总监 contract. The backend resolves the specialist Agent and action type from the prompt and canvas context, then exposes `resolvedProfile`, `resolvedActionType`, `routingReason`, and `modelCode` in the Agent event/action input summary.
- Agent model choices currently allow `deepseek-v4-flash` and `deepseek-v4-pro`. Unknown values normalize to `deepseek-v4-flash`; when `DEEPSEEK_API_KEY` exists, the selected model is used to draft proposal content, with deterministic fallback on failure. Future models should be added server-side before exposing them in the frontend.
- User Agent template ids may be sent as `agentProfile` or `agentTemplateId`; the backend uses the template's role prompt, use cases, input/output types, tools, approval policy, and default model when building the Agent prompt and action context.
- Agent-node runs include `sourceSurface: "node"` and `targetNodeId`; after approval/cancel/failure, the backend updates the target Agent node's last action state in node `data`.
- Text node local analysis uses the same DeepSeek model policy but is not part of the Agent action lifecycle. It returns `{ content, modelCode, llmUsed, summary }`; callers persist the returned Markdown through normal canvas saving.

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
| Community canvas publication | `SluvoCommunityCanvas` |
| User Agent template | `SluvoAgentTemplate` |
| Community Agent publication | `SluvoCommunityAgent` |
| Agent session | `SluvoAgentSession` |
| Agent event | `SluvoAgentEvent` |
| Agent action | `SluvoAgentAction` |
| Agent workflow run | `SluvoAgentRun` |
| Agent workflow step | `SluvoAgentStep` |
| Agent workflow artifact | `SluvoAgentArtifact` |
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
