# api.shenlu.top API Inventory For Sluvo

Version: 0.1
Date: 2026-04-30
Source audit:
- Production `https://api.shenlu.top/openapi.json`, checked 2026-04-30.
- Local Shenlu backend source at `/Volumes/T9/ljtpc/work/AIdrama/backend`.
- OpenClaw contract at `/Volumes/T9/ljtpc/work/AIdrama/docs/OPENCLAW_API_CONTRACT.md`.

## 1. Executive Summary

Sluvo can call `https://api.shenlu.top/api/*` directly from the browser for normal logged-in product workflows, as long as it uses the shared Shenlu login token:

```http
Authorization: Bearer <localStorage.shenlu_token>
```

For the Sluvo MVP, prefer these API families:

| Priority | API family | Why |
| --- | --- | --- |
| P0 | `/api/auth/*`, `/api/user/*` | Login, user profile, points, storage, account state. |
| P0 | `/api/projects/*`, `/api/episodes/{id}/script`, `/api/assets/*`, `/api/storyboard-shots/*`, `/api/generation-units/*` | Best current contract for Sluvo's project workspace, canvas projection, editable assets, shots, generation units, and run actions. |
| P0 | `/api/creative/*`, `/api/tasks/*` | Productized image/video/audio/editing generation, uploads, records, task polling and cancellation. |
| P1 | `/api/assistant/*`, `/api/agent-workflow/*` | Useful when Sluvo embeds the Shenlu Agent. SSE stream paths should use `ai.shenlu.top` or a no-buffered stream host, not normal cached API routing. |
| P1 | `/api/team/*` | Useful for team/project collaboration surfaces. |
| External only | `/api/openclaw/*`, `/skill.md` | Stable API-key contract for external Agents, CLI and MCP. Sluvo browser code should not treat this as the primary logged-in app API. |
| Avoid for MVP | `/api/generate*`, `/api/panels*`, `/api/scripts*`, `/api/resources*`, `/api/canvas/scripts*` | Existing or legacy app-facing routes. Use only as compatibility fallback when the project workspace contract lacks a needed operation. |
| Do not call from Sluvo | `/api/admin/*`, `/api/provider-callbacks/*`, most `/api/external-agent/*`, WeChat webhook routes | Admin, upstream callback, or existing-platform integration surfaces. |

## 2. Domain And Auth Rules

Sluvo production build:

```env
VITE_API_BASE=https://api.shenlu.top
```

Browser calls should be composed by the shared API client:

```js
apiFetch('/api/projects/{project_id}/workspace')
```

Do not hard-code `https://api.shenlu.top` inside components. Keep the host in `VITE_API_BASE`.

### Login Token APIs

Normal Shenlu app APIs use the user login token stored in:

```text
localStorage.shenlu_token
```

Request header:

```http
Authorization: Bearer <shenlu_token>
```

This is the right path for Sluvo browser UI.

### OpenClaw API Key APIs

OpenClaw endpoints are also hosted under `api.shenlu.top`, but they use a separate API key generated in the Shenlu user center:

```http
Authorization: Bearer shenlu-xxxxxxxxxxxx
X-API-Key: shenlu-xxxxxxxxxxxx
X-API-Token: shenlu-xxxxxxxxxxxx
```

Use OpenClaw for external Agent, CLI, MCP or server-to-server automation. Do not call `/api/openclaw/*` as Sluvo's main browser API unless the product is explicitly acting as an OpenClaw client.

### Admin Token APIs

Admin APIs use admin auth and are not part of Sluvo MVP.

### SSE Streams

The deployment split reserves `ai.shenlu.top` for long-lived SSE streams:

| Stream path | Recommendation |
| --- | --- |
| `/api/assistant/sessions/{session_id}/stream` | Use stream host / no-buffered proxy. |
| `/api/assistant/scripts/{script_id}/tasks/stream` | Use stream host / no-buffered proxy. |
| `/api/director-agent/sessions/{session_id}/stream` | Use stream host / no-buffered proxy. |
| `/api/resource_extract_stream/{task_id}` | Use stream host / no-buffered proxy. |

Normal polling and JSON requests can go through `api.shenlu.top`.

## 3. Sluvo P0 Direct-Call Surface

### 3.1 Auth And Account

| Capability | Method | Path | Sluvo use |
| --- | --- | --- | --- |
| Captcha | GET | `/api/captcha` | Login/register page if Sluvo owns auth UI. |
| Email login | POST | `/api/auth/login` | Store returned token as `shenlu_token`. |
| Register | POST | `/api/auth/register` | Optional Sluvo-owned registration. |
| Send email code | POST | `/api/auth/send-email-code` | Optional register/email verification. |
| Password reset code | POST | `/api/auth/password-reset/send-code` | Optional account recovery. |
| Password reset confirm | POST | `/api/auth/password-reset/confirm` | Optional account recovery. |
| Verify email | POST | `/api/auth/verify-email` | Optional account state. |
| Current user | GET | `/api/user/me` | Required after login. |
| User dashboard | GET | `/api/user/dashboard` | Useful for real recent projects/points. |
| Point logs | GET | `/api/user/point_logs` | Billing view. |
| Storage usage | GET | `/api/user/storage` | Quota warnings. |
| Profile update | PUT | `/api/user/profile` | Account settings. |
| Change password | POST | `/api/user/change_password` | Account settings. |

### 3.2 Project Workspace And Canvas Contracts

These are the best current contracts for Sluvo because they were built around project workspace and canvas projection instead of the older table views.

| Capability | Method | Path | Notes |
| --- | --- | --- | --- |
| Create project | POST | `/api/projects` | Creates backend `Script` and initial projection. |
| Read full workspace | GET | `/api/projects/{project_id}/workspace` | Primary Sluvo read model. |
| Create episode | POST | `/api/projects/{project_id}/episodes` | Adds an `Episode` and refreshes projection. |
| Save episode script | PATCH | `/api/episodes/{episode_id}/script` | Uses stale-update guard with `updatedAt`. |
| Extract episode assets | POST | `/api/episodes/{episode_id}/extract-assets` | Returns `task_id` plus refreshed workspace. |
| Generate storyboard | POST | `/api/episodes/{episode_id}/generate-storyboard` | Submits v3 storyboard split and returns `task_id`. |
| Patch asset | PATCH | `/api/assets/{asset_id}` | Updates asset name/prompt/order and workspace. |
| Delete asset | DELETE | `/api/assets/{asset_id}` | Cleans dependent links/units and returns workspace. |
| Patch storyboard shot | PATCH | `/api/storyboard-shots/{shot_id}` | Updates shot summary/prompts/duration/order. |
| Delete storyboard shot | DELETE | `/api/storyboard-shots/{shot_id}` | Cleans shot links/units and returns workspace. |
| Create asset image unit | POST | `/api/assets/{asset_id}/image-units` | Adds a generation unit for asset reference image. |
| Create shot image unit | POST | `/api/storyboard-shots/{shot_id}/image-units` | Adds image unit and inferred asset references. |
| Create shot video unit | POST | `/api/storyboard-shots/{shot_id}/video-units` | Adds video unit and first-frame input if available. |
| Connect generation input | POST | `/api/generation-units/{target_unit_id}/inputs` | Connects source unit/media to target generation unit. |
| Remove generation input | DELETE | `/api/generation-unit-inputs/{input_id}` | Removes reference edge/input. |
| Run generation unit | POST | `/api/generation-units/{unit_id}/run` | Submits image/video generation and returns `taskId`, `recordId`, `workspace`. |
| Hide canvas node | POST | `/api/canvas/nodes/{node_id}/hide` | Projection visibility. |
| Restore canvas node | POST | `/api/canvas/nodes/{node_id}/restore` | Projection visibility. |

### 3.3 Creative Generation, Uploads, Records

Use these for standalone generation centers, modal generation tools, media pickers, and generated record history.

| Capability | Method | Path | Sluvo use |
| --- | --- | --- | --- |
| Image estimate | POST | `/api/creative/images/estimate` | Show cost before submit. |
| Video estimate | POST | `/api/creative/videos/estimate` | Show cost before submit. |
| Audio estimate | POST | `/api/creative/audio/estimate` | Show cost before submit. |
| Submit image | POST | `/api/creative/images` | Standalone or project-bound image generation. |
| Submit video | POST | `/api/creative/videos` | Standalone or project-bound video generation. |
| Submit audio | POST | `/api/creative/audio/generate` | Dubbing and audio generation. |
| Submit asset image | POST | `/api/creative/assets/generate` | Project asset reference generation. |
| Image catalog | GET | `/api/creative/images/catalog` | Model/options UI. |
| Video catalog | GET | `/api/creative/videos/catalog` | Model/options UI. |
| Audio catalog | GET | `/api/creative/audio/catalog` | Voice/model/options UI. |
| Editing catalog | GET | `/api/creative/editing/catalog` | Editing UI options. |
| Timeline seed | GET | `/api/creative/editing/timeline-seed` | Editing workspace seed. |
| Get editing draft | GET | `/api/creative/editing/draft` | Project editing draft. |
| Save editing draft | PUT | `/api/creative/editing/draft` | Project editing draft. |
| Compose editing output | POST | `/api/creative/editing/compose` | Async editing task. |
| Create Jianying draft | POST | `/api/creative/editing/jianying-draft` | Export draft helper. |
| List records | GET | `/api/creative/records` | Main generated media history. |
| Record detail | GET | `/api/creative/records/{record_id}` | Inspector/history detail. |
| Delete record | DELETE | `/api/creative/records/{record_id}` | User cleanup. |
| Upload image | POST | `/api/creative/uploads/images` | Multipart image reference upload. |
| Upload image base64 | POST | `/api/creative/uploads/images/base64` | Small image upload. |
| Upload video | POST | `/api/creative/uploads/videos` | Multipart video reference upload. |
| Upload video base64 | POST | `/api/creative/uploads/videos/base64` | Small video upload. |
| Upload audio | POST | `/api/creative/uploads/audio` | Audio reference/voice upload. |
| Upload text | POST | `/api/creative/uploads/texts` | Text file upload. |
| Voice assets | GET | `/api/creative/voice-assets` | Voice asset picker. |
| Delete voice asset | DELETE | `/api/creative/voice-assets/{asset_id}` | Voice asset cleanup. |

### 3.4 Task Polling

| Capability | Method | Path | Sluvo use |
| --- | --- | --- | --- |
| List tasks | GET | `/api/tasks` | Optional task drawer by scope filters. |
| Get task | GET | `/api/tasks/{task_id}` | Poll generic task state. |
| Cancel task | POST | `/api/tasks/{task_id}/cancel` | Cancel cooperative tasks. |

### 3.5 Team

| Capability | Method | Path | Sluvo use |
| --- | --- | --- | --- |
| Team overview | GET | `/api/team/overview` | Account/team context. |
| Members | GET | `/api/team/members` | Collaboration UI. |
| Invitations | GET/POST | `/api/team/invitations` | Team invites. |
| Accept invitation | POST | `/api/team/invitations/accept` | Team onboarding. |
| Delete invitation | DELETE | `/api/team/invitations/{invitation_id}` | Team management. |
| Member role | PUT | `/api/team/members/{member_id}/role` | Team management. |
| Member quota | PUT | `/api/team/members/{member_id}/quota` | Team quota UI. |

## 4. OpenClaw API-Key Surface

OpenClaw is stable and well-suited for Sluvo-adjacent CLI/MCP/Agent workflows. It is not the preferred browser contract for the Sluvo app because it uses API-key auth and simplified public payloads.

Base URL:

```text
https://api.shenlu.top/api/openclaw
```

| Method | Path | Use |
| --- | --- | --- |
| GET | `/api/openclaw/capabilities` | Public capability catalog, no API key required. |
| GET | `/api/openclaw/account/quota` | API-key account/team inspiration point balances. |
| GET | `/api/openclaw/projects` | List visible projects. |
| POST | `/api/openclaw/projects` | Create project and first episode. |
| GET | `/api/openclaw/projects/{project_id}` | Project detail with episodes. |
| GET | `/api/openclaw/projects/{project_id}/episodes` | Episode list. |
| POST | `/api/openclaw/projects/{project_id}/episodes` | Create episode. |
| PATCH | `/api/openclaw/projects/{project_id}/settings` | Update public project generation settings. |
| GET | `/api/openclaw/projects/{project_id}/resources` | List character/scene/prop resources. |
| POST | `/api/openclaw/projects/{project_id}/episodes/{episode_id}/assets/extract` | Extract structured assets from script text. |
| POST | `/api/openclaw/projects/{project_id}/assets/import` | Import structured assets. |
| GET | `/api/openclaw/projects/{project_id}/episodes/{episode_id}/workspace/files` | Public file summary. |
| GET | `/api/openclaw/projects/{project_id}/episodes/{episode_id}/panels` | Public storyboard panel summary. |
| POST | `/api/openclaw/projects/{project_id}/episodes/{episode_id}/agent/chat` | Non-SSE OpenClaw Agent interaction. |
| POST | `/api/openclaw/generate/images/estimate` | Image cost estimate. |
| POST | `/api/openclaw/generate/videos/estimate` | Video cost estimate. |
| POST | `/api/openclaw/generate/audio/estimate` | Audio cost estimate. |
| POST | `/api/openclaw/generate/images` | Submit image generation. |
| POST | `/api/openclaw/generate/videos` | Submit video generation. |
| POST | `/api/openclaw/generate/audio` | Submit audio generation. |
| POST | `/api/openclaw/generate/assets` | Submit asset reference image generation. |
| GET | `/api/openclaw/generate/tasks/{task_id}` | Poll OpenClaw generation task. |
| GET | `/api/openclaw/generation-records` | List OpenClaw-visible generated records. |
| GET | `/api/openclaw/generation-records/{record_id}` | Generated record detail. |

Known OpenClaw gaps:
- `/api/openclaw/generate/assets` has no dedicated estimate endpoint; estimate via `/api/openclaw/generate/images/estimate` using equivalent image parameters.
- `Idempotency-Key` is sent by the toolkit, but backend-side deduplication is not yet enforced.
- Submit endpoints are polling-based, not SSE-based.

## 5. Compatibility And Legacy Surfaces

These endpoints exist on production. Sluvo should avoid depending on them unless a current workspace adapter is missing.

### 5.1 Current Shenlu App Project/Storyboard APIs

| Method | Path | Recommendation |
| --- | --- | --- |
| GET/POST | `/api/scripts` | Prefer `/api/projects` for Sluvo project creation/read flow. |
| PUT/DELETE | `/api/scripts/{script_id}` | Prefer project workspace adapters where possible. |
| GET | `/api/scripts/{script_id}/episodes` | Prefer workspace read model. |
| POST | `/api/episodes` | Prefer `/api/projects/{project_id}/episodes`. |
| PUT/DELETE | `/api/episodes/{episode_id}` | Optional compatibility. |
| GET/PUT | `/api/scripts/{script_id}/source` | Prefer `/api/episodes/{episode_id}/script`. |
| POST | `/api/scripts/{script_id}/episode-splits/preview` | Existing app flow, not P0. |
| POST | `/api/scripts/{script_id}/episode-splits/commit` | Existing app flow, not P0. |
| POST | `/api/scripts/{script_id}/episode-splits/ai-preview` | Existing app flow, not P0. |
| GET/POST | `/api/panels` | Prefer storyboard-shot workspace adapters. |
| POST | `/api/panels/reorder` | Optional fallback if Sluvo implements table reorder before workspace adapter exists. |
| PATCH/DELETE | `/api/panels/{panel_id}` | Prefer `/api/storyboard-shots/{shot_id}`. |
| PATCH | `/api/panels/{panel_id}/content` | Existing revision-aware panel edit. |
| POST | `/api/panels/{panel_id}/rebind_assets` | Existing asset-binding action. |
| PATCH | `/api/panels/{panel_id}/entity_bindings` | Existing entity binding action. |
| GET | `/api/panels/{panel_id}/revisions` | Useful if Sluvo exposes shot revision history. |
| POST | `/api/panels/{panel_id}/revisions/{revision_id}/restore` | Useful if Sluvo exposes shot revision restore. |
| GET | `/api/episodes/{episode_id}/segment-workspace` | Existing storyboard table read model. |
| POST | `/api/episodes/{episode_id}/parse_story_segments_v3` | Existing v3 storyboard split submit. Prefer `/api/episodes/{episode_id}/generate-storyboard` for Sluvo P0. |
| GET | `/api/parse_story_segments_v3/{task_id}` | Existing v3 storyboard split polling. |
| POST | `/api/parse_story_segments_v3/{task_id}/cancel` | Existing v3 storyboard split cancel. |
| POST | `/api/episodes/{episode_id}/parse_story_segments_v3/commit` | Existing explicit v3 commit path. Sluvo P0 should use workspace/Agent flow unless it needs draft review. |
| PATCH | `/api/segments/{segment_id}` | Existing segment edit. |
| PATCH | `/api/segments/{segment_id}/cells/{cell_id}` | Existing nine-grid cell edit. |
| POST | `/api/episodes/{episode_id}/rebind_panel_assets` | Existing batch rebind. |
| POST | `/api/episodes/{episode_id}/upload_image` | Existing extra image upload. |
| GET | `/api/episodes/{episode_id}/extra_images` | Existing extra images. |
| DELETE | `/api/episodes/{episode_id}/extra_images/{image_id}` | Existing extra image cleanup. |

### 5.2 Current Resource APIs

| Method | Path | Recommendation |
| --- | --- | --- |
| POST | `/api/resources` | Existing resource create; prefer project workspace asset adapter for Sluvo P0. |
| GET | `/api/scripts/{script_id}/resources` | Existing asset list. |
| GET | `/api/scripts/{script_id}/shared_resources` | Existing asset list alias. |
| POST | `/api/scripts/{script_id}/resources/upload` | Existing asset upload. |
| PUT/DELETE | `/api/resources/{resource_id}` | Existing asset update/delete. |
| GET | `/api/resources/{resource_id}/download` | Useful if Sluvo needs authenticated download proxy. |
| PUT | `/api/resources/{resource_id}/upload` | Existing asset file replace. |
| GET/POST | `/api/resources/{resource_id}/versions` | Useful for asset version inspector. |
| PUT/DELETE | `/api/resources/versions/{version_id}` | Useful for asset version management. |
| POST | `/api/resources/{resource_id}/generate-image` | Existing single asset image generation; Sluvo can prefer generation units or creative asset generate. |
| GET | `/api/resource_generate_status/{task_id}` | Legacy asset image task poll. |
| POST | `/api/scripts/{script_id}/extract-assets` | Existing script-level extraction. Prefer episode/project workspace adapter. |
| GET | `/api/resource_extract_status/{task_id}` | Existing extraction polling. |
| GET | `/api/resource_extract_stream/{task_id}` | Stream endpoint; use stream host if needed. |

### 5.3 Legacy Generation APIs

Prefer `/api/creative/*` and `/api/generation-units/{unit_id}/run`.

| Method | Path | Recommendation |
| --- | --- | --- |
| POST | `/api/generate/image-estimate` | Legacy estimate. |
| POST | `/api/generate/video-estimate` | Legacy estimate. |
| POST | `/api/generate` | Legacy panel image generation. |
| POST | `/api/generate_img2img` | Legacy img2img. |
| POST | `/api/generate_video` | Legacy video. |
| GET | `/api/video_status/{task_id}` | Legacy video poll. |
| POST | `/api/generate_nano` | Legacy Nano generation. |
| GET | `/api/nano_status/{task_id}` | Legacy Nano poll. |
| POST | `/api/generate_standalone_image` | Legacy standalone image. |
| GET | `/api/standalone_status/{task_id}` | Legacy standalone poll. |
| POST | `/api/episodes/{episode_id}/generate_image_v2` | Existing storyboard image generation; Sluvo can use indirectly through generation unit run. |
| GET | `/api/status/{task_id}` | Legacy status endpoint. |

### 5.4 Legacy Canvas APIs

These expose the older script-level canvas CRUD. Sluvo may use them only if it intentionally reuses legacy `CanvasWorkspace/CanvasNode/CanvasEdge` CRUD directly. The P0 product path should prefer `/api/projects/{id}/workspace` plus new thin workspace adapters.

| Method | Path |
| --- | --- |
| GET | `/api/canvas/scripts/{script_id}/workspace` |
| POST | `/api/canvas/scripts/{script_id}/bootstrap` |
| POST | `/api/canvas/workspaces/{workspace_id}/reconcile` |
| PATCH | `/api/canvas/workspaces/{workspace_id}` |
| POST | `/api/canvas/workspaces/{workspace_id}/nodes` |
| PATCH/DELETE | `/api/canvas/nodes/{node_id}` |
| POST | `/api/canvas/nodes/{node_id}/archive` |
| POST | `/api/canvas/workspaces/{workspace_id}/edges` |
| PATCH/DELETE | `/api/canvas/edges/{edge_id}` |
| POST | `/api/canvas/nodes/{node_id}/refresh-from-source` |
| POST | `/api/canvas/nodes/{node_id}/push-to-source` |
| POST | `/api/canvas/nodes/{node_id}/actions/{action_name}` |

### 5.5 Assistant And Workflow APIs

Sluvo can reuse these when adding an Agent side panel. Stream endpoints need the stream host/no-buffering path.

| Method | Path | Recommendation |
| --- | --- | --- |
| GET/POST | `/api/assistant/scripts/{script_id}/sessions` | Agent session list/create. |
| GET | `/api/assistant/scripts/{script_id}/skills` | Agent skills. |
| GET | `/api/assistant/scripts/{script_id}/tasks` | Agent task summary. |
| POST | `/api/assistant/scripts/{script_id}/tasks/{task_id}/retry` | Retry task. |
| GET/PATCH/DELETE | `/api/assistant/sessions/{session_id}` | Session detail/update/delete. |
| GET | `/api/assistant/sessions/{session_id}/snapshot` | Snapshot. |
| POST | `/api/assistant/sessions/{session_id}/messages` | Send message. |
| POST | `/api/assistant/sessions/{session_id}/agent-actions` | Execute structured action. |
| POST | `/api/assistant/sessions/{session_id}/interrupt` | Interrupt run. |
| POST | `/api/assistant/sessions/{session_id}/questions/{question_id}/answer` | Answer pending question. |
| POST | `/api/assistant/sessions/{session_id}/bridge/link` | Existing bridge link. |
| POST | `/api/assistant/sessions/{session_id}/bridge/unlink` | Existing bridge unlink. |
| GET | `/api/assistant/sessions/{session_id}/bridge/state` | Existing bridge state. |
| POST | `/api/assistant/sessions/{session_id}/bridge/imports` | Existing bridge imports. |
| GET | `/api/assistant/sessions/{session_id}/stream` | SSE stream; use stream host. |
| GET | `/api/assistant/scripts/{script_id}/tasks/stream` | SSE stream; use stream host. |
| GET | `/api/agent-workflow/scripts/{script_id}` | Project workflow state. |
| POST | `/api/agent-workflow/scripts/{script_id}/advance` | Advance project workflow. |
| GET | `/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}` | Episode workflow state. |
| POST | `/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}/advance` | Advance episode workflow. |
| POST | `/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}/redo` | Redo stage. |
| POST | `/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}/adjust` | Adjust stage. |
| POST | `/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}/optimize` | Optimize stage. |
| POST | `/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}/confirm` | Confirm stage. |

### 5.6 Director-Agent APIs

Older/parallel director-agent surface. Prefer `/api/assistant/*` for new Sluvo work unless a specific director-agent capability is needed.

| Method | Path |
| --- | --- |
| POST | `/api/director-agent/sessions` |
| GET/DELETE | `/api/director-agent/sessions/{session_id}` |
| POST | `/api/director-agent/sessions/{session_id}/messages` |
| POST | `/api/director-agent/messages/{message_id}/confirm` |
| GET | `/api/director-agent/sessions/{session_id}/context` |
| GET | `/api/director-agent/script-sessions/{script_id}` |
| GET | `/api/director-agent/scripts/{script_id}/sessions` |
| GET | `/api/director-agent/sessions/{session_id}/stream` |

### 5.7 External-Agent APIs

These are mainly for the existing OpenClaw/third-party bridge management inside the Shenlu app. Sluvo browser MVP should not depend on them unless it exposes API-key/agent settings.

| Method | Path |
| --- | --- |
| GET | `/api/external-agent/providers` |
| GET/PUT | `/api/external-agent/credentials/{provider}` |
| PATCH | `/api/external-agent/credentials/{provider}/permissions` |
| POST | `/api/external-agent/credentials/{provider}/generate` |
| POST | `/api/external-agent/credentials/{provider}/refresh` |
| GET/POST | `/api/scripts/{script_id}/external-agent/sessions` |
| POST | `/api/external-agent/sessions/{session_id}/activate` |
| PATCH | `/api/external-agent/sessions/{session_id}/settings` |
| POST | `/api/external-agent/sessions/{session_id}/chat` |
| GET | `/api/external-agent/sessions/{session_id}` |
| GET | `/api/external-agent/sessions/{session_id}/files` |
| POST | `/api/external-agent/sessions/{session_id}/import/script` |
| POST | `/api/external-agent/sessions/{session_id}/import/characters` |
| POST | `/api/external-agent/sessions/{session_id}/import/panels` |

### 5.8 Experimental Unified Gen APIs

Treat as internal/experimental until productized for Sluvo.

| Method | Path |
| --- | --- |
| POST | `/api/gen/submit` |
| GET | `/api/gen/tasks` |
| GET | `/api/gen/tasks/{task_id}` |

## 6. Do Not Call From Sluvo Browser

### 6.1 Admin APIs

Admin console only.

| Method | Path |
| --- | --- |
| POST | `/api/admin/login` |
| GET | `/api/admin/dashboard` |
| GET | `/api/admin/users` |
| POST | `/api/admin/users/{user_id}/grant_points` |
| POST | `/api/admin/users/{user_id}/toggle_active` |
| POST | `/api/admin/users/{user_id}/set_vip` |
| GET/POST | `/api/admin/membership/plans` |
| PUT | `/api/admin/membership/plans/{plan_id}` |
| POST | `/api/admin/users/{user_id}/membership` |
| POST | `/api/admin/teams/{team_id}/membership` |
| PUT | `/api/admin/users/{user_id}/membership-override` |
| GET | `/api/admin/membership/runtime-overview` |
| GET | `/api/admin/storage/users/{user_id}` |
| POST | `/api/admin/storage/users/{user_id}/recalculate` |
| GET | `/api/admin/point_logs` |
| GET | `/api/admin/orders` |
| PUT | `/api/admin/channels/{channel_id}` |

### 6.2 Provider Callback APIs

Provider-to-backend only.

| Method | Path |
| --- | --- |
| POST | `/api/provider-callbacks/runninghub/video` |
| POST | `/api/provider-callbacks/runninghub/image` |

### 6.3 WeChat Integration APIs

Only use if Sluvo explicitly supports WeChat login. Webhook routes are provider callbacks.

| Method | Path | Recommendation |
| --- | --- | --- |
| GET | `/api/wechat/login_qrcode` | Optional future login surface. |
| GET | `/api/wechat/check_login` | Optional future login surface. |
| GET/POST | `/api/wechat/webhook` | Do not call from browser. |

### 6.4 Channel API

| Method | Path | Recommendation |
| --- | --- | --- |
| GET | `/api/channels` | Existing channel settings. Use only if Sluvo exposes model/channel diagnostics. |

## 7. Request Shape Notes For P0 APIs

### Create Project

```http
POST /api/projects
Authorization: Bearer <shenlu_token>
Content-Type: application/json
```

```json
{
  "title": "新项目",
  "description": "",
  "aspect_ratio": "16:9",
  "style_preset": "默认写实",
  "default_storyboard_mode": "comic",
  "workflow_settings_json": "{}"
}
```

Response is the full project workspace.

### Read Workspace

```http
GET /api/projects/{project_id}/workspace
Authorization: Bearer <shenlu_token>
```

Use this as the primary source for:
- project identity
- episodes
- assets
- storyboard shots
- generation units
- media
- task summaries
- canvas projections

### Save Episode Script

```http
PATCH /api/episodes/{episode_id}/script
Authorization: Bearer <shenlu_token>
Content-Type: application/json
```

```json
{
  "rawScript": "当前集剧本文本",
  "updatedAt": "2026-04-30T12:00:00"
}
```

If `updatedAt` is stale, backend returns `409`.

### Run Generation Unit

```http
POST /api/generation-units/{unit_id}/run
Authorization: Bearer <shenlu_token>
Content-Type: application/json
```

```json
{
  "prompt": "可选覆盖提示词",
  "modelId": "nano-banana-pro",
  "params": {
    "resolution": "2k",
    "aspectRatio": "16:9"
  }
}
```

Response:

```json
{
  "taskId": "public task id",
  "recordId": "encoded record id",
  "workspace": {}
}
```

Then poll:

```http
GET /api/tasks/{task_id}
```

or refresh:

```http
GET /api/projects/{project_id}/workspace
```

## 8. Error Shapes

Normal app APIs usually return:

```json
{
  "detail": "message or structured detail"
}
```

Productized `/api/creative/*` and `/api/openclaw/*` APIs normalize errors to:

```json
{
  "success": false,
  "error": "invalid_request",
  "message": "请求参数不合法，请检查后重试",
  "retryable": false
}
```

Sluvo's API client should support both shapes.

## 9. Recommended Implementation Order

1. Keep Sluvo API client using `VITE_API_BASE=https://api.shenlu.top` in production and `/api` through Vite proxy locally.
2. Replace homepage mock projects with `GET /api/user/dashboard` or `GET /api/projects/{project_id}/workspace` once project selection is real.
3. Wire project creation through `POST /api/projects`.
4. Use `GET /api/projects/{project_id}/workspace` as the first real canvas hydration endpoint.
5. Add script save, asset extraction, storyboard generation, generation-unit creation and run using the P0 project workspace endpoints.
6. Use `/api/creative/uploads/*`, `/api/creative/*/estimate`, `/api/creative/*`, `/api/creative/records`, and `/api/tasks/*` for generation modals and media drawers.
7. Only add `/api/assistant/*` after the base canvas/project workflow is stable.

## 10. Verification Checklist

- `curl https://api.shenlu.top/openapi.json` returns routes and includes `https://sluvo.shenlu.top` in backend CORS source.
- Sluvo production build sets `VITE_API_BASE=https://api.shenlu.top`.
- Authenticated Sluvo calls include `Authorization: Bearer <shenlu_token>`.
- `POST /api/auth/login` stores `shenlu_token`.
- `GET /api/user/me` succeeds after login.
- `POST /api/projects` returns a workspace.
- `GET /api/projects/{project_id}/workspace` renders project/canvas state.
- Generation submissions show estimate before submit and poll `/api/tasks/{task_id}` or refresh the workspace.
- SSE usage, if added, is tested through a no-buffered stream host.
