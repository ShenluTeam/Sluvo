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
      projectWorkspaceApi.js
      generationApi.js
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
      ProjectListView.vue
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

## 4. Stores

Suggested Pinia stores:

| Store | Responsibility |
| --- | --- |
| `authStore` | token, current user, login/logout helpers |
| `projectStore` | project list, active project, workspace loading |
| `canvasStore` | selected nodes, viewport, local canvas UI state |
| `taskStore` | active tasks, polling or refresh hints |

Project truth should come from backend workspace responses, not only local canvas state.

## 5. Routes

Current MVP routes:

| Route | View |
| --- | --- |
| `/login` | `LoginView.vue` |
| `/` | `HomeView.vue` |
| `/projects` | `HomeView.vue` |
| `/projects/:projectId/canvas` | `CanvasWorkspaceView.vue` |

`HomeView.vue` is a dual-state entry:
- Without `localStorage.shenlu_token`, it shows the public black/gold Sluvo brand entry and sends login to `/login`.
- With `localStorage.shenlu_token`, it shows the OiiOii-style creation workbench using mock recent projects from `src/mock/projects.js`.

Home project cards and "start canvas" actions should route to `/projects/{projectId}/canvas`.

## 6. Canvas State Rule

Canvas state has two categories.

Backend persisted:
- node position
- node size
- hidden / restored projection
- domain-backed node and edge relationships

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
