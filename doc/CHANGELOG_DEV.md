# Sluvo Development Changelog

## 2026-05-06

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `backend/schemas.py`
- `backend/routers/sluvo.py`
- `backend/services/sluvo_service.py`
- `backend/tests/test_sluvo_service.py`
- `doc/BACKEND_CONTRACTS.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Split Agent waiting-state composer behavior from explicit stage progression: typed feedback now revises the current stage, while `继续下一步` advances to the next Agent.
- Agent continuation now carries previous artifacts into the next stage context so story structure, character, scene, and storyboard outputs stay connected to the drafted script.
- Added tests for revising the current inspiration stage without accidentally creating the next story-structure step.

Verification suggestions:
- `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py backend/schemas.py backend/tests/test_sluvo_service.py`
- `npm run build --workspace sluvo-web`
- `git diff --check`

## 2026-05-06

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Improved Agent-written text nodes with an artifact chip, preserved Agent artifact metadata through frontend persistence, and added denser script/setting Markdown styling.
- Script, character, scene, prop, and storyboard nodes now read more like production cards instead of oversized generic text blocks.

Verification suggestions:
- `npm run build --workspace sluvo-web`
- `git diff --check`

## 2026-05-06

Changed files:
- `backend/services/sluvo_service.py`
- `backend/tests/test_sluvo_service.py`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Changed Agent workflow artifacts so inspiration inputs become concrete script, character, scene, prop, and storyboard content instead of workflow-template text.
- Added an LLM-backed artifact drafting path with a specific non-template fallback when the model key is unavailable.
- Covered short inspiration input like `雨夜迈巴赫` so the first text node contains a usable script draft and no model/debug labels.

Verification suggestions:
- `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py backend/tests/test_sluvo_service.py`
- `python3 -m pytest backend/tests/test_sluvo_service.py -q`
- `git diff --check`

## 2026-05-06

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Removed internal status, routing, model, and canvas-write metadata from ordinary 创作总监 direct-answer cards.
- Ordinary question runs now show only the user's message and the assistant answer, while creative workflow runs still keep their stage and artifact labels.

Verification suggestions:
- `npm run build --workspace sluvo-web`
- `git diff --check`

## 2026-05-06

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Changed ordinary 创作总监 question replies into a compact direct-answer conversation card instead of rendering them as staged production steps.
- Kept creative inspiration and script inputs on the existing staged Agent Team timeline.

Verification suggestions:
- `npm run build --workspace sluvo-web`
- `git diff --check`

## 2026-05-06

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `backend/services/sluvo_service.py`
- `backend/tests/test_sluvo_service.py`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Restored the text-node local analysis inspiration-point estimate flow across frontend and backend.
- Added the missing shared prompt-message builder used by both estimate and analysis, preventing the text-node estimate endpoint from failing at runtime.
- The selected text-node composer now shows an estimated inspiration-point badge and keeps the estimate in sync after analysis completes.

Verification suggestions:
- `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py backend/tests/test_sluvo_service.py`
- `npm run build --workspace sluvo-web`
- `git diff --check`

## 2026-05-05

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added a visible official Agent Team roster to the 创作总监 panel so users can see the default collaborative roles, responsibilities, and outputs before running a workflow.
- Official roles can now be selected directly or copied into "我的 Agent" as editable custom templates.
- Kept the simplified run timeline while making the relationship between official Agents, user custom Agents, and collaborative execution explicit.

Verification suggestions:
- `npm run build --workspace sluvo-web`
- `git diff --check`

## 2026-05-05

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Simplified the 创作总监 panel into a clearer staged brief: current task, progress, next action, compact run history, and stage summaries.
- Collapsed verbose artifact bodies into short status chips so the Agent timeline reads at a glance instead of like raw logs.
- Reduced quick actions and visual noise while keeping Agent Team settings, history restore, step retry, and media confirmation available.

Verification suggestions:
- `npm run build --workspace sluvo-web`
- `git diff --check`

## 2026-05-05

Changed files:
- `backend/models.py`
- `backend/database.py`
- `backend/schemas.py`
- `backend/services/sluvo_service.py`
- `backend/routers/sluvo.py`
- `backend/tests/test_sluvo_service.py`
- `apps/sluvo-web/src/api/sluvoApi.js`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/API_DEVELOPMENT.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added `SluvoAgentRun`, `SluvoAgentStep`, and `SluvoAgentArtifact` persistence plus lightweight create-table migrations.
- Added Agent Run APIs for create/list/read/continue/confirm-cost/retry while keeping legacy session/action proposal endpoints compatible.
- The right-side 创作总监 panel now starts staged Agent Team workflow runs and renders a stage timeline with artifacts, automatic text/placeholder canvas writes, run history restore, media cost confirmation, and failed-step retry affordances.

Verification suggestions:
- `python3 -m py_compile backend/models.py backend/schemas.py backend/services/sluvo_service.py backend/routers/sluvo.py`
- `npm run build --workspace sluvo-web`
- `git diff --check`

## 2026-05-05

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `backend/routers/sluvo.py`
- `backend/services/sluvo_service.py`
- `backend/tests/test_sluvo_service.py`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Fixed Agent proposal writes that could fail with "无效的资源标识符" when selected or Agent-connected canvas nodes still carried frontend client IDs.
- Made Agent session/action target IDs tolerant of stale client IDs and let canvas batch edge resolution fall back to node `clientId` mappings.
- Stopped auto-restoring failed Agent actions as the active pending proposal so stale failures no longer reappear as the current panel state.

Verification suggestions:
- `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py backend/tests/test_sluvo_service.py`
- `npm run build`
- `git diff --check`

## 2026-05-05

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Allowed rendered Markdown text inside Sluvo text nodes to be selected and copied.
- Added the Markdown body to the direct-node interaction whitelist so text selection does not start node dragging or get blocked by the canvas-level selection guard.

Verification suggestions:
- `npm run build`
- `git diff --check`

## 2026-05-05

Changed files:
- `apps/sluvo-web/src/api/sluvoApi.js`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `backend/schemas.py`
- `backend/routers/sluvo.py`
- `backend/services/sluvo_service.py`
- `backend/tests/test_sluvo_service.py`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/PRD.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Split text-node local AI from the right-side Canvas Agent conversation. The selected text node composer now calls a node-scoped analysis endpoint and writes the Markdown reply back into that node.
- Added a backend text-node analysis contract that uses DeepSeek Flash/Pro when available and deterministic Markdown fallback otherwise, without creating Agent sessions, events, actions, or mutations.
- Center-aligned the text-node composer with the text-node frame by giving prompt-note nodes a shared width and making the composer fill that node width.

Verification suggestions:
- `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py backend/models.py backend/schemas.py backend/tests/test_sluvo_service.py`
- `npm run build`
- `git diff --check`

## 2026-05-04

Changed files:
- `apps/sluvo-web/src/api/sluvoApi.js`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/components/canvas/AddNodeMenu.vue`
- `apps/sluvo-web/src/canvas/nodes/WorkflowNode.vue`
- `apps/sluvo-web/src/styles/base.css`
- `backend/models.py`
- `backend/database.py`
- `backend/schemas.py`
- `backend/routers/sluvo.py`
- `backend/services/sluvo_service.py`
- `backend/services/deepseek_model_policy.py`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added the first Sluvo Canvas Agent MVP: a canvas-side Agent panel, Agent node type, selected-node context actions, and approve/cancel proposal flow.
- Added backend Agent runtime proposals that create `SluvoAgentAction` records and apply approved patches through the existing canvas batch/mutation audit path.
- Added user Agent templates and community Agent publication/fork/unpublish contracts.
- Added selectable Agent model codes for `deepseek-v4-flash` and `deepseek-v4-pro`; when a DeepSeek API key is configured, Canvas Agent proposals use the selected model and fall back to rule-based proposals if the call fails.

Verification:
- `python3 -m py_compile backend/services/sluvo_service.py backend/services/deepseek_model_policy.py backend/routers/sluvo.py backend/models.py backend/schemas.py backend/database.py`
- `npm run build`
- `git diff --check`

## 2026-05-04

Changed files:
- `apps/sluvo-web/index.html`
- `apps/sluvo-web/public/favicon.png`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added the Sluvo logo as the website favicon and Apple touch icon so browser tabs and shortcuts show the product logo instead of the default browser icon.

Verification:
- `npm run build`
- `git diff --check`

## 2026-05-04

Changed files:
- `backend/services/sluvo_service.py`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Fixed permanent recycle-bin deletion ordering for Sluvo projects.
- Child records are now deleted and flushed in dependency order before parent canvas and project rows, preventing MySQL foreign-key failures when deleting a project with canvas nodes.

Verification:
- `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py`
- `npm run build`
- `git diff --check`

## 2026-05-04

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `apps/sluvo-web/src/views/ProjectListView.vue`
- `apps/sluvo-web/src/views/TrashView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Aligned the full project space and recycle-bin navigation rail with the logged-in homepage rail.
- Unified rail logo sizing, dark gold background, active/hover states, icon order, separator styling, and topbar brand logo framing across the logged-in pages.

Verification:
- `npm run build`
- `git diff --check`

## 2026-05-04

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `apps/sluvo-web/src/views/ProjectListView.vue`
- `apps/sluvo-web/src/views/TrashView.vue`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Changed the logged-in navigation rail from sticky layout behavior to fixed viewport positioning across the home, full project space, and recycle-bin pages.
- Added main-content offsets so desktop content does not slide under the fixed left rail, and narrow screens use a fixed top rail with matching top spacing.

Verification:
- `npm run build`
- `git diff --check`

## 2026-05-04

Changed files:
- `apps/sluvo-web/src/api/sluvoApi.js`
- `apps/sluvo-web/src/views/TrashView.vue`
- `backend/routers/sluvo.py`
- `backend/services/sluvo_service.py`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Implemented recycle-bin actions for Sluvo projects: users can restore soft-deleted projects or permanently delete them.
- Added backend endpoints for project restore and permanent deletion. Permanent deletion removes the Sluvo project record and its Sluvo canvases, nodes, edges, canvas assets, agent records, mutations, members, and community publication record while leaving OSS objects untouched.
- Updated the recycle-bin copy and cards to show real action buttons instead of future-capability language.

Verification:
- `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py`
- `npm run build`

## 2026-05-04

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `apps/sluvo-web/src/views/ProjectListView.vue`
- `apps/sluvo-web/src/views/TrashView.vue`
- `apps/sluvo-web/src/router/index.js`
- `apps/sluvo-web/src/api/sluvoApi.js`
- `backend/routers/sluvo.py`
- `backend/services/sluvo_service.py`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Adjusted the logged-in homepage toward a creator-workbench information flow: recent projects are now a single horizontal row with `新建项目` and `查看全部` actions, platform highlights sit below, and the community block moves to the bottom as a larger scroll discovery space.
- Added a full project space at `/projects`, opened by the left rail folder icon and by the homepage `查看全部` action.
- Added a recycle bin at `/trash`, opened by the left rail trash icon, backed by soft-deleted Sluvo projects from `GET /api/sluvo/projects?includeDeleted=true`.
- Exposed `deletedAt` in the Sluvo project serializer so the recycle bin can show retention timing.

Verification:
- `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py`
- `npm run build`
- `git diff --check`

## 2026-05-04

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Reordered the logged-in homepage lower area so the creation start module appears before inspiration samples and community content.
- Added a creation-first two-column section with a prominent new-canvas card, up to four recent projects, empty-state guidance, and lightweight platform highlights.
- Merged the open ecosystem and Agent capability blocks into one lower explanatory section to reduce page weight while preserving platform positioning.

Verification:
- `npm run build`
- `git diff --check`

## 2026-05-04

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Changed the logged-in homepage creator headline into a single-line rotating slogan.
- Added six director/producer/storyboard/agent-themed prompt slogans while preserving the existing headline as the first line.
- Widened the headline content area and added responsive type sizes so the desktop title stays on one row.

Verification:
- `npm run build`
- `git diff --check`

## 2026-05-04

Changed files:
- `apps/sluvo-web/src/views/CommunityCanvasView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Changed the community canvas detail preview from a cropped full-size node view to a fit-to-frame panoramic canvas preview.
- Added ResizeObserver-based preview sizing so the read-only canvas scales to show all nodes across desktop and mobile widths.
- Changed image nodes in the community preview to use contain-fit media rendering so published images are not cropped inside the preview card.

Verification:
- `npm run build`
- `git diff --check`

## 2026-05-03

Changed files:
- `apps/sluvo-web/src/components/layout/CommandBar.vue`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Changed the canvas topbar community publish entry from an icon-only share button to a visible `发布` action.
- Added the missing publish dialog overlay/dialog styling so the community publish form appears above the canvas.
- Excluded the publish overlay from canvas pan/selection/context interactions while it is open.

Verification:
- `npm run build`
- `git diff --check`

## 2026-05-03

Changed files:
- `backend/models.py`
- `backend/database.py`
- `backend/schemas.py`
- `backend/services/sluvo_service.py`
- `backend/routers/sluvo.py`
- `apps/sluvo-web/src/api/sluvoApi.js`
- `apps/sluvo-web/src/router/index.js`
- `apps/sluvo-web/src/views/HomeView.vue`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/views/CommunityCanvasView.vue`
- `apps/sluvo-web/src/components/layout/CommandBar.vue`
- `doc/PRD.md`
- `doc/API_DEVELOPMENT.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added open canvas community publication storage, public list, login-gated detail, publish, unpublish, and fork APIs.
- Added homepage community cards, a read-only community detail page, and a canvas-workbench publish dialog.
- Forked community canvases create independent Sluvo projects while referencing original OSS media URLs.

Verification:
- `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py backend/models.py backend/schemas.py backend/database.py`
- `npm run build`
- `git diff --check`

## 2026-05-03

Changed files:
- `apps/sluvo-web/src/api/creativeApi.js`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Completed the canvas video generation node with backend video model catalog loading, dynamic model/type/parameter controls, inspiration point estimation, generation submission, polling, persistence, and video preview/download.
- Reused image-node reference handling so connected/generated/uploaded images can drive video generation as first-frame or image references.
- Added the Seedance 2.0 text-to-video web search toggle to the canvas video node, including persistence and estimate/generate payload support.
- Consolidated the canvas video node controls into a compact model/type/settings/generate bar with a single popover for ratio, resolution, duration, quality, motion, audio, and web search.
- Added generation-type-aware video references: text-to-video hides and ignores references, image-to-video requires an image, reference-to-video accepts image/video/audio, and start/end video sends ordered first/last frame images.
- Reworked start/end video references into two explicit first-frame and last-frame slots that can be uploaded or replaced independently.
- Added the same enlarged hover preview treatment to the start/end frame slots as regular image reference thumbnails.
- Hid node connection ports while reference hover previews are open so plus handles do not appear through the enlarged preview.
- Removed the approximate inspiration point prefix from the canvas video button and raised the settings popover above node ports while it is open.
- Tightened video result URL parsing so thumbnail OSS/CDN images are not treated as playable video sources, and kept completed video nodes in the upper preview player instead of switching to a failed control state on transient playback load errors.

Verification:
- `npm run build`

## 2026-05-03

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Replaced the logged-in homepage Agent planning visual with the Shenlu OSS asset `agent-team-planning-cover.webp`.

Verification:
- `npm run build`

## 2026-05-03

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `backend/services/sluvo_service.py`
- `backend/routers/sluvo.py`
- `doc/UI_REQUIREMENTS.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Moved the logged-in homepage new-project card to the first position in the recent creation grid.
- Changed project cards to use only project-owned imagery for covers, with a no-cover state when no project image exists.
- Added `firstImageUrl` to Sluvo project payloads from the first active image asset so the homepage can show real project covers.

Verification:
- `npm run build`
- `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py`

## 2026-05-03

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Changed the logged-in homepage inspiration samples from a manually scrollable strip to an automatic rotating showcase.
- Added clickable progress dots while preserving sample-card project creation and hover video preview behavior.

Verification:
- `npm run build`

## 2026-05-03

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Replaced the first batch of logged-in homepage visual media with Shenlu OSS-hosted showcase assets.
- Wired `hero-character-board.webp`, `hero-storyboard-board.webp`, `hero-first-frame.webp`, and `video-first-frame.mp4` into the homepage media configuration.

Verification:
- `npm run build`

## 2026-05-03

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Enhanced the logged-in homepage with a floating media canvas layer around the prompt composer.
- Added an inspiration sample strip with remote image/video previews and prompt-seeded creation actions.
- Upgraded recent projects and open ecosystem cards with visual covers while preserving existing project actions.
- Documented homepage media, hover-video, and remote-asset expectations.

Verification:
- `npm run build`

## 2026-05-03

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Expanded the public and logged-in homepage copy around the future open canvas, Agent team, Skill, and community sharing vision.
- Updated the logged-in workbench banner, prompt guidance, quick skill chips, Agent capability copy, and added an open ecosystem goal module.
- Kept the approved hero eyebrow and logged-in creator title unchanged.

Verification:
- `npm run build`

## 2026-05-02

Changed files:
- `/Volumes/T9/ljtpc/work/AIdrama/backend/services/oss_service.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/services/storage_service.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/services/sluvo_service.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/tests/test_sluvo_service.py`
- `apps/sluvo-web/src/api/sluvoApi.js`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/CHANGELOG_DEV.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/UI_REQUIREMENTS.md`

Impact scope:
- Restored the planned upload split: files up to `5MB` use base64 JSON, larger files up to `20MB` use multipart upload with XHR progress.
- Sluvo OSS object keys now stay under the existing per-user namespace and add Sluvo project/canvas folders for asset management.
- Sluvo upload persistence now enforces the shared user storage quota path; the default free-user capacity is `5GB`.
- Fixed storage quota tier normalization so enum-backed free users resolve to the intended `5GB` default.
- Duplicate uploads in the same user/project scope reuse existing OSS objects by file hash while still returning canvas asset metadata.

Verification:
- `python3 -m py_compile services/oss_service.py services/storage_service.py services/sluvo_service.py tests/test_sluvo_service.py`
- `uv run --with pytest --with fastapi --with sqlmodel --with hashids --with passlib --with pydantic-settings --with email-validator pytest tests/test_sluvo_service.py -q`
- `npm run build`

## 2026-05-02

Changed files:
- `/Volumes/T9/ljtpc/work/AIdrama/backend/schemas.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/services/sluvo_service.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/routers/sluvo.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/tests/test_sluvo_service.py`
- `apps/sluvo-web/src/api/client.js`
- `apps/sluvo-web/src/api/sluvoApi.js`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added Sluvo-specific persistent canvas asset upload endpoints for multipart and base64 payloads.
- Uploads now write OSS-backed media metadata into `sluvo_canvas_asset` and the existing `storage_object` system.
- Canvas upload nodes now show immediate local previews, real upload progress, retryable failures, and replace `blob:` previews with permanent OSS URLs after upload.
- Batch persistence strips local preview URLs so temporary browser-only media is not saved as project truth.

Verification:
- `python3 -m py_compile schemas.py services/sluvo_service.py routers/sluvo.py`
- `uv run --with pytest --with fastapi --with sqlmodel --with hashids --with passlib --with pydantic-settings --with email-validator pytest tests/test_sluvo_service.py -q`
- `npm run build`

## 2026-05-02

Changed files:
- `apps/sluvo-web/src/api/client.js`
- `apps/sluvo-web/src/api/sluvoApi.js`
- `apps/sluvo-web/src/stores/authStore.js`
- `apps/sluvo-web/src/stores/projectStore.js`
- `apps/sluvo-web/src/router/index.js`
- `apps/sluvo-web/src/views/LoginView.vue`
- `apps/sluvo-web/src/views/HomeView.vue`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/components/layout/CommandBar.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/API_DEVELOPMENT.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added a Sluvo API wrapper for real `/api/sluvo/*` project and canvas endpoints.
- Added centralized Shenlu token auth state with `authStore`.
- Replaced the logged-in home mock project flow with real project listing and prompt-based project creation.
- Canvas pages now hydrate from the Sluvo main canvas and autosave nodes, edges, viewport, and snapshot through the batch endpoint.
- Added revision-conflict handling so stale saves refresh instead of overwriting newer server state.
- Agent frontend is intentionally deferred for this milestone.

Verification:
- `npm run build`

## 2026-05-02

Changed files:
- `/Volumes/T9/ljtpc/work/AIdrama/backend/models.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/database.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/schemas.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/services/sluvo_service.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/routers/sluvo.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/main.py`
- `/Volumes/T9/ljtpc/work/AIdrama/backend/tests/test_sluvo_service.py`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/PRD.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added standalone Sluvo backend persistence under `sluvo_*` tables in the reused AIdrama backend.
- Added `/api/sluvo/*` project, canvas, member, and Agent persistence contracts.
- Updated Sluvo docs so new standalone work no longer treats `Script` or legacy canvas projection tables as the primary Sluvo data model.

Verification suggestions:
- Run the AIdrama backend Sluvo service tests.
- Hydrate a Sluvo project through `/api/sluvo/projects/{project_id}/canvas` and save through `/api/sluvo/canvases/{canvas_id}/batch`.

## 2026-05-02

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`

Impact scope:
- Updated direct text nodes to render existing node content as Markdown inside the node frame instead of showing only the empty-state action menu.
- Added a Libtv-style text-node composer under the selected text node with model selection, a write-back action, and an Agent analysis submit action.
- The node-level analysis composer sends the selected text node as context to the right-side 创作总监 flow while keeping conversation history in the Agent panel.

Verification suggestions:
- Run `npm run build`.
- Run `git diff --check`.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `backend/services/sluvo_service.py`
- `backend/tests/test_sluvo_service.py`

Impact scope:
- Added a staged new-story Agent flow: when the user enters an inspiration/script prompt, the backend routes it to the story director and creates a production pipeline proposal.
- The production pipeline writes canvas product nodes for story overview, character/prop extraction, scene setup, storyboard plan, first-frame image generation, and video generation.
- Updated the Agent panel empty state and composer placeholder so users understand that conversation stays in the panel while the canvas receives approved creative artifacts.

Verification suggestions:
- Run `python3 -m py_compile backend/services/sluvo_service.py backend/tests/test_sluvo_service.py backend/routers/sluvo.py backend/models.py backend/schemas.py`.
- Run `npm run build`.
- Run `git diff --check`.

Changed files:
- `backend/services/sluvo_service.py`
- `backend/tests/test_sluvo_service.py`

Impact scope:
- Adjusted Canvas Agent panel proposals so they write only creative product nodes to the canvas instead of also creating a new Agent node for every request.
- Connected the selected source node directly to the generated product node when context is available.
- Tightened the DeepSeek Agent prompt so `prompt.rewrite`, `workflow.plan`, and report actions return actual canvas-ready content instead of instructions about what to do.

Verification suggestions:
- Run `python3 -m py_compile backend/services/sluvo_service.py backend/tests/test_sluvo_service.py backend/routers/sluvo.py backend/models.py backend/schemas.py`.
- Run `npm run build`.
- Run `git diff --check`.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `backend/services/sluvo_service.py`
- `backend/tests/test_sluvo_service.py`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/PRD.md`
- `doc/UI_REQUIREMENTS.md`

Impact scope:
- Reworked the Canvas Agent UX into a right-side, collapsible 创作总监 panel that defaults open and stores its collapsed state locally.
- Changed the default Agent flow to `agentProfile: "auto"` with manual Agent/model controls moved into advanced settings.
- Added backend auto-routing from prompt/context to specialist Agents and action types, returning resolved profile/action/model metadata for the UI.
- Expanded proposal cards with route metadata and a compact node preview list before approval.

Verification suggestions:
- Run `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py backend/models.py backend/schemas.py`.
- Run `python3 -m pytest backend/tests/test_sluvo_service.py -q`.
- Run `npm run build`.
- Run `git diff --check`.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Fixed direct image generation result parsing so completed Shenlu records using `preview_url` or `thumbnail_url` render in the image node preview.
- Stopped task polling from replacing encoded generation record ids with backend internal numeric ids, preserving follow-up record lookups through `/api/creative/records/{record_id}`.

Verification suggestions:
- Run `npm run build`.
- Submit a direct image node generation and confirm the completed image appears after the task finishes.

## 2026-04-30

Changed files:
- `doc/API_SHENLU_TOP.md`
## 2026-04-29

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Changed the logged-in homepage recent projects section to a mock empty state.
- Removed mock recent project cards from the homepage and kept a single new-project placeholder entry.
- Added a logout action to the logged-in homepage topbar.
- Refined logged-out homepage copy into a more premium, mysterious Agent-canvas positioning while keeping the infinite canvas workflow clear.
- Replaced the previous logged-in showcase cards with a Sluvo-specific Agent capability panel.
- Enhanced the logged-out homepage visual preview with an Agent Router core and role-specific Agent capability nodes.
- Removed secondary brand subtitles from the Sluvo logo lockups and rearranged the logged-out Agent nodes into a more spacious orbital layout.
- Removed the center Agent Canvas card from the logged-out preview and refined the hero copy spacing for a cleaner premium layout.

Verification suggestions:
- Run `npm run build`.
- Set `localStorage.shenlu_token`, refresh `/`, and verify the recent projects section only shows the new-project placeholder.
- Click logout from the logged-in homepage and verify it returns to the logged-out homepage.

## 2026-04-28

Changed files:
- `apps/sluvo-web/src/api/authApi.js`
- `apps/sluvo-web/src/views/HomeView.vue`
- `apps/sluvo-web/src/views/LoginView.vue`
- `apps/sluvo-web/src/router/index.js`
- `apps/sluvo-web/src/styles/base.css`
- `apps/sluvo-web/src/styles/theme.css`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added a dual-state Sluvo homepage at `/` and `/projects`.
- Added a black/gold logged-out brand entry and a logged-in creation workbench using existing mock project summaries.
- Replaced the temporary login placeholder with a black/gold email/password login surface backed by the existing `/api/auth/login` endpoint.
- Restored direct canvas routing at `/projects/:projectId/canvas`.
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
- `doc/BACKEND_CONTRACTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added an audited `api.shenlu.top` API inventory for Sluvo.
- Separated Sluvo P0 direct-call APIs from OpenClaw API-key APIs, legacy compatibility routes, admin routes, provider callbacks, and stream-host caveats.
- Linked the new inventory from the existing API development and backend contract docs.

Verification suggestions:
- Re-check `https://api.shenlu.top/openapi.json` when backend routes change.
- Confirm Sluvo browser requests keep using `Authorization: Bearer <shenlu_token>` and do not use OpenClaw API-key endpoints as the main app API.

## 2026-04-29

Changed files:
- `apps/sluvo-web/src/views/HomeView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Changed the logged-in homepage recent projects section to a mock empty state.
- Removed mock recent project cards from the homepage and kept a single new-project placeholder entry.
- Added a logout action to the logged-in homepage topbar.
- Refined logged-out homepage copy into a more premium, mysterious Agent-canvas positioning while keeping the infinite canvas workflow clear.
- Replaced the previous logged-in showcase cards with a Sluvo-specific Agent capability panel.
- Enhanced the logged-out homepage visual preview with an Agent Router core and role-specific Agent capability nodes.
- Removed secondary brand subtitles from the Sluvo logo lockups and rearranged the logged-out Agent nodes into a more spacious orbital layout.
- Removed the center Agent Canvas card from the logged-out preview and refined the hero copy spacing for a cleaner premium layout.

Verification suggestions:
- Run `npm run build`.
- Set `localStorage.shenlu_token`, refresh `/`, and verify the recent projects section only shows the new-project placeholder.
- Click logout from the logged-in homepage and verify it returns to the logged-out homepage.

## 2026-04-28

Changed files:
- `apps/sluvo-web/src/api/authApi.js`
- `apps/sluvo-web/src/views/HomeView.vue`
- `apps/sluvo-web/src/views/LoginView.vue`
- `apps/sluvo-web/src/router/index.js`
- `apps/sluvo-web/src/styles/base.css`
- `apps/sluvo-web/src/styles/theme.css`
- `doc/API_DEVELOPMENT.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added a dual-state Sluvo homepage at `/` and `/projects`.
- Added a black/gold logged-out brand entry and a logged-in creation workbench using existing mock project summaries.
- Replaced the temporary login placeholder with a black/gold email/password login surface backed by the existing `/api/auth/login` endpoint.
- Restored direct canvas routing at `/projects/:projectId/canvas`.
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

Changed files:
- `apps/sluvo-web/src/views/LoginView.vue`
- `apps/sluvo-web/src/views/HomeView.vue`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added responsive layout rules across login, logged-out home, logged-in workbench, and canvas workspace surfaces.
- Replaced several fixed column and fixed-width assumptions with shrinking grid tracks, auto-fit cards, wrapped controls, and compact canvas node sizing.
- Improved narrow-screen canvas behavior for the top bar, tool rail, starter strip, bottom controls, minimap, side panels, history panel, library picker, and direct workflow nodes.

Verification suggestions:
- Run `npm run build`.
- Resize the browser across desktop, tablet, and phone widths and verify the login form, home/workbench grids, and canvas controls remain usable without horizontal overflow.

Changed files:
- `apps/sluvo-web/src/views/LoginView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added a development-only login bypass button on the Sluvo login page so local UI testing can reach the protected canvas route when the real backend login is unavailable.
- The bypass writes the existing Shenlu auth storage keys locally and redirects to the requested route; it is gated by `import.meta.env.DEV`.

Verification suggestions:
- Run `npm run build`.
- In Vite dev mode, open `/login` and use "本地开发模式进入画布" to reach `/projects/proj-aurora/canvas` or the redirect target.

Changed files:
- `backend/routers/sluvo.py`
- `backend/services/sluvo_service.py`
- `backend/tests/test_sluvo_service.py`
- `apps/sluvo-web/src/api/sluvoApi.js`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/API_DEVELOPMENT.md`
- `doc/UI_REQUIREMENTS.md`
- `doc/FRONTEND_ARCHITECTURE.md`
- `doc/BACKEND_CONTRACTS.md`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Upgraded Canvas Agent into an Agent Team control surface with project-local session history, custom Agent template creation/edit/delete, starter-template copying, and richer proposal previews.
- Made Agent nodes runnable canvas units that read connected upstream nodes, create target-node Agent sessions, keep proposals approval-gated, and persist the node's recent action state.
- Added `GET /api/sluvo/projects/{project_id}/agent/sessions` and made custom Agent templates participate in backend routing/prompt context.

Verification suggestions:
- Run `npm run build`.
- Run `python3 -m py_compile backend/services/sluvo_service.py backend/routers/sluvo.py`.
- Run `python3 -m pytest backend/tests/test_sluvo_service.py -q` in an environment with pytest installed.
- On the canvas, create a custom Agent, select it in the 创作总监 panel, run a proposal, cancel it, then run and approve another proposal.
- Add an Agent node, connect a text/image node upstream, run the Agent node, and verify the proposal context and node recent status update.

Changed files:
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Moved the canvas bottom control cluster from the lower-left corner to bottom center.
- Kept the control cluster width constrained on narrow screens so it remains centered without overflowing.

Verification suggestions:
- Run `npm run build`.
- Open the canvas and verify the zoom/grid/minimap controls sit centered along the bottom edge at desktop and narrow widths.

Changed files:
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Moved the canvas minimap to align above the bottom-centered canvas control cluster.
- Kept the minimap centered and width-constrained across tablet and phone breakpoints.

Verification suggestions:
- Run `npm run build`.
- Toggle the minimap on the canvas and verify it appears centered above the bottom controls on desktop and narrow screens.

Changed files:
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Made the canvas top-right command/account cluster responsive with smaller controls, horizontal overflow handling, and wrapping at constrained widths.
- Compacted the account dropdown panel with responsive width, max-height scrolling, smaller cards, and mobile fixed positioning.
- Preserved access to the account menu on narrow screens instead of hiding the entire right control cluster.

Verification suggestions:
- Run `npm run build`.
- Open the canvas, resize the viewport from desktop to phone widths, and verify the top-right controls and account dropdown remain usable without covering the canvas excessively.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Direct canvas edges now anchor to the actual visible plus-port centers by reading each port element's DOM rectangle and converting it into flow coordinates.
- This keeps connections aligned for generated/uploaded images with unusual aspect ratios such as 9:16.
- When a direct connection is released into empty space and opens the reference-node menu, the draft line remains visible from the source port to the release point until the menu is closed or a node is selected.

Verification suggestions:
- Run `npm run build`.
- Connect from a tall uploaded/generated image node to another node and confirm the line starts at the plus center.
- Drag a connection into empty space and confirm the draft line stays visible while the reference menu is open.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Anchored the direct-reference creation menu to the canvas flow coordinate where the connection was released.
- The menu now recalculates its screen position when the canvas viewport pans or zooms, keeping it aligned with the retained draft edge instead of drifting away.

Verification suggestions:
- Run `npm run build`.
- Drag a direct connection into empty space, leave the reference menu open, then pan/zoom the canvas and confirm the menu stays attached to the same canvas release point.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `backend/services/sluvo_service.py`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Reworked the Sluvo Agent Team flow around a staged handoff model: official agents now appear as a fixed, readable sequence of creation stages instead of a generic card pile.
- Added per-stage custom Agent assignment so user-created agents can replace official roles while still collaborating inside the same run.
- Enriched run summaries with workflow specs, resolved team membership, stage labels, handoff copy, and artifact definitions for recovery and clearer UI display.
- Fixed the waiting-cost badge count to read the active run status correctly.

Verification suggestions:
- Run `python3 -m py_compile backend/services/sluvo_service.py`.
- Run `npm run build --workspace sluvo-web`.
- Create or copy a custom Agent, assign it to one official stage, start a run, and verify the timeline shows that custom Agent participating in the team handoff.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Reworked the right-side Agent panel into a cleaner task conversation: the default view now emphasizes the current goal, stage progress, and Agent handoff messages.
- Moved official team configuration and per-stage custom Agent replacement into the team settings area so the conversation stays readable by default.
- Replaced dense timeline cards with compact Agent message bubbles, status chips, artifact chips, handoff hints, and inline retry for failed stages.

Verification suggestions:
- Run `npm run build --workspace sluvo-web`.
- Start an Agent run from the canvas and confirm the panel reads as a staged conversation with team settings collapsed by default.

Changed files:
- `backend/services/sluvo_service.py`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Changed Agent runs from one-shot full workflow generation to staged handoff execution: a new run now creates only the first Agent step and waits for user confirmation before appending the next step.
- The continue action advances the next official/custom Agent in the configured team, writes that stage's artifacts to the canvas, then waits again; media placeholders only appear at the final production stage.
- Added an explicit "继续下一步" panel action for waiting runs, while typed feedback still travels with the next stage as user context.
- Media cost confirmation now completes the run after generation records are queued instead of leaving the run in a generic running state.

Verification suggestions:
- Run `python3 -m py_compile backend/services/sluvo_service.py`.
- Run `npm run build --workspace sluvo-web`.
- Start a run and verify only stage 1 appears; click "继续下一步" repeatedly and verify each stage is appended one at a time until media confirmation.

Changed files:
- `backend/services/sluvo_service.py`
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Added Agent input intent routing: ordinary questions now produce a direct read-only answer and do not create canvas nodes or start the creative workflow.
- Creative inspiration now starts by expanding the idea into a script draft, while script-like input is treated as source script material for the downstream team.
- Downstream extraction now includes props alongside characters and scenes, so the workflow follows script -> characters/scenes/props -> storyboard -> prompts -> production placeholders.
- Sending a new prompt after a completed answer now starts a fresh run instead of appending to the prior answered run.

Verification suggestions:
- Run `python3 -m py_compile backend/services/sluvo_service.py`.
- Run `npm run build --workspace sluvo-web`.
- Enter `你是谁` and verify the panel answers directly without writing canvas nodes; then enter a creative idea and verify it starts with a script draft.

Changed files:
- `apps/sluvo-web/src/views/CanvasWorkspaceView.vue`
- `apps/sluvo-web/src/styles/base.css`
- `doc/CHANGELOG_DEV.md`

Impact scope:
- Tightened the Agent panel into a chat-first layout: the current task card is gone, the user prompt appears as a right-aligned message, and Agent steps read as the main conversation.
- Team/history controls now sit in a slim toolbar, and quick creative starters only appear before a run starts.
- Read-only answer artifacts are rendered as message text instead of redundant artifact chips, making ordinary Q&A feel like direct chat.

Verification suggestions:
- Run `npm run build --workspace sluvo-web`.
- Ask `你是谁` and verify the panel shows a user bubble plus a concise Agent answer, with no canvas-write chips or workflow clutter.

