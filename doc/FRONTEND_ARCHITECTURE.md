# Sluvo Frontend Architecture

Version: 0.1
Date: 2026-04-24

## 1. Recommended Stack

Default stack:

- Vue 3
- Vite
- Pinia
- Vue Router
- Fetch-based API client
- Vue Flow for graph canvas MVP

Do not add a backend service inside this repository for MVP.

## 2. Proposed Directory Structure

After scaffolding, use this shape:

```text
apps/sluvo-web/
  src/
    api/
      client.js
      authApi.js
      sluvoApi.js
      creativeApi.js
    assets/
    canvas/
      components/
      composables/
      edges/
      nodes/
      ports/
      utils/
    components/
      common/
      layout/
      task/
    router/
      index.js
    stores/
      authStore.js
      projectStore.js
      canvasStore.js
      taskStore.js
    styles/
      base.css
      theme.css
    views/
      HomeView.vue
      LoginView.vue
      CommunityCanvasView.vue
      ProjectListView.vue
      TrashView.vue
      CanvasWorkspaceView.vue
    App.vue
    main.js
```

Keep feature-specific canvas code under `src/canvas/`.

Keep shared app shell and reusable UI under `src/components/`.

## 3. API Layer

All network calls should go through `src/api/client.js`.

Rules:
- API paths are relative, starting with `/api`.
- The API client injects `Authorization: Bearer <shenlu_token>`.
- Components should not call `fetch` directly unless there is a clear reason.
- Provider APIs should never be called directly from the browser.

2026-05-02 backend contract update:
- Standalone Sluvo project/canvas features should call `/api/sluvo/*`.
- Do not use `/api/projects/*` as the Sluvo project root for new standalone canvas work.
- Frontend project truth should hydrate from `GET /api/sluvo/projects/{projectId}/canvas`, then save canvas state with `POST /api/sluvo/canvases/{canvasId}/batch`.
- Canvas, node, and edge writes should pass `expectedRevision` when available and handle `409` by refreshing the canvas.

## 4. Stores

Suggested Pinia stores:

| Store | Responsibility |
| --- | --- |
| `authStore` | token, current user, login/logout helpers |
| `projectStore` | project list, active project, workspace loading |
| `canvasStore` | selected nodes, viewport, local canvas UI state |
| `taskStore` | active tasks, polling or refresh hints |

Project truth should come from Sluvo backend responses, not only local canvas state.

## 5. Routes

Current MVP routes:

| Route | View |
| --- | --- |
| `/login` | `LoginView.vue` |
| `/` | `HomeView.vue` |
| `/projects` | `ProjectListView.vue` |
| `/trash` | `TrashView.vue` |
| `/projects/:projectId/canvas` | `CanvasWorkspaceView.vue` |
| `/community/canvases/:publicationId` | `CommunityCanvasView.vue` |

`HomeView.vue` is a dual-state entry:
- Without `localStorage.shenlu_token`, it shows the public black/gold Sluvo brand entry and sends login to `/login`.
- With `localStorage.shenlu_token`, it shows the OiiOii-style creation workbench backed by real `/api/sluvo/projects` data.

Home project cards route to `/projects/{projectId}/canvas`. The central prompt composer creates a real Sluvo project, writes the prompt as the first `note` node on the main canvas, then routes to the canvas page.

The logged-in home keeps projects in a single horizontal recent-project row with a `查看全部` route to `/projects`. The left rail folder icon opens `/projects`, and the trash icon opens `/trash` as the deleted-project holding area.

Community canvas cards are visible on the public and logged-in home. Guests can browse cards but must log in before opening detail or forking. Logged-in users can open the read-only community detail view and fork a publication into a new editable Sluvo project.

## 6. Canvas State Rule

Canvas state has two categories.

Backend persisted through `/api/sluvo/*`:
- node position
- node size
- hidden / restored projection
- node/edge data, ports, style, and Agent config
- canvas snapshot JSON
- project members and Agent action audit records

Current persistence behavior:
- Canvas pages load from `GET /api/sluvo/projects/{projectId}/canvas`.
- Local direct canvas nodes and edges autosave with a 1.2s debounce through `POST /api/sluvo/canvases/{canvasId}/batch`.
- Unsaved nodes carry a local `clientId`; after save, the frontend refreshes to server encoded IDs.
- New edges that reference just-created local nodes are saved after the node ID refresh.
- Revision conflicts return `409`; the frontend shows a conflict state and reloads the canvas.
- Upload nodes create an immediate local `blob:` preview, upload in the background, then replace the preview with OSS-backed `fileUrl` and asset metadata. Local preview URLs must be stripped before batch persistence.
- Upload size limits are enforced in the browser at `20MB`; files up to `5MB` use base64 JSON upload, larger files use multipart upload for progress.
- Upload responses may include quota and deduplication metadata; the node stores permanent `assetId`, `storageObjectId`, and `storageObjectKey` values, never temporary browser URLs.

Frontend local:
- selected node ids
- hover state
- open drawers
- temporary drag state
- unsaved viewport during interaction

Do not store business truth only in local canvas state.

## 7. Component Rules

Nodes should be small and scannable.

Use inspector panels for detailed editing.

Avoid:
- Giant components that combine API calls, layout, canvas interaction, and form logic.
- Direct backend calls inside deeply nested visual components.
- Duplicating the same endpoint call in many places.

Prefer:
- API wrapper
- store action
- composable
- focused visual component

## 8. Environment Variables

Use `.env.example` as the source for expected environment variables.

Initial variables:

```text
VITE_APP_NAME=Sluvo
VITE_DEV_SERVER_PORT=5174
VITE_API_BASE=/api
```

Even with `VITE_API_BASE`, prefer `/api` as the default and use Vite / gateway proxying.

## 9. Build Verification

Once scaffolded, every meaningful frontend change should verify at least:

```powershell
npm run build
```

If tests are added later, also run the relevant test command.
