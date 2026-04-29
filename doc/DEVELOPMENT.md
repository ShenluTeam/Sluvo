# Sluvo Development Guide

Version: 0.1
Date: 2026-04-24

## 1. Local Repositories

Sluvo is developed as a separate frontend repository.

```text
E:\ljtpc\work\Sluvo
  Sluvo frontend and docs

E:\ljtpc\work\AIdrama
  Existing Shenlu platform

E:\ljtpc\work\AIdrama\backend
  Existing FastAPI backend reused by Sluvo
```

## 2. Required Reading

Before code changes, read:

1. `AGENTS.md`
2. `doc/PRD.md`
3. `doc/API_DEVELOPMENT.md`
4. `doc/FRONTEND_ARCHITECTURE.md`
5. `doc/UI_REQUIREMENTS.md`
6. `doc/BACKEND_CONTRACTS.md`

## 3. Setup

After the frontend app is scaffolded:

```powershell
cd E:\ljtpc\work\Sluvo
npm install
Copy-Item .env.example .env.local
npm run dev
```

The dev server should use port `5174` unless there is a conflict.

Current frontend location:

```text
E:\ljtpc\work\Sluvo\apps\sluvo-web
```

The root `package.json` uses npm workspaces, so `npm install` and `npm run dev` can be run from the repository root.

The Vite app reads env files from the repository root, so root-level `.env.local` and `.env.production` apply to `apps/sluvo-web`.

## 4. Backend Startup

Run the existing backend separately:

```powershell
cd E:\ljtpc\work\AIdrama\backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Sluvo should call API paths through `apiFetch('/api/...')`.

For production, set:

```env
VITE_API_BASE=https://api.shenlu.top
```

For local proxy development, set `VITE_API_BASE=` and Vite forwards `/api` requests to `http://127.0.0.1:8000`.

## 5. API Rule

Use relative API paths in frontend code:

```js
apiFetch('/api/projects/{projectId}/workspace')
```

Do not hard-code backend hosts in components, stores, or composables. Use `VITE_API_BASE` for environment-specific API hosts.

## 6. Auth Rule

Use existing Shenlu auth:

```text
localStorage.shenlu_token
Authorization: Bearer <shenlu_token>
```

Do not create `sluvo_token` for MVP.

## 7. Suggested First Scaffold

Recommended stack:

- Vue 3
- Vite
- Pinia
- Vue Router
- Fetch-based API client
- Vue Flow for the first graph-oriented canvas MVP

Recommended app structure is documented in `doc/FRONTEND_ARCHITECTURE.md`.

## 8. Verification Checklist

After scaffolding or changing API code, verify:

- Sluvo dev server starts.
- Existing Shenlu backend starts.
- `/api/projects/{id}/workspace` reaches the backend through the local proxy, or `https://api.shenlu.top/api/projects/{id}/workspace` in production.
- Authenticated requests include `Authorization`.
- Clearing `shenlu_token` makes protected requests fail.
- No browser code calls provider APIs directly.

## 9. Documentation Updates

Update docs when:

- API proxy or auth changes: `doc/API_DEVELOPMENT.md`
- Frontend structure changes: `doc/FRONTEND_ARCHITECTURE.md`
- UI patterns or product wording changes: `doc/UI_REQUIREMENTS.md`
- Backend contracts change: `doc/BACKEND_CONTRACTS.md`
- Any non-trivial implementation happens: `doc/CHANGELOG_DEV.md`
