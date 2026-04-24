# Sluvo API Development Guide

Version: 0.1
Date: 2026-04-24

## 1. Core Rule

Sluvo frontend code should always call backend APIs with relative paths:

```js
fetch('/api/projects/{projectId}/workspace')
```

Do not write backend hosts directly in UI code:

```js
// Avoid this in app code.
fetch('http://127.0.0.1:8000/api/projects/{projectId}/workspace')
```

The environment decides where `/api` goes:
- Local development: Vite proxy forwards `/api` to `http://127.0.0.1:8000`.
- Production: Nginx or the platform gateway forwards `/api` to the existing Shenlu backend.

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

When the frontend app is scaffolded, configure `vite.config.js` or `vite.config.ts` like this:

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

With this proxy, browser requests to:

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
const API_BASE = ''

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

  const response = await fetch(`${API_BASE}${path}`, {
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

## 6. Backend APIs To Reuse First

The existing backend should be the first source of truth.

Project workspace:

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

Example Nginx shape:

```nginx
server {
  server_name sluvo.shenlu.top;

  location / {
    root /var/www/sluvo/dist;
    try_files $uri $uri/ /index.html;
  }

  location /api/ {
    proxy_pass http://127.0.0.1:8000/api/;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

If the backend is deployed behind another internal domain or service name, only the proxy target should change. Sluvo frontend code should still call `/api/...`.

## 8. CORS Guidance

Prefer same-origin proxying over browser-side cross-origin requests.

Recommended:

```text
Browser -> sluvo.shenlu.top/api -> backend
```

Avoid:

```text
Browser -> api.shenlu.top/api
```

Same-origin proxying avoids most CORS, cookie, preflight, and token forwarding surprises.

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
- Production config keeps frontend calls as `/api/...` and moves host routing to Nginx or gateway config.
