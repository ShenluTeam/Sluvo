# Sluvo UI Requirements

Version: 0.1
Date: 2026-04-24

## 1. Product Feel

Sluvo should feel like a focused AI production workspace, not a marketing page.

The first screen after login should be a useful project or canvas experience, not a landing hero.

The root homepage has two states:
- Logged out: a black/gold brand entry for Sluvo as the infinite-canvas creation workspace under Shenlu Video AI.
- Logged in: an OiiOii-style creation workbench with a central command input, quick skill actions, recent projects, and showcase templates.

The logged-in homepage should still behave like a tool surface, not a traditional marketing landing page.

The logged-in homepage must expose a clear logout action near the account controls.

Design tone:
- Clear
- Fast
- Creator-oriented
- Dense enough for repeated production work
- Visually polished without decorative clutter

## 2. Core Layout

The main canvas workspace should contain:

- Top command bar for project switch, run actions, save status, and account controls.
- Left rail or drawer for project files, templates, and asset library.
- Full-bleed canvas area for nodes and edges.
- Right inspector for selected node details.
- Bottom or side task drawer for generation queue and history.

Avoid putting the whole canvas inside a decorative card.

## 3. Canvas Interaction

MVP canvas interactions:

- Pan
- Zoom
- Fit view
- Select node
- Multi-select when practical
- Drag node
- Resize node when practical
- Connect compatible ports
- Hide / restore node projection
- Open inspector from node click
- Run node action from node or inspector
- Upload image, video, and audio files into a canvas asset node with instant preview and visible upload state

Canvas layout must be stable: hover states, badges, task indicators, and loading states should not cause node size jumps.

## 4. Node Types

Initial node types:

- Project root
- Script / episode
- Asset table
- Storyboard table
- Image generation unit
- Video generation unit
- Prompt note
- Media board

Each node should show:

- Clear title
- Type indicator
- Primary status
- Most important content preview
- Available primary action
- Output or task state when relevant

## 5. Inspector Rules

The right inspector owns detailed editing.

Do not overload nodes with every field. Nodes should stay scannable; inspector panels can be denser.

Inspector should expose:

- Source fields
- Prompt fields
- Model settings
- References
- Versions / history
- Task status
- Error details

## 6. Task And Error States

Every async action should show a visible state:

- Idle
- Queued
- Running
- Waiting upstream
- Succeeded
- Failed
- Cancelled, if backend supports it

Failed tasks should show:

- Human-readable reason
- Retry action when safe
- Link or action to inspect inputs

Upload failures should keep the upload node visible, avoid saving temporary `blob:` URLs as permanent media, and offer a retry action while the original file is still available in the browser session.

Upload capacity errors should use user-facing copy that explains the storage limit. The initial Sluvo quota is `5GB` per user through the shared Shenlu storage accounting system.

## 7. Copywriting

Use creator-facing language.

Prefer:
- Project
- Script
- Character
- Scene
- Prop
- Shot
- Reference
- Generate
- Render
- Version

Avoid exposing backend terms in the UI unless needed for debugging:
- `Panel`
- `TaskJob`
- `GenerationRecord`
- `CanvasNode`
- `CanvasEdge`
- raw provider names unless the user is choosing a model


Design tone:
- Clear
- Fast
- Creator-oriented
- Dense enough for repeated production work
- Visually polished without decorative clutter

## 2. Core Layout

The main canvas workspace should contain:

- Top command bar for project switch, run actions, save status, and account controls.
- Left rail or drawer for project files, templates, and asset library.
- Full-bleed canvas area for nodes and edges.
- Right inspector for selected node details.
- Bottom or side task drawer for generation queue and history.

Avoid putting the whole canvas inside a decorative card.

## 3. Canvas Interaction

MVP canvas interactions:

- Pan
- Zoom
- Fit view
- Select node
- Multi-select when practical
- Drag node
- Resize node when practical
- Connect compatible ports
- Hide / restore node projection
- Open inspector from node click
- Run node action from node or inspector

Canvas layout must be stable: hover states, badges, task indicators, and loading states should not cause node size jumps.

## 4. Node Types

Initial node types:

- Project root
- Script / episode
- Asset table
- Storyboard table
- Image generation unit
- Video generation unit
- Prompt note
- Media board

Each node should show:

- Clear title
- Type indicator
- Primary status
- Most important content preview
- Available primary action
- Output or task state when relevant

## 5. Inspector Rules

The right inspector owns detailed editing.

Do not overload nodes with every field. Nodes should stay scannable; inspector panels can be denser.

Inspector should expose:

- Source fields
- Prompt fields
- Model settings
- References
- Versions / history
- Task status
- Error details

## 6. Task And Error States

Every async action should show a visible state:

- Idle
- Queued
- Running
- Waiting upstream
- Succeeded
- Failed
- Cancelled, if backend supports it

Failed tasks should show:

- Human-readable reason
- Retry action when safe
- Link or action to inspect inputs

## 7. Copywriting

Use creator-facing language.

Prefer:
- Project
- Script
- Character
- Scene
- Prop
- Shot
- Reference
- Generate
- Render
- Version

Avoid exposing backend terms in the UI unless needed for debugging:
- `Panel`
- `TaskJob`
- `GenerationRecord`
- `CanvasNode`
- `CanvasEdge`
- raw provider names unless the user is choosing a model

## 8. Visual Rules

- The homepage uses the Sluvo black/gold palette: `#050505`, `#0d0b07`, `#d6b56d`, and `#fff1c7`.
- The logged-out homepage should position Sluvo as an AI Agent driven infinite canvas where Agents understand context, connect nodes, and advance creative workflow execution.
- Homepage creation controls should feel actionable: prompt input, upload/script/character/storyboard actions, recent projects, and canvas entry points must look like real workspace affordances.
- The logged-in homepage should use visual media to communicate creative output: a central prompt composer may be surrounded by low-emphasis floating image/video cards, followed by an inspiration sample strip and visual project covers.
- Homepage sample videos must be muted, inline, and lightweight. Use poster images and hover/focus playback where practical; failed video loads should still leave an image or gradient fallback.
- Remote homepage media should use stable official or owned URLs when available. Do not commit large binary showcase assets to the repository for the first homepage visual pass.
- Keep cards at `8px` border radius or less unless a future design system changes this.
- Use icons for common commands where appropriate.
- Avoid oversized hero typography inside tool surfaces.
- Avoid one-color palettes; Sluvo should not become only purple, only blue, or only beige.
- Text must fit inside buttons, nodes, badges, and panels across desktop widths.
- Do not use decorative blobs or orbs as backgrounds.

## 9. Mobile Scope

MVP is desktop-first.

Mobile should:
- Open without broken layout.
- Allow project browsing and result review if practical.
- Not be treated as the primary creation surface until explicitly planned.

## 10. Accessibility

Baseline requirements:

- Keyboard focus visible.
- Buttons have accessible labels.
- Color is not the only status signal.
- Important status changes are text-visible.
- Canvas controls have tooltips or labels.
