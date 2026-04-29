# Sluvo PRD

Version: 0.1
Date: 2026-04-24
Owner: Shenlu product and engineering
Status: planning

## 1. Executive Decision

Recommendation: build Sluvo as a new standalone frontend subsite for the infinite canvas product, while reusing the current `ai.shenlu.top` backend and core data model.

Suggested domain:
- Primary: `sluvo.shenlu.top`
- Alternative: `studio.shenlu.top`
- Keep current `ai.shenlu.top` as the stable production creation workspace during the first launch stage.

Rationale:
- The current user frontend already carries script, asset, storyboard, dubbing, editing, account, and assistant workflows. A full infinite canvas interface will change navigation, layout, keyboard behavior, rendering strategy, and creator mental model. Shipping it as a subsite reduces blast radius.
- The backend already has reusable foundations: `Script` as project root, `Episode`, `SharedResource`, `Panel`, `GenerationUnit`, `GenerationRecord`, `TaskJob`, `CanvasWorkspace`, `CanvasNode`, `CanvasEdge`, project workspace aggregation, and provider dispatch.
- The existing hidden canvas code is useful as a reference, but not enough as the final product experience. A new subsite lets us rebuild the interaction layer cleanly while consuming the same project workspace APIs.
- Backend reuse preserves login, team permissions, points, provider keys, OSS storage, async tasks, model routing, and historical project data.

Decision summary:

| Option | Recommendation | Why |
| --- | --- | --- |
| Add directly inside current `frontend/` | Use only as fallback | Fastest to reuse UI state, but high coupling and product risk |
| New subsite + reused backend | Recommended | Clean product surface, safer rollout, shared data and billing |
| New frontend + new backend | Not recommended for MVP | Too slow and duplicates auth, assets, tasks, billing, providers |

## 2. Product Positioning

Sluvo is an AI-native creative workspace from Shenlu for comic and short-drama creators. It lets creators place scripts, characters, scenes, props, storyboard shots, reference images, generated images, generated videos, notes, and model actions on one infinite canvas, then connect them into an executable production graph.

One-line positioning:

> A canvas-based AI production workspace that turns story ideas into reusable assets, storyboard shots, images, videos, and team-ready creative workflows.

Primary users:
- Solo creators producing AI comics or short dramas.
- Small content teams with script, visual, and video roles.
- Agencies that need repeatable short-video or ad production workflows.
- Internal Shenlu operators who need to debug or demonstrate full project generation chains.

## 3. Product Goals

MVP goals:
- Let a creator start from text or an existing Shenlu project and see the whole project as a visual production map.
- Let script, asset, storyboard, image, and video nodes run existing Shenlu generation capabilities.
- Make generated outputs traceable: every image or video should show what prompt, asset references, storyboard shot, and model produced it.
- Preserve current backend truth: canvas nodes are presentation and orchestration, not the sole business source of truth.

Non-goals for MVP:
- No full real-time multiplayer editing in the first release.
- No public marketplace in the first release.
- No replacement of all current `ai.shenlu.top` workflow pages in the first release.
- No separate user, billing, or provider account system.

## 4. Deployment And Architecture Strategy

### 4.1 Frontend Strategy

Create a new top-level application under this directory when implementation starts:

```text
sluvo/
  doc/
  app/
    src/
    package.json
    vite.config.*
```

Recommended implementation:
- Independent Vite frontend.
- Reuse existing Shenlu login token, preferably `shenlu_token`.
- Call the existing backend under the same API gateway or shared `/api` reverse proxy.
- Keep the current `frontend/` unchanged during MVP except for optional entry links after the subsite is stable.

Canvas engine recommendation:
- If we keep Vue: use `@vue-flow/core` for the first graph-based MVP because the current hidden canvas already uses it.
- If we choose a more freeform creative canvas: evaluate `tldraw`, `Konva`, `PixiJS`, or a custom renderer. `tldraw` is stronger for whiteboard-like interaction but may push the app toward React.
- MVP should prioritize data flow and execution graph over perfect whiteboard freedom.

### 4.2 Backend Strategy

Reuse the current FastAPI backend.

Existing backend capabilities to reuse:
- Auth and team permission chain.
- `Script` as the project aggregate root.
- `Episode` as script content and episode container.
- `SharedResource` and `SharedResourceVersion` for characters, scenes, props, and appearance prompts.
- `Panel` as storyboard shot truth.
- `GenerationUnit`, `GenerationUnitInput`, `GenerationRecord`, `TaskJob`, and `MediaAsset` for image and video production.
- `CanvasWorkspace`, `CanvasNode`, and `CanvasEdge` for canvas projection state.
- `GET /api/projects/{project_id}/workspace` as the first read model.
- Existing image, video, asset extraction, and storyboard extraction task chains.

Backend extension principle:
- Add thin product-facing adapters only where the new canvas needs a cleaner contract.
- Do not fork provider logic.
- Do not move project truth into canvas JSON.
- Treat canvas positions, hidden state, selected layout, collapsed cards, and view metadata as projection data.

## 5. Existing System Fit

Current code signals:
- `backend/routers/project_workspace.py` already exposes project workspace aggregation and canvas-oriented actions.
- `backend/services/project_workspace_service.py` builds a workspace snapshot from existing project facts.
- `backend/services/canvas_projection_service.py` projects domain facts into canvas nodes and edges.
- `frontend/src/views/ScriptCanvasView.vue` exists and uses Vue Flow, but current docs show mixed status around whether it is active, hidden, or historical.
- `docs/API_MAP.md` documents `/api/projects/{project_id}/workspace` and related project workspace APIs as implemented.

Product implication:
- We should reuse the backend model and service direction.
- We should not rely on the old hidden frontend canvas as the final user experience.
- Before implementation, reconcile doc status for canvas modules so engineering has one source of truth.

## 6. User Experience Scope

### 6.1 MVP User Flow

1. User opens `sluvo.shenlu.top`.
2. If not logged in, redirect to Shenlu login or show embedded login.
3. User creates a new canvas project or imports an existing Shenlu project.
4. The canvas loads project facts as nodes:
   - project root
   - script or episode nodes
   - asset table node
   - storyboard table node
   - image generation units
   - video generation units
5. User edits text, prompts, asset references, and shot rows.
6. User connects assets or generated images to storyboard image or video units.
7. User runs a node or a selected branch.
8. The backend creates or updates existing generation records and tasks.
9. The canvas refreshes the project workspace and shows completed outputs.
10. User exports a board snapshot, project package, or generated media list.

### 6.2 Core Views

| View | Purpose |
| --- | --- |
| Project list | Open recent projects or create a new canvas project |
| Canvas workspace | Main infinite canvas and executable graph |
| Node inspector | Edit selected node details, prompts, model params, references, and history |
| Run queue drawer | Show submitted tasks, status, cost, failures, and retry actions |
| Asset library drawer | Search and drag existing characters, scenes, props, references, and media |
| Template drawer | Insert common workflows such as script to storyboard, character consistency, image to video |

## 7. Node Model

MVP node types:

| Node Type | Source Of Truth | Main Actions |
| --- | --- | --- |
| `project_root` | `Script` | edit title, aspect ratio, style preset |
| `script_episode` | `Episode` | save source, extract assets, extract storyboard |
| `asset_table` | `SharedResource` | edit assets, generate asset images, bind to shots |
| `storyboard_table` | `Panel` | edit shots, generate images, create video units |
| `prompt_note` | canvas-only | reusable prompt snippets, comments, planning |
| `image_unit` | `GenerationUnit` | run image generation, compare versions, set as reference |
| `video_unit` | `GenerationUnit` | run video generation, select first frame, preview history |
| `media_board` | `MediaAsset` or query result | collect outputs for review and export |

Edge types:
- `reference`: source media or asset is used as a reference.
- `identity`: character or prop identity reference.
- `first_frame`: image used as video first frame.
- `style`: style or mood reference.
- `generation`: output dependency between generation units.
- `contains`: project, episode, or table grouping relationship.

## 8. Functional Requirements

### P0: MVP

- Infinite canvas navigation: pan, zoom, fit view, minimap, selection, drag, resize, hide, restore.
- Project workspace load from existing backend.
- Create project and episode from canvas entry.
- Render project, script, asset, storyboard, image, and video nodes.
- Persist node position, size, hidden state, and collapsed state.
- Edit script source and save through backend.
- Extract assets from script.
- Extract storyboard from script.
- Generate asset images.
- Generate storyboard shot images.
- Generate storyboard shot videos from image references.
- Connect image and asset references to generation units.
- Show task states: queued, running, waiting upstream, succeeded, failed.
- Show cost and point estimate where backend exposes it.
- Refresh workspace after task completion.
- Export canvas as PNG and export project workflow JSON.

### P1: Production Beta

- Node templates and workflow templates.
- Branch run: execute selected downstream graph.
- Output comparison board for image and video variants.
- Prompt library and reusable style packs.
- Version timeline per node.
- Comment pins and review state.
- Lightweight sharing link inside the same team.
- Better conflict handling with optimistic locking and refresh prompts.
- Search command palette for nodes, assets, shots, and actions.

### P2: Growth And Platform

- Public template gallery.
- Forkable community canvases.
- Team permission roles for edit, run, comment, and export.
- Real-time collaboration with presence and patch sync.
- Workflow API for external agents.
- Template marketplace and revenue sharing.
- Multi-project boards for campaign-level production.

## 9. API Planning

Reuse first:

| Capability | Existing API Direction |
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
| Hide or restore canvas projection | `POST /api/canvas/nodes/{node_id}/hide`, `POST /api/canvas/nodes/{node_id}/restore` |

Likely new API adapters:

| Capability | Proposed Shape | Reason |
| --- | --- | --- |
| Save canvas viewport | `PATCH /api/projects/{project_id}/canvas-view` | Restore user view without touching domain facts |
| Batch geometry update | `PATCH /api/canvas/nodes/geometry:batch` | Avoid many writes during drag or layout |
| Insert prompt note | `POST /api/projects/{project_id}/canvas-notes` | Canvas-only planning nodes |
| Run selected graph | `POST /api/projects/{project_id}/graph-runs` | Product action over multiple units |
| Export workflow JSON | `GET /api/projects/{project_id}/workflow-export` | Portable workflow and debugging |

## 10. Data Ownership Rules

The canvas is not the only truth layer.

Truth ownership:
- Project identity: `Script`
- Script source: `Episode.source_text` or current script source model
- Assets: `SharedResource` and `SharedResourceVersion`
- Storyboard shots: `Panel`
- Media requests: `GenerationUnit`
- Provider records: `GenerationRecord`
- Async state: `TaskJob`
- Canvas layout: `CanvasWorkspace`, `CanvasNode`, `CanvasEdge`

Canvas JSON may store:
- x, y, width, height
- hidden, locked, collapsed
- local UI view metadata
- selected node visual state
- note node content if deliberately canvas-only
- ports and presentation hints

Canvas JSON must not become the only storage for:
- script source
- asset list
- storyboard rows
- generated media truth
- billing state
- provider task state

## 11. Frontend Module Plan

Suggested structure after implementation starts:

```text
sluvo/app/src/
  api/
    client.ts
    projectWorkspace.ts
    generation.ts
  canvas/
    components/
    nodes/
    edges/
    layout/
    interactions/
  stores/
    authStore.ts
    projectStore.ts
    canvasStore.ts
    taskStore.ts
  views/
    ProjectListView.vue
    CanvasWorkspaceView.vue
  routes/
  styles/
```

If the app chooses React instead of Vue, keep the same module boundary:
- `api`
- `canvas`
- `nodes`
- `stores`
- `views`

## 12. Milestones

### Week 1-2: Product And Technical Alignment

- Freeze MVP node types.
- Reconcile current canvas docs and actual backend behavior.
- Confirm subdomain and auth flow.
- Decide Vue Flow vs other canvas engine.
- Define workspace response fields the new app needs.

### Week 3-5: Canvas MVP

- Bootstrap standalone frontend app.
- Implement auth, project list, workspace load.
- Render core nodes and edges.
- Persist node geometry.
- Add node inspector and asset drawer.

### Week 6-8: Execution

- Wire script save, asset extraction, storyboard extraction.
- Wire asset image, storyboard image, and video generation units.
- Show task status and refresh workspace.
- Implement connection semantics for reference, identity, and first frame.

### Week 9-10: Beta Quality

- Add templates, export, task drawer, error states, and retry.
- Add onboarding sample project.
- Add basic telemetry.
- Internal QA on real projects.

### Week 11-12: Public Beta

- Deploy `sluvo.shenlu.top`.
- Add optional entry from `ai.shenlu.top`.
- Run beta with selected creators.
- Track activation, run success rate, and first-output time.

## 13. Success Metrics

Activation:
- New user creates or opens a canvas project.
- User runs at least one generation unit.

Core product:
- Median time from project open to first generated image.
- Median time from script paste to storyboard generation.
- Percentage of projects with at least one connected reference edge.
- Generation success rate by unit type.
- Retry rate and failed task reason distribution.

Retention:
- 7-day returning canvas creators.
- Projects reopened after first generation.
- Template reuse rate.

Business:
- Points consumed from canvas workflows.
- Paid conversion after canvas usage.
- Team projects using comments or sharing.

## 14. Risks And Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Existing canvas docs conflict with actual code | Engineering confusion | Reconcile docs before implementation |
| Drag persistence causes excessive writes | Backend pressure | Add batch geometry save and debounce |
| Canvas becomes another source of truth | Data drift | Keep domain writes in existing business models |
| Long-running tasks feel disconnected | User loses trust | Central task drawer and workspace refresh after completion |
| New frontend diverges from auth or billing | Operational complexity | Reuse `shenlu_token`, team permissions, `TaskJob`, and points |
| Existing mojibake in some files leaks into new UI | Poor product polish | New subsite copy must be UTF-8 clean and creator-oriented |

## 15. Open Questions

- Should the first release support only project-bound canvases, or also blank exploratory canvases?
- Should note and prompt nodes be canvas-only, or saved as reusable prompt assets?
- Should the subsite use Vue to stay close to the current stack, or React to access stronger canvas ecosystems?
- Should public template sharing wait until billing and permissions are more granular?
- Should `ai.shenlu.top` link to the subsite only from project pages, or also from the dashboard?

## 16. Final Recommendation

Use a new subsite with backend reuse.

The best first architecture is:

```text
sluvo.shenlu.top
  standalone Sluvo frontend
  uses shenlu_token
  calls existing FastAPI backend
  consumes /api/projects/{id}/workspace
  writes domain changes through project workspace adapters
  runs generation through existing TaskJob and provider chains

ai.shenlu.top
  remains the stable creator workspace
  later links into canvas for selected projects
```

This gives the product enough freedom to feel like TapNow or LibTV, without rebuilding Shenlu's hardest backend assets from scratch.
