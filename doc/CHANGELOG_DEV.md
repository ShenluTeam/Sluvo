# Sluvo Development Changelog

## 2026-04-28

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `apps/sluvo-web/src/views/LoginView.vue`
- `apps/sluvo-web/src/router/index.js`
- `apps/sluvo-web/src/styles/base.css`
- `apps/sluvo-web/src/styles/theme.css`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added a dual-state Sluvo homepage at `/` and `/projects`.
- Added a black/gold logged-out brand entry and a logged-in creation workbench using existing mock project summaries.
- Restored direct canvas routing at `/projects/:projectId/canvas`.
- Added a temporary Shenlu login placeholder route at `/login`.
- Allowed homepage document scrolling while keeping the canvas view as a full-screen workspace.

Verification suggestions:
- Run `npm run build`.
- Open `/` without `localStorage.shenlu_token` and verify the public homepage.
- Set `localStorage.shenlu_token`, refresh `/`, and verify the creation workbench and project-card canvas navigation.
- Open `/projects/proj-aurora/canvas` and confirm the existing canvas still renders.

## 2026-04-27

Changed files:
- `.env.example`
- `.env.production`
- `apps/sluvo-web/vite.config.js`
- `apps/sluvo-web/src/api/client.js`
- `doc/API_DEVELOPMENT.md`
- `doc/DEVELOPMENT.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Documented production API routing through `https://api.shenlu.top`.
- Added a production env file for building Sluvo against `api.shenlu.top`.
- Configured the Vite app to read environment files from the repository root.
- Updated the API client URL builder so environment API hosts and `/api/...` paths compose cleanly.
- Clarified that Sluvo production needs `https://sluvo.shenlu.top` allowed by backend CORS.

Verification suggestions:
- Build with `VITE_API_BASE=https://api.shenlu.top`.
- Confirm authenticated browser requests from `sluvo.shenlu.top` include `Authorization` and pass backend CORS.

## 2026-04-24

Changed files:
- `AGENTS.md`
- `README.md`
- `doc/API_DEVELOPMENT.md`
- `.gitignore`
- `.editorconfig`
- `.env.example`
- `doc/DEVELOPMENT.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added repository-level development rules and frontend/backend integration guidance.
- Added local development, UI, frontend architecture, backend contract, and changelog documents.
- Added baseline repository hygiene files for future frontend implementation.

Verification suggestions:
- Confirm future Codex sessions start by reading `AGENTS.md`.
- Confirm frontend scaffold uses `/api` relative paths and Vite proxy.
- Confirm no backend implementation is added to Sluvo for MVP.

Changed files:
- `package.json`
- `README.md`
- `doc/DEVELOPMENT.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/CHANGELOG_DEV.md`
- `apps/sluvo-web/package.json`
- `apps/sluvo-web/index.html`
- `apps/sluvo-web/vite.config.js`
- `apps/sluvo-web/src/App.vue`
- `apps/sluvo-web/src/main.js`
- `apps/sluvo-web/src/router/index.js`
- `apps/sluvo-web/src/api/client.js`
- `apps/sluvo-web/src/api/projectWorkspaceApi.js`
- `apps/sluvo-web/src/mock/projects.js`
- `apps/sluvo-web/src/stores/projectStore.js`
- `apps/sluvo-web/src/stores/canvasStore.js`
- `apps/sluvo-web/src/stores/taskStore.js`
- `apps/sluvo-web/src/components/layout/CommandBar.vue`
- `apps/sluvo-web/src/components/layout/LeftSidebar.vue`
- `apps/sluvo-web/src/components/layout/RightInspector.vue`
- `apps/sluvo-web/src/components/layout/TaskDrawer.vue`
- `apps/sluvo-web/src/canvas/nodes/WorkflowNode.vue`
- `apps/sluvo-web/src/views/ProjectListView.vue`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/theme.css`
- `apps/sluvo-web/src/styles/base.css`

Impact scope:
- Added a standalone Vue 3 + Vite + Pinia + Vue Router + Vue Flow frontend MVP under `apps/sluvo-web`.
- Implemented mock-backed project list and infinite canvas workspace shell with command bar, left node library, right inspector, and task drawer.
- Added core canvas interactions for pan, zoom, fit view, node creation, drag, selection, multi-selection, node connection, and delete.
- Added root npm workspace scripts so the repository can be installed and started from the root.

Verification suggestions:
- Run `npm install` at the repository root and confirm workspace dependencies install correctly.
- Run `npm run dev` and verify the app starts on port `5174`.
- Run `npm run build` and verify the app builds successfully.

Changed files:
- `apps/sluvo-web/src/router/index.js`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/views/ProjectListView.vue`
- `apps/sluvo-web/src/components/layout/CommandBar.vue`
- `apps/sluvo-web/src/components/layout/LeftSidebar.vue`
- `apps/sluvo-web/src/styles/base.css`

Impact scope:
- Converted the frontend into a single infinite-canvas page at `/`.
- Redirected old project-list routes back to the canvas.
- Removed the project list view and its unused page styles.
- Updated the canvas layout to use a full-screen canvas with floating node library and inspector panels, closer to LibTV-style spatial workflow editing.

Verification suggestions:
- Run `npm run build`.
- Open `http://127.0.0.1:5174/` and verify it enters the canvas directly.

Changed files:
- `apps/sluvo-web/package.json`
- `package-lock.json`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/components/layout/CommandBar.vue`
- `apps/sluvo-web/src/components/canvas/AddNodeMenu.vue`
- `apps/sluvo-web/src/components/canvas/CanvasBottomControls.vue`
- `apps/sluvo-web/src/components/canvas/CanvasToolRail.vue`
- `apps/sluvo-web/src/components/canvas/StarterSkillStrip.vue`
- `apps/sluvo-web/src/canvas/nodes/WorkflowNode.vue`
- `apps/sluvo-web/src/styles/base.css`
- `apps/sluvo-web/src/components/layout/LeftSidebar.vue`
- `apps/sluvo-web/src/components/layout/RightInspector.vue`
- `apps/sluvo-web/src/components/layout/TaskDrawer.vue`
- `apps/sluvo-web/src/stores/taskStore.js`

Impact scope:
- Reworked the canvas to closely follow the provided LibTV infinite-canvas screenshots.
- Added a LibTV-like floating top bar, left vertical tool rail, bottom zoom controls, center starter skill cards, and add-node popup.
- Added double-click-on-canvas creation flow using a floating "添加节点" menu.
- Removed unused project-list/sidebar/inspector/task-drawer surfaces so the app is now a pure canvas page.
- Added `lucide-vue-next` for icon-based canvas controls.

Verification suggestions:
- Run `npm run build`.
- Open `http://127.0.0.1:5174/`, double-click the empty canvas, and verify the add-node menu appears.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/components/canvas/CanvasToolRail.vue`
- `apps/sluvo-web/src/components/canvas/CanvasBottomControls.vue`
- `apps/sluvo-web/src/styles/base.css`

Impact scope:
- Wired the LibTV-style left rail buttons to real canvas actions: add-node menu, starter workflow creation/arrange, resource node insertion, undo, help overlay, and support feedback.
- Wired the bottom controls to real canvas actions: grid visibility toggle, locate/fit view, snap-to-grid toggle, zoom in, and zoom out.
- Improved canvas handling with scroll zoom, pinch zoom, drag pan, box selection, double-click add-node flow, Ctrl+Z undo, Ctrl+D duplicate, Escape close panels, and toast feedback.

Verification suggestions:
- Run `npm run build`.
- Open `http://127.0.0.1:5174/` and verify the left rail, bottom controls, double-click menu, shortcuts, and node creation all respond.


Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/canvas/nodes/WorkflowNode.vue`
- `apps/sluvo-web/src/canvas/edges/WorkflowEdge.vue`
- `apps/sluvo-web/src/components/layout/CommandBar.vue`
- `apps/sluvo-web/src/components/canvas/AddNodeMenu.vue`
- `apps/sluvo-web/src/components/canvas/StarterSkillStrip.vue`
- `apps/sluvo-web/src/utils/statusLabels.js`
- `apps/sluvo-web/src/styles/base.css`

Impact scope:
- Deepened the LibTV-style infinite canvas interaction model.
- Added right-click canvas/node menus, double-click node run, custom labeled workflow edges, richer node cards, running progress, and group frames.
- Added clipboard-like shortcuts: Ctrl/Cmd+C, Ctrl/Cmd+V, Ctrl/Cmd+D, Ctrl/Cmd+G, Ctrl/Cmd+0, Ctrl/Cmd +/-.
- Added keyboard pan, Escape close, delete selection, undo history, and copy/paste with internal edges preserved.

Verification suggestions:
- Run `npm run build`.
- Open `http://127.0.0.1:5174/` and test double-click add node, right-click menus, workflow creation, copy/paste, grouping, zoom, snap, and grid toggles.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/components/canvas/AddNodeMenu.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added drag-out linking for the large direct canvas cards by pulling from the right-side plus handle.
- Added animated direct edge rendering, target-node hit detection, and empty-space release flow for creating a downstream node from the dragged connection.
- Included direct nodes and direct edges in undo history and delete cleanup so the canvas state stays consistent.

Verification suggestions:
- Run `npm run build`.
- Open `http://127.0.0.1:5174/`, create two direct nodes, drag from the right-side plus on the first node to the second node, and verify the glowing line appears and follows node movement.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/components/canvas/AddNodeMenu.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Restored stable add-node menu behavior by using normal click selection again while still stopping pointer events from leaking to the canvas.
- Changed direct node creation to use the saved canvas coordinate from the opened menu, so newly added text cards appear predictably in the visible canvas.
- Explicitly layered direct edge SVGs below direct cards while preserving drag-out connection behavior from the right-side plus handle.

Verification suggestions:
- Run `npm run build`.
- Open `http://127.0.0.1:5174/`, add a text node from the menu, then drag from its right-side plus handle to another direct card.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Fixed add-node creation failure caused by cloning Vue reactive arrays with `structuredClone` during history capture.
- Added mouse-event fallbacks for direct connection dragging so the right-side plus handle works with normal mouse input as well as pointer events.
- Increased automatic placement offset for newly added direct cards so consecutive nodes do not cover each other's connection handles.

Verification suggestions:
- Run `npm run build`.
- In the browser, add two nodes from the left add menu, drag from the first node's right plus handle onto the second node, and confirm a glowing edge is created.

