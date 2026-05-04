# Sluvo API Development Guide

Version: 0.1
Date: 2026-04-24

Related detailed inventory:
- `doc/API_SHENLU_TOP.md` lists the audited `api.shenlu.top` route surface, Sluvo direct-call recommendations, OpenClaw API-key boundaries, and endpoints to avoid for the MVP.

## 1. Core Rule

Sluvo frontend code should call backend APIs through the shared API client with backend paths:

```js
apiFetch('/api/projects/{projectId}/workspace')
```

Do not write backend hosts directly in components, stores, or composables:

```js
fetch('http://127.0.0.1:8000/api/projects/{projectId}/workspace')
```

The environment decides the API host:
- Local development may use Vite proxy by setting `VITE_API_BASE=` and calling `/api/...`.
- Production uses `VITE_API_BASE=https://api.shenlu.top`, so `apiFetch('/api/projects/...')` reaches `https://api.shenlu.top/api/projects/...`.

This keeps local, staging, and production builds consistent.

## 2. Local Development Topology

Recommended local paths:

```text
E:\ljtpc\work\Sluvo
  Sluvo frontend repository

E:\ljtpc\work\AIdrama\backend
  Existing Shenlu FastAPI backend
```

Recommended ports:
- Sluvo Vite dev server: `5174`
- Existing Shenlu backend: `8000`

Run backend:

```powershell
cd E:\ljtpc\work\AIdrama\backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Run Sluvo frontend after scaffolding:

```powershell
cd E:\ljtpc\work\Sluvo
npm install
npm run dev
```

## 3. Vite Proxy

The app loads Vite env files from the repository root and supports a Vite proxy for local development. Use the proxy when `VITE_API_BASE` is empty:

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
})
```

With this proxy and `VITE_API_BASE=`, browser requests to:

```text
http://127.0.0.1:5174/api/projects/{projectId}/workspace
```

are forwarded by Vite to:

```text
http://127.0.0.1:8000/api/projects/{projectId}/workspace
```

## 4. API Client Pattern

Use one shared API client wrapper instead of scattered raw `fetch` calls.

Recommended shape:

```js
const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

function buildApiUrl(path) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE}${normalizedPath}`
}

export async function apiFetch(path, options = {}) {
  const token = localStorage.getItem('shenlu_token') || ''
  const headers = {
    ...(options.headers || {})
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json'
  }

  const response = await fetch(buildApiUrl(path), {
    ...options,
    headers
  })

  const contentType = response.headers.get('content-type') || ''
  const data = contentType.includes('application/json')
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    const message = typeof data === 'object' && data?.detail
      ? data.detail
      : `API request failed: ${response.status}`
    throw new Error(message)
  }

  return data
}
```

Example:

```js
export function fetchProjectWorkspace(projectId) {
  return apiFetch(`/api/projects/${projectId}/workspace`)
}
```

## 5. Auth Integration

Sluvo reuses the existing Shenlu auth chain.

Required token storage:

```text
localStorage.shenlu_token
```

Required request header:

```http
Authorization: Bearer <shenlu_token>
```

Do not introduce a second token key such as `sluvo_token` for MVP.

If Sluvo owns a login page later, it should still call the existing Shenlu auth endpoints and store the returned token as `shenlu_token`.

Current Sluvo login wrapper:

```js
loginWithPassword({ email, password })
```

It calls `POST /api/auth/login` and stores the returned `token` as `localStorage.shenlu_token`.

## 6. Backend APIs To Reuse First

The existing backend should be the first source of truth.

2026-05-02 update: standalone Sluvo project/canvas work should use the dedicated `/api/sluvo/*` API surface. Older `/api/projects/*` workspace APIs are compatibility references for Shenlu project workspace experiments, not the primary standalone Sluvo contract.

Standalone Sluvo:

| Capability | API |
| --- | --- |
| List/create Sluvo projects | `GET/POST /api/sluvo/projects` |
| List deleted Sluvo projects | `GET /api/sluvo/projects?includeDeleted=true` |
| Read/update/delete Sluvo project | `GET/PATCH/DELETE /api/sluvo/projects/{project_id}` |
| Restore/permanently delete Sluvo project | `POST /api/sluvo/projects/{project_id}/restore`, `DELETE /api/sluvo/projects/{project_id}/permanent` |
| Read main canvas | `GET /api/sluvo/projects/{project_id}/canvas` |
| Patch canvas snapshot/viewport | `PATCH /api/sluvo/canvases/{canvas_id}` |
| Create/update canvas nodes | `POST /api/sluvo/canvases/{canvas_id}/nodes`, `PATCH /api/sluvo/canvases/{canvas_id}/nodes/{node_id}` |
| Create/update canvas edges | `POST /api/sluvo/canvases/{canvas_id}/edges`, `PATCH /api/sluvo/canvases/{canvas_id}/edges/{edge_id}` |
| Batch save canvas | `POST /api/sluvo/canvases/{canvas_id}/batch` |
| Upload persistent canvas asset | `POST /api/sluvo/canvases/{canvas_id}/assets/upload` |
| Upload persistent canvas asset as base64 | `POST /api/sluvo/canvases/{canvas_id}/assets/upload/base64` |
| Manage project members | `/api/sluvo/projects/{project_id}/members` |
| Canvas Agent persistence | `/api/sluvo/projects/{project_id}/agent/sessions`, `/api/sluvo/agent/*` |
| Community canvas list/detail | `GET /api/sluvo/community/canvases`, `GET /api/sluvo/community/canvases/{publication_id}` |
| Community publish/fork/unpublish | `POST /api/sluvo/projects/{project_id}/community/publish`, `POST /api/sluvo/community/canvases/{publication_id}/fork`, `POST /api/sluvo/community/canvases/{publication_id}/unpublish` |

Frontend implementation note:
- `src/api/sluvoApi.js` wraps the standalone project/canvas endpoints.
- `fetchSluvoProjects({ includeDeleted: true })` is used by the recycle bin to list soft-deleted projects. The normal project list keeps deleted projects hidden. Recycle-bin actions call the restore endpoint or the permanent-delete endpoint.
- The logged-in home creates projects through `POST /api/sluvo/projects`; when the user enters a prompt, Sluvo writes it as an initial `note` node through `POST /api/sluvo/canvases/{canvas_id}/batch`.
- Canvas pages hydrate from `GET /api/sluvo/projects/{project_id}/canvas` and autosave node, edge, viewport, and snapshot state through the batch endpoint.
- `409` responses are treated as revision conflicts; the canvas refreshes instead of overwriting newer server state.
- Canvas uploads use instant local preview, then persist to OSS through Sluvo upload endpoints. Files up to `5MB` use base64 JSON; files over `5MB` and up to `20MB` use multipart upload with progress. Returned OSS URLs are written back to the upload node and `sluvo_canvas_asset`.
- Sluvo upload objects are stored under the existing per-user OSS namespace, then grouped by Sluvo project and canvas: `users/{namespace}/sluvo/projects/{project}/canvases/{canvas}/{mediaType}/...`. Sluvo upload quota uses the existing storage accounting system and enforces the current `5GB` free-user quota for this upload path.
- Community canvas list is public card metadata; detail and fork require login. Forked projects reuse original OSS media URLs for v1.

For the complete `api.shenlu.top` inventory and Sluvo suitability notes, read `doc/API_SHENLU_TOP.md`.

Legacy project workspace:

| Capability | API |
| --- | --- |
| Read full project workspace | `GET /api/projects/{project_id}/workspace` |
| Create project | `POST /api/projects` |
| Create episode | `POST /api/projects/{project_id}/episodes` |
| Save episode script | `PATCH /api/episodes/{episode_id}/script` |
| Patch asset | `PATCH /api/assets/{asset_id}` |
| Patch storyboard shot | `PATCH /api/storyboard-shots/{shot_id}` |
| Create asset image unit | `POST /api/assets/{asset_id}/image-units` |
| Create shot image unit | `POST /api/storyboard-shots/{shot_id}/image-units` |
| Create shot video unit | `POST /api/storyboard-shots/{shot_id}/video-units` |
| Connect generation input | `POST /api/generation-units/{target_unit_id}/inputs` |
| Run generation unit | `POST /api/generation-units/{unit_id}/run` |
| Hide canvas projection node | `POST /api/canvas/nodes/{node_id}/hide` |
| Restore canvas projection node | `POST /api/canvas/nodes/{node_id}/restore` |

Existing backend path:

```text
E:\ljtpc\work\AIdrama\backend
```

If an endpoint contract is unclear, inspect:
- `backend/routers/project_workspace.py`
- `backend/services/project_workspace_service.py`
- `backend/services/canvas_projection_service.py`
- `backend/routers/generate.py`
- `backend/routers/resource.py`

## 7. Production Routing

Recommended production domain:

```text
sluvo.shenlu.top
```

Production should serve the Sluvo static frontend and proxy `/api` to the existing Shenlu backend.

Production API traffic should go to:

```text
https://api.shenlu.top
```

Build Sluvo with:

```env
VITE_API_BASE=https://api.shenlu.top
```

Because the API is cross-origin from `sluvo.shenlu.top`, the existing Shenlu backend must allow this origin in CORS:

```python
"https://sluvo.shenlu.top",
```

Example Nginx shape:

```nginx
server {
  server_name sluvo.shenlu.top;

  location / {
    root /var/www/sluvo/dist;
    try_files $uri $uri/ /index.html;
  }
}
```

The `api.shenlu.top` Nginx site should continue proxying backend traffic to the existing FastAPI service.

## 8. CORS Guidance

Sluvo production intentionally uses cross-origin API requests:

```text
Browser -> sluvo.shenlu.top static frontend
Browser -> api.shenlu.top/api -> backend
```

This requires `https://sluvo.shenlu.top` in backend CORS. Bearer-token auth still uses `Authorization: Bearer <shenlu_token>`.

## 9. Common Mistakes

Avoid these:
- Hard-coding backend host URLs in components.
- Creating `sluvo_token` instead of using `shenlu_token`.
- Calling provider APIs directly from the browser.
- Persisting project truth only in canvas node JSON.
- Creating duplicate Sluvo backend routes for behavior already owned by the Shenlu backend.
- Forgetting to pass `Authorization` on project workspace and generation requests.

## 10. Quick Verification Checklist

After the frontend app is scaffolded, verify:

- `npm run dev` starts Sluvo on port `5174`.
- The old backend is running on port `8000`.
- A browser request to `/api/projects/{id}/workspace` reaches the backend through the Vite proxy.
- Authenticated requests include `Authorization: Bearer <shenlu_token>`.
- Logging out or clearing `shenlu_token` causes protected requests to fail as expected.
- Production build sets `VITE_API_BASE=https://api.shenlu.top`.
