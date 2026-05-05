from sqlalchemy import text
import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.engine.url import make_url
from sqlmodel import SQLModel, Session, create_engine

from core.config import settings

logger = logging.getLogger(__name__)


def _build_engine_kwargs() -> dict:
    url = make_url(settings.DATABASE_URL)
    if url.get_backend_name() == "sqlite":
        return {}
    return {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_pre_ping": settings.DB_POOL_PRE_PING,
    }


engine = create_engine(settings.DATABASE_URL, **_build_engine_kwargs())


def get_pool_status() -> str:
    status = getattr(engine.pool, "status", None)
    if not callable(status):
        return str(engine.pool)
    try:
        return status()
    except Exception as exc:
        return f"pool status unavailable: {exc}"


def log_pool_status(context: str) -> None:
    if settings.DB_POOL_LOG_STATUS:
        logger.info("database pool status [%s]: %s", context, get_pool_status())


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def _is_duplicate_column_error(err: Exception) -> bool:
    msg = str(err).lower()
    return (
        "duplicate column" in msg
        or "already exists" in msg
        or "duplicate key name" in msg
        or "index already exists" in msg
    )


def _ensure_lightweight_columns() -> None:
    statements = [
        "ALTER TABLE script ADD COLUMN source_text LONGTEXT",
        "ALTER TABLE script ADD COLUMN openclaw_settings_json LONGTEXT",
        "ALTER TABLE script ADD COLUMN workflow_settings_json LONGTEXT",
        "ALTER TABLE script ADD COLUMN updated_at DATETIME",
        "ALTER TABLE episode ADD COLUMN source_text LONGTEXT",
        "ALTER TABLE episode ADD COLUMN storyboard_mode VARCHAR(32) NOT NULL DEFAULT 'commentary'",
        "ALTER TABLE episode ADD COLUMN workflow_override_json LONGTEXT",
        "ALTER TABLE episode ADD COLUMN composed_video_url LONGTEXT",
        "ALTER TABLE episode ADD COLUMN composed_video_thumbnail_url LONGTEXT",
        "ALTER TABLE episode ADD COLUMN composed_video_updated_at DATETIME NULL",
        "ALTER TABLE episode ADD COLUMN updated_at DATETIME",
        "ALTER TABLE script ADD COLUMN last_accessed_at DATETIME NULL",
        "ALTER TABLE teammemberlink ADD COLUMN point_quota INT NULL",
        "ALTER TABLE teammemberlink ADD COLUMN point_quota_used INT NOT NULL DEFAULT 0",
        "ALTER TABLE panel ADD COLUMN prop VARCHAR(255)",
        "ALTER TABLE panel ADD COLUMN nine_grid_prompt LONGTEXT",
        "ALTER TABLE panel ADD COLUMN entity_bindings_json LONGTEXT",
        "ALTER TABLE panel ADD COLUMN current_revision_id INT NULL",
        "ALTER TABLE panel ADD COLUMN panel_type VARCHAR(32)",
        "ALTER TABLE panel ADD COLUMN storyboard_mode VARCHAR(32) NOT NULL DEFAULT 'commentary'",
        "ALTER TABLE panel ADD COLUMN title VARCHAR(255)",
        "ALTER TABLE panel ADD COLUMN text_span_json LONGTEXT",
        "ALTER TABLE panel ADD COLUMN recommended_duration_seconds INT NOT NULL DEFAULT 6",
        "ALTER TABLE panel ADD COLUMN grid_count INT NOT NULL DEFAULT 1",
        "ALTER TABLE panel ADD COLUMN pacing VARCHAR(32)",
        "ALTER TABLE panel ADD COLUMN rhythm LONGTEXT",
        "ALTER TABLE panel ADD COLUMN continuity_note LONGTEXT",
        "ALTER TABLE panel ADD COLUMN scene_prompt LONGTEXT",
        "ALTER TABLE panel ADD COLUMN multi_shot_prompt LONGTEXT",
        "ALTER TABLE panel ADD COLUMN multi_shot_video_prompt LONGTEXT",
        "ALTER TABLE panel ADD COLUMN reference_assets_json LONGTEXT",
        "ALTER TABLE panel ADD COLUMN reference_images_json LONGTEXT",
        "ALTER TABLE panel ADD COLUMN auto_asset_reference_enabled BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE panel ADD COLUMN video_thumbnail_url LONGTEXT",
        "ALTER TABLE panel ADD COLUMN segment_no INT NULL",
        "ALTER TABLE panel ADD COLUMN segment_summary LONGTEXT",
        "ALTER TABLE panel ADD COLUMN narrative_purpose LONGTEXT",
        "ALTER TABLE panel ADD COLUMN panel_type_reason LONGTEXT",
        "ALTER TABLE panel ADD COLUMN segment_prompt_summary LONGTEXT",
        "ALTER TABLE panel ADD COLUMN narration_text LONGTEXT",
        "ALTER TABLE panel ADD COLUMN dialogue_text LONGTEXT",
        "ALTER TABLE panel ADD COLUMN segment_break BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE panel ADD COLUMN dependency_panel_id INT NULL",
        "ALTER TABLE panel ADD COLUMN shot_type VARCHAR(64)",
        "ALTER TABLE panel ADD COLUMN camera_motion VARCHAR(64)",
        "ALTER TABLE panel ADD COLUMN composition LONGTEXT",
        "ALTER TABLE panel ADD COLUMN previous_storyboard_path VARCHAR(512)",
        "ALTER TABLE panel ADD COLUMN transition_to_next VARCHAR(64)",
        "ALTER TABLE panel ADD COLUMN generation_status VARCHAR(32) NOT NULL DEFAULT 'idle'",
        "ALTER TABLE panel ADD COLUMN note LONGTEXT",
        "ALTER TABLE panel ADD COLUMN updated_at DATETIME",
        "ALTER TABLE panelrevision ADD COLUMN panel_type VARCHAR(32)",
        "ALTER TABLE panelrevision ADD COLUMN storyboard_mode VARCHAR(32) NOT NULL DEFAULT 'commentary'",
        "ALTER TABLE panelrevision ADD COLUMN title VARCHAR(255)",
        "ALTER TABLE panelrevision ADD COLUMN text_span_json LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN recommended_duration_seconds INT NOT NULL DEFAULT 6",
        "ALTER TABLE panelrevision ADD COLUMN grid_count INT NOT NULL DEFAULT 1",
        "ALTER TABLE panelrevision ADD COLUMN pacing VARCHAR(32)",
        "ALTER TABLE panelrevision ADD COLUMN rhythm LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN continuity_note LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN scene_prompt LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN multi_shot_prompt LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN multi_shot_video_prompt LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN reference_assets_json LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN reference_images_json LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN auto_asset_reference_enabled BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE panelrevision ADD COLUMN segment_no INT NULL",
        "ALTER TABLE panelrevision ADD COLUMN segment_summary LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN narrative_purpose LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN panel_type_reason LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN segment_prompt_summary LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN narration_text LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN dialogue_text LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN segment_break BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE panelrevision ADD COLUMN dependency_panel_id INT NULL",
        "ALTER TABLE panelrevision ADD COLUMN shot_type VARCHAR(64)",
        "ALTER TABLE panelrevision ADD COLUMN camera_motion VARCHAR(64)",
        "ALTER TABLE panelrevision ADD COLUMN composition LONGTEXT",
        "ALTER TABLE panelrevision ADD COLUMN previous_storyboard_path VARCHAR(512)",
        "ALTER TABLE panelrevision ADD COLUMN transition_to_next VARCHAR(64)",
        "ALTER TABLE panelrevision ADD COLUMN generation_status VARCHAR(32) NOT NULL DEFAULT 'idle'",
        "ALTER TABLE panelrevision ADD COLUMN note LONGTEXT",
        "ALTER TABLE panelgridcell ADD COLUMN start_second DOUBLE NOT NULL DEFAULT 0",
        "ALTER TABLE panelgridcell ADD COLUMN end_second DOUBLE NOT NULL DEFAULT 0",
        "ALTER TABLE panelgridcell ADD COLUMN duration_seconds DOUBLE NOT NULL DEFAULT 0",
        "ALTER TABLE panelgridcell ADD COLUMN speech_items_json LONGTEXT",
        "ALTER TABLE panelgridcell ADD COLUMN performance_focus LONGTEXT",
        "ALTER TABLE panelgridcell ADD COLUMN mouth_sync_required BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE panelgridcell ADD COLUMN camera_position LONGTEXT",
        "ALTER TABLE panelgridcell ADD COLUMN camera_direction LONGTEXT",
        "ALTER TABLE panelgridcell ADD COLUMN shot_purpose LONGTEXT",
        "ALTER TABLE panelgridcell ADD COLUMN image_prompt_structured_json LONGTEXT",
        "ALTER TABLE panelgridcell ADD COLUMN video_prompt_structured_json LONGTEXT",
        "ALTER TABLE sharedresource ADD COLUMN thumbnail_url VARCHAR(255)",
        "ALTER TABLE sharedresource ADD COLUMN aliases LONGTEXT",
        "ALTER TABLE sharedresource ADD COLUMN storage_object_key VARCHAR(255)",
        "ALTER TABLE sharedresource ADD COLUMN original_filename VARCHAR(255)",
        "ALTER TABLE sharedresource ADD COLUMN mime_type VARCHAR(255)",
        "ALTER TABLE sharedresource ADD COLUMN file_size BIGINT NULL",
        "ALTER TABLE sharedresource ADD COLUMN updated_at DATETIME",
        "ALTER TABLE user ADD COLUMN storage_namespace VARCHAR(64) NULL",
        "CREATE UNIQUE INDEX idx_user_storage_namespace ON user (storage_namespace)",
        "ALTER TABLE externalprovidercredential ADD COLUMN token_masked VARCHAR(255)",
        "ALTER TABLE externalprovidercredential ADD COLUMN token_hash VARCHAR(64)",
        "ALTER TABLE externalprovidercredential ADD COLUMN token_prefix VARCHAR(24)",
        "ALTER TABLE externalprovidercredential ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE externalprovidercredential ADD COLUMN openclaw_api_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE externalprovidercredential ADD COLUMN expires_at DATETIME NULL",
        "ALTER TABLE externalprovidercredential ADD COLUMN created_at DATETIME",
        "ALTER TABLE externalprovidercredential ADD COLUMN updated_at DATETIME",
        "ALTER TABLE externalagentsession ADD COLUMN base_name VARCHAR(255)",
        "ALTER TABLE externalagentsession ADD COLUMN provider_episode_id VARCHAR(255)",
        "ALTER TABLE externalagentsession ADD COLUMN settings_json LONGTEXT",
        "ALTER TABLE externalagentsession ADD COLUMN workspace_snapshot_json LONGTEXT",
        "ALTER TABLE externalagentsession ADD COLUMN last_reply_text LONGTEXT",
        "ALTER TABLE externalagentsession ADD COLUMN status VARCHAR(64)",
        "ALTER TABLE externalagentsession ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE externalagentsession ADD COLUMN last_synced_at DATETIME NULL",
        "ALTER TABLE externalagentsession ADD COLUMN created_at DATETIME",
        "ALTER TABLE externalagentsession ADD COLUMN updated_at DATETIME",
        "ALTER TABLE externalagentmessage ADD COLUMN reply_text LONGTEXT",
        "ALTER TABLE externalagentmessage ADD COLUMN reply_json LONGTEXT",
        "ALTER TABLE externalagentmessage ADD COLUMN actions_json LONGTEXT",
        "ALTER TABLE externalagentmessage ADD COLUMN workspace_snapshot_json LONGTEXT",
        "ALTER TABLE externalagentmessage ADD COLUMN created_at DATETIME",
        "ALTER TABLE externalagentfilemapping ADD COLUMN provider_docu_type VARCHAR(64)",
        "ALTER TABLE externalagentfilemapping ADD COLUMN provider_name VARCHAR(255)",
        "ALTER TABLE externalagentfilemapping ADD COLUMN internal_target_type VARCHAR(64)",
        "ALTER TABLE externalagentfilemapping ADD COLUMN internal_target_id INT NULL",
        "ALTER TABLE externalagentfilemapping ADD COLUMN snapshot_json LONGTEXT",
        "ALTER TABLE externalagentfilemapping ADD COLUMN created_at DATETIME",
        "ALTER TABLE externalagentfilemapping ADD COLUMN updated_at DATETIME",
        "ALTER TABLE voiceasset ADD COLUMN activation_billed_at DATETIME NULL",
        "ALTER TABLE emailverificationcode ADD COLUMN purpose VARCHAR(32) NOT NULL DEFAULT 'register'",
        # 神鹿AI导演相关表
        "CREATE TABLE IF NOT EXISTS director_agent_session (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, episode_id INT NULL, user_id INT NOT NULL, team_id INT NOT NULL, agent_name VARCHAR(64), title VARCHAR(255), context_snapshot_json LONGTEXT, status VARCHAR(32) DEFAULT 'active', created_at DATETIME, updated_at DATETIME)",
        "ALTER TABLE director_agent_session ADD COLUMN last_message_at DATETIME NULL",
        "ALTER TABLE director_agent_session ADD COLUMN last_action_type VARCHAR(64)",
        "CREATE TABLE IF NOT EXISTS director_agent_message (id INT AUTO_INCREMENT PRIMARY KEY, session_id INT NOT NULL, role VARCHAR(16), content LONGTEXT, message_type VARCHAR(32), payload_json LONGTEXT, task_type VARCHAR(64), task_status VARCHAR(32), requires_confirmation BOOLEAN DEFAULT FALSE, confirmation_status VARCHAR(32), confirmed_at DATETIME NULL, confirmed_by_user_id INT NULL, execution_result_json LONGTEXT, agent_name VARCHAR(64), created_at DATETIME)",
        # 统一 Assistant Runtime v2 相关表
        "CREATE TABLE IF NOT EXISTS assistant_session (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, episode_id INT NULL, user_id INT NOT NULL, team_id INT NOT NULL, channel VARCHAR(32) NOT NULL DEFAULT 'internal', profile VARCHAR(64) NOT NULL DEFAULT 'director', status VARCHAR(32) NOT NULL DEFAULT 'idle', title VARCHAR(255), linked_external_session_id INT NULL, metadata_json LONGTEXT, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS assistant_transcript_event (id INT AUTO_INCREMENT PRIMARY KEY, session_id INT NOT NULL, turn_id VARCHAR(64) NULL, role VARCHAR(32) NULL, event_type VARCHAR(32) NOT NULL DEFAULT 'turn', block_type VARCHAR(64) NULL, sequence_no INT NOT NULL DEFAULT 0, payload_json LONGTEXT, created_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS assistant_pending_question (id INT AUTO_INCREMENT PRIMARY KEY, session_id INT NOT NULL, question_key VARCHAR(64) NOT NULL UNIQUE, question_type VARCHAR(32) NOT NULL DEFAULT 'question', status VARCHAR(32) NOT NULL DEFAULT 'pending', title VARCHAR(255) NULL, prompt_text LONGTEXT NULL, payload_json LONGTEXT, answer_json LONGTEXT, created_at DATETIME, updated_at DATETIME, answered_at DATETIME NULL)",
        "CREATE TABLE IF NOT EXISTS script_workflow_state (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, team_id INT NOT NULL, current_stage VARCHAR(64) NOT NULL DEFAULT 'INIT', stage_status VARCHAR(32) NOT NULL DEFAULT 'idle', current_step_key VARCHAR(64) NOT NULL DEFAULT 'demand_understanding', mode VARCHAR(32) NOT NULL DEFAULT 'semi_auto', pause_policy VARCHAR(64) NOT NULL DEFAULT 'stage_boundary_and_cost', pending_confirmation_json LONGTEXT, result_summary_json LONGTEXT, result_detail_json LONGTEXT, quality_assessment_json LONGTEXT, recommended_actions_json LONGTEXT, adjustment_actions_json LONGTEXT, history_versions_json LONGTEXT, last_agent_run_at DATETIME NULL, last_user_decision_at DATETIME NULL, version INT NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS episode_workflow_state (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, episode_id INT NOT NULL, team_id INT NOT NULL, current_stage VARCHAR(64) NOT NULL DEFAULT 'ASSET_EXTRACTION', stage_status VARCHAR(32) NOT NULL DEFAULT 'idle', current_step_key VARCHAR(64) NOT NULL DEFAULT 'asset_extraction', mode VARCHAR(32) NOT NULL DEFAULT 'semi_auto', pause_policy VARCHAR(64) NOT NULL DEFAULT 'stage_boundary_and_cost', pending_confirmation_json LONGTEXT, result_summary_json LONGTEXT, result_detail_json LONGTEXT, quality_assessment_json LONGTEXT, recommended_actions_json LONGTEXT, adjustment_actions_json LONGTEXT, history_versions_json LONGTEXT, last_agent_run_at DATETIME NULL, last_user_decision_at DATETIME NULL, version INT NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS membership_plan (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(64) NOT NULL UNIQUE, name VARCHAR(255) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'active', scope_type VARCHAR(16) NOT NULL DEFAULT 'both', sort_order INT NOT NULL DEFAULT 100, priority_default INT NOT NULL DEFAULT 100, max_storyboard_concurrency INT NULL, max_resource_concurrency INT NULL, max_media_concurrency INT NULL, max_audio_concurrency INT NULL, storage_quota_bytes BIGINT NULL, description LONGTEXT NULL, is_default BOOLEAN NOT NULL DEFAULT FALSE, is_builtin BOOLEAN NOT NULL DEFAULT FALSE, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS user_membership (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, plan_id INT NOT NULL, starts_at DATETIME NULL, expires_at DATETIME NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE, remark LONGTEXT NULL, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS team_membership (id INT AUTO_INCREMENT PRIMARY KEY, team_id INT NOT NULL, plan_id INT NOT NULL, starts_at DATETIME NULL, expires_at DATETIME NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE, remark LONGTEXT NULL, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS user_membership_override (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL UNIQUE, enabled BOOLEAN NOT NULL DEFAULT TRUE, effective_priority INT NULL, max_storyboard_concurrency INT NULL, max_resource_concurrency INT NULL, max_media_concurrency INT NULL, max_audio_concurrency INT NULL, storage_quota_bytes BIGINT NULL, remark LONGTEXT NULL, created_at DATETIME, updated_at DATETIME)",
        "ALTER TABLE membership_plan ADD COLUMN storage_quota_bytes BIGINT NULL",
        "ALTER TABLE user_membership_override ADD COLUMN storage_quota_bytes BIGINT NULL",
        "CREATE TABLE IF NOT EXISTS storage_object (id INT AUTO_INCREMENT PRIMARY KEY, owner_user_id INT NOT NULL, object_key VARCHAR(512) NOT NULL UNIQUE, old_object_key VARCHAR(512) NULL, media_type VARCHAR(32) NOT NULL, file_size BIGINT NOT NULL DEFAULT 0, status VARCHAR(32) NOT NULL DEFAULT 'active', source_type VARCHAR(64) NULL, source_id INT NULL, old_deleted_at DATETIME NULL, created_at DATETIME, updated_at DATETIME)",
        "CREATE INDEX idx_storage_object_owner ON storage_object (owner_user_id)",
        "CREATE INDEX idx_storage_object_old_object_key ON storage_object (old_object_key)",
        "CREATE INDEX idx_storage_object_status ON storage_object (status)",
        "CREATE TABLE IF NOT EXISTS user_storage_usage (user_id INT NOT NULL PRIMARY KEY, used_bytes BIGINT NOT NULL DEFAULT 0, reserved_bytes BIGINT NOT NULL DEFAULT 0, quota_bytes_snapshot BIGINT NULL, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS task_job (id INT AUTO_INCREMENT PRIMARY KEY, task_id VARCHAR(64) NOT NULL UNIQUE, task_type VARCHAR(64) NOT NULL, queue_name VARCHAR(32) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'queued', priority INT NOT NULL DEFAULT 100, provider VARCHAR(64) NULL, team_id INT NULL, user_id INT NULL, script_id INT NULL, episode_id INT NULL, scope_type VARCHAR(64) NULL, scope_id INT NULL, generation_record_id INT NULL, payload_json LONGTEXT, result_json LONGTEXT, progress INT NOT NULL DEFAULT 0, stage VARCHAR(64) NULL, message LONGTEXT NULL, error_code VARCHAR(64) NULL, error_message LONGTEXT NULL, retry_count INT NOT NULL DEFAULT 0, max_retries INT NOT NULL DEFAULT 0, scheduled_at DATETIME NULL, started_at DATETIME NULL, finished_at DATETIME NULL, heartbeat_at DATETIME NULL, lease_expires_at DATETIME NULL, worker_id VARCHAR(128) NULL, cancel_requested_at DATETIME NULL, created_at DATETIME, updated_at DATETIME)",
        "ALTER TABLE task_job ADD COLUMN ownership_mode VARCHAR(32) NULL",
        "ALTER TABLE task_job ADD COLUMN task_category VARCHAR(32) NULL",
        "ALTER TABLE task_job ADD COLUMN membership_source VARCHAR(32) NULL",
        "ALTER TABLE task_job ADD COLUMN membership_plan_id INT NULL",
        "ALTER TABLE task_job ADD COLUMN membership_plan_name VARCHAR(255) NULL",
        "ALTER TABLE task_job ADD COLUMN membership_subject_type VARCHAR(32) NULL",
        "ALTER TABLE task_job ADD COLUMN membership_subject_id INT NULL",
        "ALTER TABLE task_job ADD COLUMN concurrency_limit INT NULL",
        "ALTER TABLE task_job ADD COLUMN actual_cost_cny DOUBLE NULL DEFAULT 0",
        "ALTER TABLE task_job ADD COLUMN charged_points INT NOT NULL DEFAULT 0",
        "ALTER TABLE task_job ADD COLUMN actual_points INT NOT NULL DEFAULT 0",
        "ALTER TABLE task_job ADD COLUMN points_status VARCHAR(32) NULL DEFAULT 'free'",
        "ALTER TABLE task_job ADD COLUMN billing_detail_json LONGTEXT",
        "ALTER TABLE task_job ADD COLUMN callback_token VARCHAR(128) NULL",
        "ALTER TABLE task_job ADD COLUMN next_poll_at DATETIME NULL",
        "ALTER TABLE task_job ADD COLUMN poll_attempts INT NOT NULL DEFAULT 0",
        "ALTER TABLE task_job ADD COLUMN callback_received_at DATETIME NULL",
        # AI native canvas tables
        "CREATE TABLE IF NOT EXISTS canvas_workspace (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, title VARCHAR(255) NOT NULL, description LONGTEXT NULL, viewport_json LONGTEXT, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS canvas_node (id INT AUTO_INCREMENT PRIMARY KEY, workspace_id INT NOT NULL, type VARCHAR(64) NOT NULL, title VARCHAR(255) NOT NULL, position_x DOUBLE, position_y DOUBLE, width DOUBLE NULL, height DOUBLE NULL, status VARCHAR(32) NOT NULL DEFAULT 'idle', source_type VARCHAR(64) NULL, source_id INT NULL, source_sub_id INT NULL, bootstrap_key VARCHAR(255) NULL, sync_status VARCHAR(32) NOT NULL DEFAULT 'clean', snapshot_version VARCHAR(64) NULL, source_version VARCHAR(64) NULL, source_updated_at DATETIME NULL, last_synced_at DATETIME NULL, archived_at DATETIME NULL, data_json LONGTEXT, context_json LONGTEXT, ai_config_json LONGTEXT, meta_json LONGTEXT, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS canvas_edge (id INT AUTO_INCREMENT PRIMARY KEY, workspace_id INT NOT NULL, source_node_id INT NOT NULL, target_node_id INT NOT NULL, edge_type VARCHAR(64) NOT NULL, mapping_json LONGTEXT, label VARCHAR(255) NULL, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS episode_asset_link (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, episode_id INT NOT NULL, resource_id INT NOT NULL, sort_order INT NOT NULL DEFAULT 0, revision INT NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS storyboard_shot_asset_link (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, episode_id INT NOT NULL, panel_id INT NOT NULL, resource_id INT NOT NULL, role VARCHAR(64) NULL, sort_order INT NOT NULL DEFAULT 0, revision INT NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS media_asset (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, media_type VARCHAR(32) NOT NULL, url LONGTEXT NOT NULL, thumbnail_url LONGTEXT NULL, width INT NULL, height INT NULL, duration_seconds DOUBLE NULL, source_record_id INT NULL, metadata_json LONGTEXT, created_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS generation_unit (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, episode_id INT NULL, unit_type VARCHAR(32) NOT NULL, name VARCHAR(255) NOT NULL, owner_type VARCHAR(64) NULL, owner_id INT NULL, prompt LONGTEXT, negative_prompt LONGTEXT NULL, model_id VARCHAR(128) NULL, params_json LONGTEXT, status VARCHAR(32) NOT NULL DEFAULT 'empty', current_media_id INT NULL, generation_record_id INT NULL, versions_json LONGTEXT, revision INT NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS generation_unit_input (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, target_unit_id INT NOT NULL, source_unit_id INT NULL, source_media_id INT NULL, input_type VARCHAR(32) NOT NULL, role VARCHAR(64) NULL, weight DOUBLE NULL, sort_order INT NOT NULL DEFAULT 0, metadata_json LONGTEXT, created_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS domain_event (id INT AUTO_INCREMENT PRIMARY KEY, script_id INT NOT NULL, event_type VARCHAR(128) NOT NULL, entity_type VARCHAR(64) NOT NULL, entity_id INT NOT NULL, payload_json LONGTEXT, created_by_user_id INT NULL, created_at DATETIME)",
        "ALTER TABLE canvas_node ADD COLUMN source_type VARCHAR(64) NULL",
        "ALTER TABLE canvas_node ADD COLUMN source_id INT NULL",
        "ALTER TABLE canvas_node ADD COLUMN source_sub_id INT NULL",
        "ALTER TABLE canvas_node ADD COLUMN bootstrap_key VARCHAR(255) NULL",
        "ALTER TABLE canvas_node ADD COLUMN sync_status VARCHAR(32) NOT NULL DEFAULT 'clean'",
        "ALTER TABLE canvas_node ADD COLUMN snapshot_version VARCHAR(64) NULL",
        "ALTER TABLE canvas_node ADD COLUMN source_version VARCHAR(64) NULL",
        "ALTER TABLE canvas_node ADD COLUMN source_updated_at DATETIME NULL",
        "ALTER TABLE canvas_node ADD COLUMN last_synced_at DATETIME NULL",
        "ALTER TABLE canvas_node ADD COLUMN archived_at DATETIME NULL",
        "ALTER TABLE canvas_node ADD COLUMN domain_type VARCHAR(64) NULL",
        "ALTER TABLE canvas_node ADD COLUMN domain_id INT NULL",
        "ALTER TABLE canvas_node ADD COLUMN parent_node_id INT NULL",
        "ALTER TABLE canvas_node ADD COLUMN collapsed BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE canvas_node ADD COLUMN hidden BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE canvas_node ADD COLUMN locked BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE canvas_node ADD COLUMN revision INT NOT NULL DEFAULT 1",
        "ALTER TABLE canvas_node ADD COLUMN view_data_json LONGTEXT",
        "ALTER TABLE canvas_edge ADD COLUMN source_port_id VARCHAR(255) NULL",
        "ALTER TABLE canvas_edge ADD COLUMN target_port_id VARCHAR(255) NULL",
        "ALTER TABLE canvas_edge ADD COLUMN role VARCHAR(64) NULL",
        "ALTER TABLE canvas_edge ADD COLUMN domain_type VARCHAR(64) NULL",
        "ALTER TABLE canvas_edge ADD COLUMN domain_id INT NULL",
        "ALTER TABLE canvas_edge ADD COLUMN is_projection BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE canvas_edge ADD COLUMN hidden BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE canvas_edge ADD COLUMN view_data_json LONGTEXT",
        "ALTER TABLE temporaryuploadasset ADD COLUMN duration_seconds DOUBLE NULL",
        "ALTER TABLE temporaryuploadasset ADD COLUMN has_audio BOOLEAN NULL",
        "ALTER TABLE temporaryuploadasset ADD COLUMN width INT NULL",
        "ALTER TABLE temporaryuploadasset ADD COLUMN height INT NULL",
        "CREATE INDEX idx_externalprovidercredential_token_hash ON externalprovidercredential (token_hash)",
        "CREATE INDEX idx_externalprovidercredential_token_prefix ON externalprovidercredential (token_prefix)",
        "CREATE UNIQUE INDEX uq_canvas_workspace_script_id ON canvas_workspace (script_id)",
        "CREATE UNIQUE INDEX uq_canvas_node_workspace_bootstrap_key ON canvas_node (workspace_id, bootstrap_key)",
        "CREATE UNIQUE INDEX uq_episode_asset_link_episode_resource ON episode_asset_link (episode_id, resource_id)",
        "CREATE UNIQUE INDEX uq_storyboard_shot_asset_link_panel_resource ON storyboard_shot_asset_link (panel_id, resource_id)",
        "CREATE UNIQUE INDEX uq_script_workflow_state_script_id ON script_workflow_state (script_id)",
        "CREATE UNIQUE INDEX uq_episode_workflow_state_episode_id ON episode_workflow_state (episode_id)",
        "CREATE INDEX idx_script_workflow_state_stage_status ON script_workflow_state (current_stage, stage_status)",
        "CREATE INDEX idx_episode_workflow_state_stage_status ON episode_workflow_state (current_stage, stage_status)",
        "CREATE INDEX idx_canvas_node_sync_status ON canvas_node (sync_status)",
        "CREATE INDEX idx_canvas_node_source_type ON canvas_node (source_type)",
        "CREATE INDEX idx_canvas_node_source_id ON canvas_node (source_id)",
        "CREATE INDEX idx_canvas_node_archived_at ON canvas_node (archived_at)",
        "CREATE INDEX idx_canvas_node_domain_ref ON canvas_node (workspace_id, type, domain_type, domain_id)",
        "CREATE INDEX idx_canvas_node_hidden ON canvas_node (hidden)",
        "CREATE INDEX idx_canvas_edge_projection_lookup ON canvas_edge (workspace_id, edge_type, source_node_id, target_node_id)",
        "CREATE INDEX idx_canvas_edge_ports ON canvas_edge (source_port_id, target_port_id)",
        "CREATE INDEX idx_episode_asset_link_script_episode ON episode_asset_link (script_id, episode_id, sort_order)",
        "CREATE INDEX idx_storyboard_shot_asset_link_script_episode ON storyboard_shot_asset_link (script_id, episode_id, sort_order)",
        "CREATE INDEX idx_generation_unit_script_owner ON generation_unit (script_id, owner_type, owner_id)",
        "CREATE INDEX idx_generation_unit_episode_type ON generation_unit (episode_id, unit_type)",
        "CREATE INDEX idx_generation_unit_input_target ON generation_unit_input (script_id, target_unit_id)",
        "CREATE INDEX idx_media_asset_script_type ON media_asset (script_id, media_type)",
        "CREATE INDEX idx_domain_event_script_entity ON domain_event (script_id, entity_type, entity_id)",
        "CREATE INDEX idx_task_job_status_queue_name ON task_job (status, queue_name)",
        "CREATE INDEX idx_task_job_scope ON task_job (scope_type, scope_id)",
        "CREATE INDEX idx_task_job_generation_record_id ON task_job (generation_record_id)",
        "CREATE INDEX idx_task_job_lease_expires_at ON task_job (lease_expires_at)",
        "CREATE INDEX idx_task_job_priority_created_at ON task_job (queue_name, status, priority, created_at)",
        "CREATE INDEX idx_task_job_membership_subject ON task_job (membership_subject_type, membership_subject_id, task_category, status)",
        "CREATE INDEX idx_task_job_next_poll_at ON task_job (status, next_poll_at, provider)",
        "CREATE INDEX idx_task_job_points_status ON task_job (points_status)",
        # Sluvo standalone canvas product tables
        "CREATE TABLE IF NOT EXISTS sluvo_project (id INT AUTO_INCREMENT PRIMARY KEY, owner_user_id INT NOT NULL, team_id INT NOT NULL, title VARCHAR(255) NOT NULL, description LONGTEXT NULL, status VARCHAR(32) NOT NULL DEFAULT 'active', visibility VARCHAR(32) NOT NULL DEFAULT 'project_members', settings_json LONGTEXT, cover_url LONGTEXT NULL, last_opened_at DATETIME NULL, deleted_at DATETIME NULL, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS sluvo_project_member (id INT AUTO_INCREMENT PRIMARY KEY, project_id INT NOT NULL, user_id INT NOT NULL, role VARCHAR(32) NOT NULL DEFAULT 'viewer', invited_by_user_id INT NULL, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS sluvo_canvas (id INT AUTO_INCREMENT PRIMARY KEY, project_id INT NOT NULL, canvas_key VARCHAR(64) NOT NULL DEFAULT 'main', title VARCHAR(255) NOT NULL DEFAULT 'Main Canvas', viewport_json LONGTEXT, snapshot_json LONGTEXT, schema_version INT NOT NULL DEFAULT 1, revision INT NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS sluvo_canvas_node (id INT AUTO_INCREMENT PRIMARY KEY, canvas_id INT NOT NULL, parent_node_id INT NULL, node_type VARCHAR(64) NOT NULL DEFAULT 'text', title VARCHAR(255) NOT NULL DEFAULT '', position_x DOUBLE NOT NULL DEFAULT 0, position_y DOUBLE NOT NULL DEFAULT 0, width DOUBLE NULL, height DOUBLE NULL, z_index INT NOT NULL DEFAULT 0, rotation DOUBLE NOT NULL DEFAULT 0, status VARCHAR(32) NOT NULL DEFAULT 'idle', hidden BOOLEAN NOT NULL DEFAULT FALSE, locked BOOLEAN NOT NULL DEFAULT FALSE, collapsed BOOLEAN NOT NULL DEFAULT FALSE, data_json LONGTEXT, ports_json LONGTEXT, ai_config_json LONGTEXT, style_json LONGTEXT, revision INT NOT NULL DEFAULT 1, created_by_user_id INT NULL, updated_by_user_id INT NULL, created_at DATETIME, updated_at DATETIME, deleted_at DATETIME NULL)",
        "CREATE TABLE IF NOT EXISTS sluvo_canvas_edge (id INT AUTO_INCREMENT PRIMARY KEY, canvas_id INT NOT NULL, source_node_id INT NOT NULL, target_node_id INT NOT NULL, source_port_id VARCHAR(255) NULL, target_port_id VARCHAR(255) NULL, edge_type VARCHAR(64) NOT NULL DEFAULT 'custom', label VARCHAR(255) NULL, data_json LONGTEXT, style_json LONGTEXT, hidden BOOLEAN NOT NULL DEFAULT FALSE, revision INT NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME, deleted_at DATETIME NULL)",
        "CREATE TABLE IF NOT EXISTS sluvo_canvas_asset (id INT AUTO_INCREMENT PRIMARY KEY, project_id INT NOT NULL, canvas_id INT NULL, node_id INT NULL, owner_user_id INT NOT NULL, media_type VARCHAR(32) NOT NULL DEFAULT 'image', source_type VARCHAR(64) NULL, url LONGTEXT NOT NULL, thumbnail_url LONGTEXT NULL, storage_object_id INT NULL, mime_type VARCHAR(255) NULL, file_size BIGINT NULL, width INT NULL, height INT NULL, duration_seconds DOUBLE NULL, metadata_json LONGTEXT, created_at DATETIME, updated_at DATETIME, deleted_at DATETIME NULL)",
        "CREATE TABLE IF NOT EXISTS sluvo_community_canvas (id INT AUTO_INCREMENT PRIMARY KEY, source_project_id INT NOT NULL, source_canvas_id INT NOT NULL, owner_user_id INT NOT NULL, team_id INT NOT NULL, title VARCHAR(255) NOT NULL, description LONGTEXT NULL, cover_url LONGTEXT NULL, tags_json LONGTEXT, status VARCHAR(32) NOT NULL DEFAULT 'published', snapshot_json LONGTEXT, nodes_json LONGTEXT, edges_json LONGTEXT, viewport_json LONGTEXT, schema_version INT NOT NULL DEFAULT 1, view_count INT NOT NULL DEFAULT 0, fork_count INT NOT NULL DEFAULT 0, published_at DATETIME NULL, unpublished_at DATETIME NULL, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS sluvo_agent_template (id INT AUTO_INCREMENT PRIMARY KEY, owner_user_id INT NOT NULL, team_id INT NOT NULL, name VARCHAR(255) NOT NULL, description LONGTEXT NULL, avatar_url LONGTEXT NULL, cover_url LONGTEXT NULL, profile_key VARCHAR(64) NOT NULL DEFAULT 'custom_agent', model_code VARCHAR(64) NOT NULL DEFAULT 'deepseek-v4-flash', role_prompt LONGTEXT, use_cases_json LONGTEXT, input_types_json LONGTEXT, output_types_json LONGTEXT, tools_json LONGTEXT, approval_policy_json LONGTEXT, examples_json LONGTEXT, memory_json LONGTEXT, status VARCHAR(32) NOT NULL DEFAULT 'active', forked_from_publication_id INT NULL, created_at DATETIME, updated_at DATETIME, deleted_at DATETIME NULL)",
        "CREATE TABLE IF NOT EXISTS sluvo_community_agent (id INT AUTO_INCREMENT PRIMARY KEY, source_agent_id INT NOT NULL, owner_user_id INT NOT NULL, team_id INT NOT NULL, title VARCHAR(255) NOT NULL, description LONGTEXT NULL, cover_url LONGTEXT NULL, tags_json LONGTEXT, template_snapshot_json LONGTEXT, status VARCHAR(32) NOT NULL DEFAULT 'published', view_count INT NOT NULL DEFAULT 0, fork_count INT NOT NULL DEFAULT 0, published_at DATETIME NULL, unpublished_at DATETIME NULL, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS sluvo_agent_session (id INT AUTO_INCREMENT PRIMARY KEY, project_id INT NOT NULL, canvas_id INT NOT NULL, target_node_id INT NULL, user_id INT NOT NULL, team_id INT NOT NULL, title VARCHAR(255) NULL, agent_profile VARCHAR(64) NOT NULL DEFAULT 'canvas_agent', mode VARCHAR(32) NOT NULL DEFAULT 'semi_auto', status VARCHAR(32) NOT NULL DEFAULT 'active', context_snapshot_json LONGTEXT, last_event_at DATETIME NULL, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS sluvo_agent_event (id INT AUTO_INCREMENT PRIMARY KEY, session_id INT NOT NULL, turn_id VARCHAR(64) NULL, role VARCHAR(32) NOT NULL DEFAULT 'user', event_type VARCHAR(32) NOT NULL DEFAULT 'message', sequence_no INT NOT NULL DEFAULT 0, payload_json LONGTEXT, created_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS sluvo_agent_action (id INT AUTO_INCREMENT PRIMARY KEY, session_id INT NOT NULL, project_id INT NOT NULL, canvas_id INT NOT NULL, target_node_id INT NULL, action_type VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'proposed', input_json LONGTEXT, patch_json LONGTEXT, result_json LONGTEXT, error_json LONGTEXT, approved_by_user_id INT NULL, executed_at DATETIME NULL, created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS sluvo_agent_run (id INT AUTO_INCREMENT PRIMARY KEY, project_id INT NOT NULL, canvas_id INT NOT NULL, session_id INT NULL, target_node_id INT NULL, user_id INT NOT NULL, team_id INT NOT NULL, title VARCHAR(255) NULL, goal LONGTEXT, source_surface VARCHAR(32) NOT NULL DEFAULT 'panel', status VARCHAR(32) NOT NULL DEFAULT 'drafting', mode VARCHAR(32) NOT NULL DEFAULT 'semi_auto', approval_policy_json LONGTEXT, context_snapshot_json LONGTEXT, summary_json LONGTEXT, created_at DATETIME, updated_at DATETIME, finished_at DATETIME NULL)",
        "CREATE TABLE IF NOT EXISTS sluvo_agent_step (id INT AUTO_INCREMENT PRIMARY KEY, run_id INT NOT NULL, session_id INT NULL, agent_template_id INT NULL, action_id INT NULL, step_key VARCHAR(64) NOT NULL, agent_name VARCHAR(255) NULL, agent_profile VARCHAR(64) NOT NULL DEFAULT 'canvas_agent', model_code VARCHAR(64) NOT NULL DEFAULT 'deepseek-v4-flash', title VARCHAR(255) NULL, status VARCHAR(32) NOT NULL DEFAULT 'queued', input_json LONGTEXT, output_json LONGTEXT, error_json LONGTEXT, order_index INT NOT NULL DEFAULT 0, created_at DATETIME, updated_at DATETIME, finished_at DATETIME NULL)",
        "CREATE TABLE IF NOT EXISTS sluvo_agent_artifact (id INT AUTO_INCREMENT PRIMARY KEY, run_id INT NOT NULL, step_id INT NOT NULL, canvas_node_id INT NULL, generation_record_id INT NULL, title VARCHAR(255) NULL, artifact_type VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'draft', payload_json LONGTEXT, preview_json LONGTEXT, write_policy VARCHAR(64) NOT NULL DEFAULT 'readonly', created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE IF NOT EXISTS sluvo_canvas_mutation (id INT AUTO_INCREMENT PRIMARY KEY, project_id INT NOT NULL, canvas_id INT NOT NULL, actor_type VARCHAR(32) NOT NULL DEFAULT 'user', actor_user_id INT NULL, agent_session_id INT NULL, agent_action_id INT NULL, mutation_type VARCHAR(64) NOT NULL DEFAULT 'canvas.update', revision_from INT NULL, revision_to INT NULL, patch_json LONGTEXT, created_at DATETIME)",
        "CREATE UNIQUE INDEX uq_sluvo_project_member_project_user ON sluvo_project_member (project_id, user_id)",
        "CREATE UNIQUE INDEX uq_sluvo_canvas_project_key ON sluvo_canvas (project_id, canvas_key)",
        "CREATE INDEX idx_sluvo_project_team_status ON sluvo_project (team_id, status, deleted_at)",
        "CREATE INDEX idx_sluvo_project_owner ON sluvo_project (owner_user_id)",
        "CREATE INDEX idx_sluvo_project_member_user ON sluvo_project_member (user_id, role)",
        "CREATE INDEX idx_sluvo_canvas_node_canvas_type ON sluvo_canvas_node (canvas_id, node_type, deleted_at)",
        "CREATE INDEX idx_sluvo_canvas_node_parent ON sluvo_canvas_node (parent_node_id)",
        "CREATE INDEX idx_sluvo_canvas_edge_canvas_type ON sluvo_canvas_edge (canvas_id, edge_type, deleted_at)",
        "CREATE INDEX idx_sluvo_canvas_edge_nodes ON sluvo_canvas_edge (source_node_id, target_node_id)",
        "CREATE INDEX idx_sluvo_canvas_asset_project_type ON sluvo_canvas_asset (project_id, media_type, deleted_at)",
        "CREATE UNIQUE INDEX uq_sluvo_community_canvas_source_project ON sluvo_community_canvas (source_project_id)",
        "CREATE INDEX idx_sluvo_community_canvas_status_time ON sluvo_community_canvas (status, published_at)",
        "CREATE INDEX idx_sluvo_community_canvas_owner ON sluvo_community_canvas (owner_user_id, status)",
        "CREATE INDEX idx_sluvo_agent_template_owner ON sluvo_agent_template (owner_user_id, team_id, status, deleted_at)",
        "CREATE INDEX idx_sluvo_agent_template_profile ON sluvo_agent_template (profile_key, model_code)",
        "CREATE INDEX idx_sluvo_community_agent_status_time ON sluvo_community_agent (status, published_at)",
        "CREATE INDEX idx_sluvo_community_agent_owner ON sluvo_community_agent (owner_user_id, status)",
        "CREATE INDEX idx_sluvo_agent_session_project ON sluvo_agent_session (project_id, status, updated_at)",
        "CREATE INDEX idx_sluvo_agent_event_session_sequence ON sluvo_agent_event (session_id, sequence_no)",
        "CREATE INDEX idx_sluvo_agent_action_status ON sluvo_agent_action (project_id, status, action_type)",
        "CREATE INDEX idx_sluvo_agent_run_project ON sluvo_agent_run (project_id, status, updated_at)",
        "CREATE INDEX idx_sluvo_agent_step_run ON sluvo_agent_step (run_id, order_index)",
        "CREATE INDEX idx_sluvo_agent_artifact_run ON sluvo_agent_artifact (run_id, artifact_type, status)",
        "CREATE INDEX idx_sluvo_canvas_mutation_canvas ON sluvo_canvas_mutation (canvas_id, created_at)",
        "CREATE INDEX idx_membership_plan_status_scope ON membership_plan (status, scope_type, sort_order)",
        "CREATE INDEX idx_user_membership_user_id ON user_membership (user_id)",
        "CREATE INDEX idx_team_membership_team_id ON team_membership (team_id)",
        "ALTER TABLE director_agent_session ADD COLUMN session_config_json TEXT NULL",
        "ALTER TABLE generationrecord ADD COLUMN points_status VARCHAR(32) NULL DEFAULT 'free'",
        "ALTER TABLE task_job ADD COLUMN upstream_task_id VARCHAR(255) NULL",
    ]

    with engine.connect() as conn:
        for sql in statements:
            try:
                conn.execute(text(sql))
            except Exception as exc:
                if not _is_duplicate_column_error(exc):
                    raise
        conn.commit()


def _ensure_shared_resource_type_storage() -> None:
    driver = engine.url.drivername.lower()
    if "mysql" not in driver:
        return

    with engine.connect() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE sharedresource
                MODIFY COLUMN resource_type VARCHAR(32) NOT NULL
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE sharedresource
                SET resource_type = CASE resource_type
                    WHEN 'CHARACTER_REF' THEN 'character'
                    WHEN 'SCENE_REF' THEN 'scene'
                    WHEN 'PROP_REF' THEN 'prop'
                    WHEN 'LORA' THEN 'lora'
                    ELSE resource_type
                END
                """
            )
        )
        conn.commit()


def _migrate_legacy_image_model_codes() -> None:
    replacements = [
        ("shenlu-image-fast", "nano-banana-2-低价版"),
        ("low_cost", "nano-banana-2-低价版"),
        ("shenlu-image-stable", "nano-banana-pro"),
        ("stable", "nano-banana-pro"),
    ]
    with engine.connect() as conn:
        for old_value, new_value in replacements:
            conn.execute(
                text(
                    """
                    UPDATE script
                    SET workflow_settings_json = REPLACE(workflow_settings_json, :old_value, :new_value)
                    WHERE workflow_settings_json IS NOT NULL AND workflow_settings_json <> ''
                    """
                ),
                {"old_value": old_value, "new_value": new_value},
            )
            conn.execute(
                text(
                    """
                    UPDATE episode
                    SET workflow_override_json = REPLACE(workflow_override_json, :old_value, :new_value)
                    WHERE workflow_override_json IS NOT NULL AND workflow_override_json <> ''
                    """
                ),
                {"old_value": old_value, "new_value": new_value},
            )
        conn.commit()


def create_db_and_tables() -> None:
    log_pool_status("startup-before-create")
    SQLModel.metadata.create_all(engine)
    _ensure_lightweight_columns()
    _ensure_shared_resource_type_storage()
    _migrate_legacy_image_model_codes()
    from services.membership_service import ensure_builtin_membership_plans
    with session_scope() as session:
        ensure_builtin_membership_plans(session)
    log_pool_status("startup-after-create")


def get_session():
    with session_scope() as session:
        yield session
