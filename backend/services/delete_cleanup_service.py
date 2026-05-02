from __future__ import annotations

from sqlmodel import Session, select

from models import (
    AssistantPendingQuestion,
    AssistantSession,
    AssistantTranscriptEvent,
    CanvasEdge,
    CanvasNode,
    CanvasWorkspace,
    CreativeEditingDraft,
    DirectorAgentMessage,
    DirectorAgentSession,
    DomainEvent,
    Episode,
    EpisodeAssetLink,
    EpisodeWorkflowState,
    ExternalAgentFileMapping,
    ExternalAgentMessage,
    ExternalAgentSession,
    ExtraImage,
    GenerationRecord,
    GenerationUnit,
    GenerationUnitInput,
    MediaAsset,
    Panel,
    PanelGridCell,
    PanelRevision,
    ScriptWorkflowState,
    SharedResource,
    SharedResourceVersion,
    StoryboardShotAssetLink,
    TaskJob,
)


def _delete_assistant_sessions_by_ids(session: Session, session_ids: list[int]) -> None:
    if not session_ids:
        return

    pending_questions = session.exec(
        select(AssistantPendingQuestion).where(AssistantPendingQuestion.session_id.in_(session_ids))
    ).all()
    for item in pending_questions:
        session.delete(item)

    transcript_events = session.exec(
        select(AssistantTranscriptEvent).where(AssistantTranscriptEvent.session_id.in_(session_ids))
    ).all()
    for item in transcript_events:
        session.delete(item)

    assistant_sessions = session.exec(select(AssistantSession).where(AssistantSession.id.in_(session_ids))).all()
    for item in assistant_sessions:
        session.delete(item)


def _delete_director_sessions_by_ids(session: Session, session_ids: list[int]) -> None:
    if not session_ids:
        return

    messages = session.exec(select(DirectorAgentMessage).where(DirectorAgentMessage.session_id.in_(session_ids))).all()
    for item in messages:
        session.delete(item)

    director_sessions = session.exec(select(DirectorAgentSession).where(DirectorAgentSession.id.in_(session_ids))).all()
    for item in director_sessions:
        session.delete(item)


def _delete_external_sessions_by_ids(session: Session, session_ids: list[int]) -> None:
    if not session_ids:
        return

    messages = session.exec(select(ExternalAgentMessage).where(ExternalAgentMessage.session_ref_id.in_(session_ids))).all()
    for item in messages:
        session.delete(item)

    file_mappings = session.exec(
        select(ExternalAgentFileMapping).where(ExternalAgentFileMapping.session_ref_id.in_(session_ids))
    ).all()
    for item in file_mappings:
        session.delete(item)

    external_sessions = session.exec(select(ExternalAgentSession).where(ExternalAgentSession.id.in_(session_ids))).all()
    for item in external_sessions:
        session.delete(item)


def cleanup_episode_dependencies(session: Session, episode_id: int) -> None:
    panel_ids = [
        item.id
        for item in session.exec(select(Panel).where(Panel.episode_id == episode_id)).all()
        if item.id is not None
    ]

    storyboard_asset_links = session.exec(
        select(StoryboardShotAssetLink).where(StoryboardShotAssetLink.episode_id == episode_id)
    ).all()
    for item in storyboard_asset_links:
        session.delete(item)

    episode_asset_links = session.exec(
        select(EpisodeAssetLink).where(EpisodeAssetLink.episode_id == episode_id)
    ).all()
    for item in episode_asset_links:
        session.delete(item)

    generation_units = session.exec(
        select(GenerationUnit).where(GenerationUnit.episode_id == episode_id)
    ).all()
    generation_unit_ids = [item.id for item in generation_units if item.id is not None]
    generation_unit_inputs_by_target = (
        session.exec(select(GenerationUnitInput).where(GenerationUnitInput.target_unit_id.in_(generation_unit_ids))).all()
        if generation_unit_ids
        else []
    )
    generation_unit_inputs_by_source = (
        session.exec(select(GenerationUnitInput).where(GenerationUnitInput.source_unit_id.in_(generation_unit_ids))).all()
        if generation_unit_ids
        else []
    )
    media_ids = {item.current_media_id for item in generation_units if item.current_media_id is not None}
    for item in {row.id: row for row in generation_unit_inputs_by_target + generation_unit_inputs_by_source if row.id is not None}.values():
        if item.source_media_id is not None:
            media_ids.add(item.source_media_id)
        session.delete(item)

    for item in generation_units:
        session.delete(item)

    task_jobs = session.exec(
        select(TaskJob).where(TaskJob.episode_id == episode_id)
    ).all()
    for item in task_jobs:
        session.delete(item)

    generation_records = session.exec(
        select(GenerationRecord).where(GenerationRecord.episode_id == episode_id)
    ).all()
    generation_record_ids = [item.id for item in generation_records if item.id is not None]
    media_assets_by_record = (
        session.exec(select(MediaAsset).where(MediaAsset.source_record_id.in_(generation_record_ids))).all()
        if generation_record_ids
        else []
    )
    media_assets_by_id = (
        session.exec(select(MediaAsset).where(MediaAsset.id.in_(media_ids))).all()
        if media_ids
        else []
    )
    for item in {row.id: row for row in media_assets_by_record + media_assets_by_id if row.id is not None}.values():
        session.delete(item)

    if panel_ids:
        panel_grid_cells = session.exec(select(PanelGridCell).where(PanelGridCell.panel_id.in_(panel_ids))).all()
        for item in panel_grid_cells:
            session.delete(item)

        panel_revisions = session.exec(select(PanelRevision).where(PanelRevision.panel_id.in_(panel_ids))).all()
        for item in panel_revisions:
            session.delete(item)

        panels = session.exec(select(Panel).where(Panel.id.in_(panel_ids))).all()
        for item in panels:
            session.delete(item)

    episode_workflow_states = session.exec(
        select(EpisodeWorkflowState).where(EpisodeWorkflowState.episode_id == episode_id)
    ).all()
    for item in episode_workflow_states:
        session.delete(item)

    assistant_session_ids = [
        item.id
        for item in session.exec(select(AssistantSession).where(AssistantSession.episode_id == episode_id)).all()
        if item.id is not None
    ]
    _delete_assistant_sessions_by_ids(session, assistant_session_ids)

    director_session_ids = [
        item.id
        for item in session.exec(select(DirectorAgentSession).where(DirectorAgentSession.episode_id == episode_id)).all()
        if item.id is not None
    ]
    _delete_director_sessions_by_ids(session, director_session_ids)

    # Preserve external bridge conversations at script scope while removing the episode binding.
    external_sessions = session.exec(
        select(ExternalAgentSession).where(ExternalAgentSession.episode_id == episode_id)
    ).all()
    for item in external_sessions:
        item.episode_id = None
        session.add(item)

    for item in generation_records:
        session.delete(item)

    editing_drafts = session.exec(
        select(CreativeEditingDraft).where(CreativeEditingDraft.episode_id == episode_id)
    ).all()
    for item in editing_drafts:
        session.delete(item)

    extra_images = session.exec(select(ExtraImage).where(ExtraImage.episode_id == episode_id)).all()
    for item in extra_images:
        session.delete(item)


def cleanup_script_dependencies(session: Session, script_id: int) -> None:
    episode_ids = [
        item.id
        for item in session.exec(select(Episode).where(Episode.script_id == script_id)).all()
        if item.id is not None
    ]
    panel_ids = (
        [
            item.id
            for item in session.exec(select(Panel).where(Panel.episode_id.in_(episode_ids))).all()
            if item.id is not None
        ]
        if episode_ids
        else []
    )

    storyboard_asset_links = session.exec(
        select(StoryboardShotAssetLink).where(StoryboardShotAssetLink.script_id == script_id)
    ).all()
    for item in storyboard_asset_links:
        session.delete(item)

    episode_asset_links = session.exec(
        select(EpisodeAssetLink).where(EpisodeAssetLink.script_id == script_id)
    ).all()
    for item in episode_asset_links:
        session.delete(item)

    generation_unit_inputs = session.exec(
        select(GenerationUnitInput).where(GenerationUnitInput.script_id == script_id)
    ).all()
    for item in generation_unit_inputs:
        session.delete(item)

    generation_units = session.exec(
        select(GenerationUnit).where(GenerationUnit.script_id == script_id)
    ).all()
    for item in generation_units:
        session.delete(item)

    task_jobs_by_script = session.exec(
        select(TaskJob).where(TaskJob.script_id == script_id)
    ).all()
    task_jobs_by_episode = (
        session.exec(select(TaskJob).where(TaskJob.episode_id.in_(episode_ids))).all()
        if episode_ids
        else []
    )
    for item in {row.id: row for row in task_jobs_by_script + task_jobs_by_episode if row.id is not None}.values():
        session.delete(item)

    media_assets = session.exec(
        select(MediaAsset).where(MediaAsset.script_id == script_id)
    ).all()
    for item in media_assets:
        session.delete(item)

    if panel_ids:
        panel_grid_cells = session.exec(select(PanelGridCell).where(PanelGridCell.panel_id.in_(panel_ids))).all()
        for item in panel_grid_cells:
            session.delete(item)

        panel_revisions = session.exec(select(PanelRevision).where(PanelRevision.panel_id.in_(panel_ids))).all()
        for item in panel_revisions:
            session.delete(item)

        panels = session.exec(select(Panel).where(Panel.id.in_(panel_ids))).all()
        for item in panels:
            session.delete(item)

    script_workflow_states = session.exec(
        select(ScriptWorkflowState).where(ScriptWorkflowState.script_id == script_id)
    ).all()
    for item in script_workflow_states:
        session.delete(item)

    if episode_ids:
        episode_workflow_states = session.exec(
            select(EpisodeWorkflowState).where(EpisodeWorkflowState.episode_id.in_(episode_ids))
        ).all()
        for item in episode_workflow_states:
            session.delete(item)

    assistant_session_ids = [
        item.id
        for item in session.exec(select(AssistantSession).where(AssistantSession.script_id == script_id)).all()
        if item.id is not None
    ]
    _delete_assistant_sessions_by_ids(session, assistant_session_ids)

    director_session_ids = [
        item.id
        for item in session.exec(select(DirectorAgentSession).where(DirectorAgentSession.script_id == script_id)).all()
        if item.id is not None
    ]
    _delete_director_sessions_by_ids(session, director_session_ids)

    external_session_ids = [
        item.id
        for item in session.exec(select(ExternalAgentSession).where(ExternalAgentSession.script_id == script_id)).all()
        if item.id is not None
    ]
    _delete_external_sessions_by_ids(session, external_session_ids)

    generation_records_by_script = session.exec(
        select(GenerationRecord).where(GenerationRecord.script_id == script_id)
    ).all()
    generation_records_by_episode = (
        session.exec(select(GenerationRecord).where(GenerationRecord.episode_id.in_(episode_ids))).all()
        if episode_ids
        else []
    )
    for item in {row.id: row for row in generation_records_by_script + generation_records_by_episode}.values():
        session.delete(item)

    editing_drafts_by_script = session.exec(
        select(CreativeEditingDraft).where(CreativeEditingDraft.script_id == script_id)
    ).all()
    editing_drafts_by_episode = (
        session.exec(select(CreativeEditingDraft).where(CreativeEditingDraft.episode_id.in_(episode_ids))).all()
        if episode_ids
        else []
    )
    for item in {row.id: row for row in editing_drafts_by_script + editing_drafts_by_episode}.values():
        session.delete(item)

    if episode_ids:
        extra_images = session.exec(select(ExtraImage).where(ExtraImage.episode_id.in_(episode_ids))).all()
        for item in extra_images:
            session.delete(item)

    shared_resources = session.exec(
        select(SharedResource).where(SharedResource.script_id == script_id)
    ).all()
    shared_resource_ids = [item.id for item in shared_resources if item.id is not None]
    if shared_resource_ids:
        resource_versions = session.exec(
            select(SharedResourceVersion).where(SharedResourceVersion.resource_id.in_(shared_resource_ids))
        ).all()
        for item in resource_versions:
            session.delete(item)
    for item in shared_resources:
        session.delete(item)

    workspace_ids = [
        item.id
        for item in session.exec(select(CanvasWorkspace).where(CanvasWorkspace.script_id == script_id)).all()
        if item.id is not None
    ]
    if workspace_ids:
        canvas_edges = session.exec(select(CanvasEdge).where(CanvasEdge.workspace_id.in_(workspace_ids))).all()
        for item in canvas_edges:
            session.delete(item)

        canvas_nodes = session.exec(select(CanvasNode).where(CanvasNode.workspace_id.in_(workspace_ids))).all()
        for item in canvas_nodes:
            session.delete(item)

        workspaces = session.exec(select(CanvasWorkspace).where(CanvasWorkspace.id.in_(workspace_ids))).all()
        for item in workspaces:
            session.delete(item)

    domain_events = session.exec(select(DomainEvent).where(DomainEvent.script_id == script_id)).all()
    for item in domain_events:
        session.delete(item)
