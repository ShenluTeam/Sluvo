from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from pydantic import Field as PydanticField

PANEL_TYPE_NORMAL = "normal"
PANEL_TYPE_NINE_GRID = "nine_grid"
VALID_PANEL_TYPES = {PANEL_TYPE_NORMAL, PANEL_TYPE_NINE_GRID}
STORYBOARD_MODE_COMMENTARY = "commentary"
STORYBOARD_MODE_COMIC = "comic"
VALID_STORYBOARD_MODES = {STORYBOARD_MODE_COMMENTARY, STORYBOARD_MODE_COMIC}
VALID_SEGMENT_GRID_COUNTS = {1, 2, 4, 6, 9}
EXTERNAL_PROVIDER_SHENLU_AGENT = "shenlu_agent"


def normalize_panel_type(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_PANEL_TYPES else PANEL_TYPE_NORMAL


def is_nine_grid_panel_type(value: Optional[str]) -> bool:
    return normalize_panel_type(value) == PANEL_TYPE_NINE_GRID


def normalize_storyboard_mode(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_STORYBOARD_MODES else STORYBOARD_MODE_COMMENTARY


def normalize_grid_count(value: Optional[int]) -> int:
    try:
        count = int(value or 1)
    except (TypeError, ValueError):
        count = 1
    return count if count in VALID_SEGMENT_GRID_COUNTS else 1


# ==========================================
# 剧本与剧集
# ==========================================
class ScriptCreate(BaseModel):
    name: str
    description: Optional[str] = None
    aspect_ratio: str = "16:9"
    style_preset: str = "默认写实"
    default_storyboard_mode: str = STORYBOARD_MODE_COMIC
    workflow_settings_json: Optional[Dict[str, Any]] = None

class ScriptUpdate(BaseModel):
    aspect_ratio: Optional[str] = None
    style_preset: Optional[str] = None
    default_storyboard_mode: Optional[str] = None
    workflow_settings_json: Optional[Dict[str, Any]] = None

class ScriptSourceUpdateRequest(BaseModel):
    source_text: Optional[str] = None

class EpisodeSplitPreviewRequest(BaseModel):
    source_text: Optional[str] = None
    split_mode: str = "rule"
    requirements: Optional[str] = None

class EpisodeSplitItem(BaseModel):
    title: str
    source_text: Optional[str] = None

class EpisodeSplitCommitRequest(BaseModel):
    source_text: Optional[str] = None
    episodes: List[EpisodeSplitItem]
    replace_existing: bool = True

class EpisodeCreate(BaseModel):
    script_id: str
    title: str
    sequence_num: int = 1
    insert_after_episode_id: Optional[str] = None


class EpisodeUpdateRequest(BaseModel):
    title: Optional[str] = None
    source_text: Optional[str] = None
    storyboard_mode: Optional[str] = None
    workflow_override_json: Optional[Dict[str, Any]] = None
    clear_workflow_override: bool = False

class PanelCreate(BaseModel):
    episode_id: str
    insert_at: Optional[int] = None  # 可选：插入到第几个位置(sequence_num)
    panel_type: Optional[str] = None

class ReorderRequest(BaseModel):
    episode_id: str
    panel_id: str   
    new_index: int  

# ==========================================
# 生成图片请求
# ==========================================
class GenerateRequest(BaseModel):
    panel_id: str     
    prompt: str
    negative_prompt: Optional[str] = None
    resolution: Optional[str] = None

class Img2ImgRequest(BaseModel):
    episode_id: str   
    prompt: str
    ref_images: List[str] = [] 
    ratio: str = "4:3"         
    resolution: str = "2k"  

class NanoBananaRequest(BaseModel):
    prompt: str
    model: str = "nano-banana-pro"
    aspectRatio: str = "4:3"
    imageSize: str = "2K"
    urls: List[str] = []
    episode_id: str  # 必填，用于将生成结果保存到对应剧集的分镜中

class GenerateImageV2Request(BaseModel):
    prompt: str
    prompt_zh: Optional[str] = None
    resolution: str = "2k"
    quality: Optional[str] = None
    aspectRatio: str = "16:9"
    model_code: str = "nano-banana-pro"
    channel: Optional[str] = None
    imageUrls: List[str] = []
    insert_at: Optional[int] = None
    panel_id: Optional[str] = None


class ImageEstimateRequest(BaseModel):
    mode: str = "text_to_image"
    model_code: str = "nano-banana-pro"
    channel: Optional[str] = None
    resolution: str = "2k"
    quality: Optional[str] = None
    aspect_ratio: str = "16:9"
    has_reference_images: bool = False

class GenerateAssetImageRequest(BaseModel):
    prompt: str
    channel: str = "nano-banana-pro"
    aspectRatio: str = "1:1"
    insert_at: Optional[int] = None
    panel_id: Optional[str] = None

class UploadImageRequest(BaseModel):
    image_base64: str    

class ParseScriptV2Request(BaseModel):
    text: str
    storyboard_mode: Optional[str] = None
    mode: Optional[str] = None
    plan_revision_instruction: Optional[str] = None
    confirmed_plan_id: Optional[str] = None
    confirmed_plan_bundle: Optional[Dict[str, Any]] = None


class StructuredAssetDraftItem(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_word: Optional[str] = None
    resource_type: Optional[str] = None
    source_status: str = "draft"


class StructuredPanelDraftItem(BaseModel):
    sequence: int = 0
    panel_type: Optional[str] = None
    storyboard_mode: Optional[str] = STORYBOARD_MODE_COMMENTARY
    segment_no: Optional[int] = None
    segment_summary: Optional[str] = None
    narrative_purpose: Optional[str] = None
    panel_type_reason: Optional[str] = None
    scene_refs: List[str] = []
    character_refs: List[str] = []
    prop_refs: List[str] = []
    prompt: str = ""
    prompt_zh: Optional[str] = None
    nine_grid_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    image_framing: Optional[str] = None
    original_text: Optional[str] = None
    narration_text: Optional[str] = None
    dialogue_text: Optional[str] = None
    segment_break: bool = False
    shot_type: Optional[str] = None
    camera_motion: Optional[str] = None
    composition: Optional[str] = None
    transition_to_next: Optional[str] = None
    binding_suggestions: Optional[Dict[str, Any]] = None


class StructuredSpeechItem(BaseModel):
    speaker_name: Optional[str] = None
    speaker_ref: Optional[str] = None
    speech_type: str = "spoken"
    text: str = ""
    emotion: Optional[str] = None
    intensity: Optional[str] = "medium"
    mouth_sync_required: bool = False


class StructuredGridCellDraftItem(BaseModel):
    cell_index: int = 1
    start_second: float = 0.0
    end_second: float = 0.0
    duration_seconds: float = 0.0
    shot_description: Optional[str] = None
    action_description: Optional[str] = None
    dialogue_excerpt: Optional[str] = None
    speech_items: List[StructuredSpeechItem] = []
    performance_focus: Optional[str] = None
    mouth_sync_required: bool = False
    shot_type: Optional[str] = None
    camera_motion: Optional[str] = None
    composition: Optional[str] = None
    lighting: Optional[str] = None
    ambiance: Optional[str] = None
    camera_position: Optional[str] = None
    camera_direction: Optional[str] = None
    shot_purpose: Optional[str] = None
    image_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    image_prompt_structured: Dict[str, Any] = PydanticField(default_factory=dict)
    video_prompt_structured: Dict[str, Any] = PydanticField(default_factory=dict)
    character_refs: List[str] = []
    scene_refs: List[str] = []
    prop_refs: List[str] = []
    asset_status: str = "idle"
    binding_suggestions: Optional[Dict[str, Any]] = None


class StructuredStorySegmentDraftItem(BaseModel):
    sequence_num: int = 1
    title: Optional[str] = None
    summary: Optional[str] = None
    text_span: Dict[str, Any] = PydanticField(default_factory=dict)
    recommended_duration_seconds: int = 6
    grid_count: int = 1
    pacing: Optional[str] = None
    rhythm: Optional[str] = None
    scene_constraint: Optional[str] = None
    scene_prompt: Optional[str] = None
    continuity_note: Optional[str] = None
    transition_to_next: Optional[str] = None
    character_refs: List[str] = []
    scene_refs: List[str] = []
    prop_refs: List[str] = []
    segment_prompt_summary: Optional[str] = None
    multi_shot_prompt: Optional[str] = None
    multi_shot_video_prompt: Optional[str] = None
    reference_assets: List[Dict[str, Any]] = []
    reference_images: List[str] = []
    auto_asset_reference_enabled: bool = True
    generation_status: str = "idle"
    grid_cells: List[StructuredGridCellDraftItem] = []


class DirectorDraftSegmentItem(BaseModel):
    segment_no: int = 0
    summary: str = ""
    narrative_purpose: str = ""
    emotion: str = ""
    recommended_panel_type: str = PANEL_TYPE_NORMAL
    reason: str = ""


class DirectorDraftParagraphItem(BaseModel):
    paragraph_no: int = 0
    summary: str = ""
    scene: str = ""
    characters: List[str] = []
    emotion: str = ""
    narrative_function: str = ""
    shot_ids: List[str] = []
    warnings: List[str] = []


class DirectorDraftNineGridCandidateItem(BaseModel):
    grid_no: int = 0
    shot_size: str = ""
    angle: str = ""
    subject_position: str = ""
    composition_focus: str = ""
    emotion_effect: str = ""
    usage_note: str = ""


class DirectorDraftRecommendationItem(BaseModel):
    grid_no: int = 0
    reason: str = ""


class DirectorDraftShotItem(BaseModel):
    shot_id: str = ""
    sequence: int = 0
    paragraph_no: int = 0
    shot_type: str = ""
    shot_size: str = ""
    visual_content: str = ""
    shot_purpose: str = ""
    duration_seconds: float = 0
    scene_refs: List[str] = []
    character_refs: List[str] = []
    prop_refs: List[str] = []
    motion_prompt: Optional[str] = None
    final_prompt_zh: str = ""
    start_frame_prompt_zh: Optional[str] = None
    end_frame_prompt_zh: Optional[str] = None
    nine_grid_candidates: List[DirectorDraftNineGridCandidateItem] = []
    recommended_candidates: List[DirectorDraftRecommendationItem] = []
    recommended_summary: str = ""
    candidate_summary: str = ""
    warnings: List[str] = []


class DirectorDraftSummary(BaseModel):
    paragraph_count: int = 0
    shot_count: int = 0
    recommended_count: int = 0
    warning_count: int = 0


class EpisodeDirectorDraftPayload(BaseModel):
    segments: List[DirectorDraftSegmentItem] = []
    paragraphs: List[DirectorDraftParagraphItem] = []
    shots: List[DirectorDraftShotItem] = []
    summary: DirectorDraftSummary = DirectorDraftSummary()


class EpisodeStructuredDraftPayload(BaseModel):
    characters: List[StructuredAssetDraftItem] = []
    scenes: List[StructuredAssetDraftItem] = []
    props: List[StructuredAssetDraftItem] = []
    panel_drafts: List[StructuredPanelDraftItem] = []
    story_segments: List[StructuredStorySegmentDraftItem] = []
    director_draft: Optional[EpisodeDirectorDraftPayload] = None
    warnings: List[str] = []


class ParseScriptV2CommitRequest(BaseModel):
    structured_draft: EpisodeStructuredDraftPayload
    replace_existing_panels: bool = False
    sync_resources: bool = True


class PanelContentUpdateRequest(BaseModel):
    title: Optional[str] = None
    panel_type: Optional[str] = None
    storyboard_mode: Optional[str] = None
    text_span_json: Optional[str] = None
    recommended_duration_seconds: Optional[int] = None
    grid_count: Optional[int] = None
    pacing: Optional[str] = None
    rhythm: Optional[str] = None
    continuity_note: Optional[str] = None
    segment_no: Optional[int] = None
    segment_summary: Optional[str] = None
    narrative_purpose: Optional[str] = None
    panel_type_reason: Optional[str] = None
    segment_prompt_summary: Optional[str] = None
    narration_text: Optional[str] = None
    dialogue_text: Optional[str] = None
    segment_break: Optional[bool] = None
    dependency_panel_id: Optional[int] = None
    shot_type: Optional[str] = None
    camera_motion: Optional[str] = None
    composition: Optional[str] = None
    previous_storyboard_path: Optional[str] = None
    transition_to_next: Optional[str] = None
    scene: Optional[str] = None
    character: Optional[str] = None
    prop: Optional[str] = None
    prompt: Optional[str] = None
    nine_grid_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    image_framing: Optional[str] = None
    original_text: Optional[str] = None
    entity_bindings: Optional[Dict[str, Any]] = None
    generation_status: Optional[str] = None
    note: Optional[str] = None
    source: str = "content"


class SegmentUpdateRequest(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    recommended_duration_seconds: Optional[int] = None
    grid_count: Optional[int] = None
    pacing: Optional[str] = None
    rhythm: Optional[str] = None
    scene_prompt: Optional[str] = None
    continuity_note: Optional[str] = None
    transition_to_next: Optional[str] = None
    segment_prompt_summary: Optional[str] = None
    multi_shot_prompt: Optional[str] = None
    multi_shot_video_prompt: Optional[str] = None
    image_url: Optional[str] = None
    image_history: Optional[List[str]] = None
    video_url: Optional[str] = None
    video_thumbnail_url: Optional[str] = None
    video_history: Optional[List[Dict[str, Any]]] = None
    auto_asset_reference_enabled: Optional[bool] = None
    note: Optional[str] = None


class SegmentCellUpdateRequest(BaseModel):
    start_second: Optional[float] = None
    end_second: Optional[float] = None
    duration_seconds: Optional[float] = None
    shot_description: Optional[str] = None
    action_description: Optional[str] = None
    dialogue_excerpt: Optional[str] = None
    speech_items: Optional[List[StructuredSpeechItem]] = None
    performance_focus: Optional[str] = None
    mouth_sync_required: Optional[bool] = None
    shot_type: Optional[str] = None
    camera_motion: Optional[str] = None
    composition: Optional[str] = None
    lighting: Optional[str] = None
    ambiance: Optional[str] = None
    camera_position: Optional[str] = None
    camera_direction: Optional[str] = None
    shot_purpose: Optional[str] = None
    image_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    note: Optional[str] = None


class PanelEntityBindingsUpdateRequest(BaseModel):
    entity_bindings: Dict[str, Any]


class SharedResourceVersionCreateRequest(BaseModel):
    version_tag: str
    appearance_prompt: Optional[str] = None
    file_url: Optional[str] = None
    trigger_word: Optional[str] = None
    start_seq: Optional[int] = None
    end_seq: Optional[int] = None
    is_default: bool = False


class SharedResourceVersionUpdateRequest(BaseModel):
    version_tag: Optional[str] = None
    appearance_prompt: Optional[str] = None
    file_url: Optional[str] = None
    trigger_word: Optional[str] = None
    start_seq: Optional[int] = None
    end_seq: Optional[int] = None
    is_default: Optional[bool] = None


class ExtractScriptAssetsRequest(BaseModel):
    source_text: Optional[str] = None
    episode_id: Optional[str] = None


class GenerateSharedResourceImageRequest(BaseModel):
    prompt: str
    model_code: str = "nano-banana-pro"
    channel: Optional[str] = None
    resolution: str = "2k"
    quality: Optional[str] = None
    aspectRatio: str
    reference_images: List[str] = []
    generation_intent: Optional[str] = None
    version_tag: Optional[str] = None
    start_seq: Optional[int] = None
    end_seq: Optional[int] = None
    is_default: bool = True

class GenerateVideoRequest(BaseModel):
    channel_id: str
    prompt: str

    # 兼容旧版单图
    image_url: Optional[str] = None

    # 首尾帧
    start_frame: Optional[str] = None
    end_frame: Optional[str] = None

    # 多帧参考
    reference_images: Optional[List[str]] = None

    # 参考视频
    reference_videos: Optional[List[str]] = None

    # 数字人音频
    audio_url: Optional[str] = None

    duration: int = 5
    resolution: str = "720p"
    aspect_ratio: Optional[str] = None
    movement_amplitude: Optional[str] = "auto"
    audio: bool = False

    episode_id: Optional[str] = None
    panel_id: Optional[str] = None


class VideoEstimateRequest(BaseModel):
    channel: str = "shenlu-physics-engine"
    resolution: str = "720p"
    duration: int = 5
    aspect_ratio: str = "16:9"
    audio: bool = False
    reference_image_count: int = 0
    reference_video_count: int = 0

# ==========================================
# 用户与鉴权
# ==========================================
class SendEmailCodeRequest(BaseModel):
    email: EmailStr
    captcha_id: str
    captcha_code: str

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    email_code: str
    nickname: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class VerifyEmailRequest(BaseModel):
    email_code: str

class PasswordResetSendCodeRequest(BaseModel):
    email: EmailStr
    captcha_id: str
    captcha_code: str

class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    email_code: str
    new_password: str

class UpdateProfileRequest(BaseModel):
    nickname: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class TeamInviteCreateRequest(BaseModel):
    email: Optional[EmailStr] = None
    role: str = "editor"
    expire_hours: int = 72

class TeamInviteAcceptRequest(BaseModel):
    token: str
    auto_migrate_projects: bool = True

class TeamMemberRoleUpdateRequest(BaseModel):
    role: str

class TeamMemberQuotaUpdateRequest(BaseModel):
    point_quota: Optional[int] = None
    reset_used: bool = False

# ==========================================
# 资源库相关(SharedResource)
# ==========================================
from models import ResourceTypeEnum

class SharedResourceCreate(BaseModel):
    script_id: str
    resource_type: ResourceTypeEnum
    name: str
    file_url: Optional[str] = None
    trigger_word: Optional[str] = None
    description: Optional[str] = None
    aliases: Optional[List[str]] = None

# ==========================================
# 管理员与通道设置
# ==========================================
class AdminLoginRequest(BaseModel):
    email: str
    password: str


class MembershipPlanUpsertRequest(BaseModel):
    code: Optional[str] = None
    name: str
    status: str = "active"
    scope_type: str = "both"
    sort_order: int = 100
    priority_default: int = 100
    max_storyboard_concurrency: Optional[int] = None
    max_resource_concurrency: Optional[int] = None
    max_media_concurrency: Optional[int] = None
    max_audio_concurrency: Optional[int] = None
    storage_quota_bytes: Optional[int] = None
    storage_quota_gb: Optional[float] = None
    description: Optional[str] = None
    is_default: bool = False


class MembershipAssignmentRequest(BaseModel):
    plan_id: int
    starts_at: Optional[str] = None
    expires_at: Optional[str] = None
    duration_days: Optional[int] = None
    enabled: bool = True
    remark: Optional[str] = None


class UserMembershipOverrideRequest(BaseModel):
    enabled: bool = True
    effective_priority: Optional[int] = None
    max_storyboard_concurrency: Optional[int] = None
    max_resource_concurrency: Optional[int] = None
    max_media_concurrency: Optional[int] = None
    max_audio_concurrency: Optional[int] = None
    storage_quota_bytes: Optional[int] = None
    storage_quota_gb: Optional[float] = None
    remark: Optional[str] = None

class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    cost_points: Optional[int] = None
    is_active: Optional[bool] = None
    is_vip_only: Optional[bool] = None
    sort_order: Optional[int] = None


class ExternalProviderCredentialUpdateRequest(BaseModel):
    token: str


class ExternalProviderCredentialPermissionUpdateRequest(BaseModel):
    openclaw_api_enabled: bool


class ExternalAgentSessionCreateRequest(BaseModel):
    provider: str = EXTERNAL_PROVIDER_SHENLU_AGENT
    name: Optional[str] = None
    episode_id: Optional[str] = None


class ExternalAgentSettingsPayload(BaseModel):
    locale: Optional[str] = None
    aspect_ratio: Optional[str] = None
    style: Optional[str] = None
    generation_method: Optional[str] = None
    image_size: Optional[str] = None
    video_resolution: Optional[str] = None
    video_model: Optional[str] = None


class ExternalAgentSettingsUpdateRequest(BaseModel):
    episode_id: Optional[str] = None
    settings: ExternalAgentSettingsPayload


class ExternalAgentChatRequest(BaseModel):
    message: str


class ExternalAgentImportScriptRequest(BaseModel):
    mode: str = "current_script_source"
    source_file_id: Optional[str] = None
    name: Optional[str] = None


class ExternalAgentImportCharactersRequest(BaseModel):
    source_file_ids: Optional[List[str]] = None


class ExternalAgentImportPanelsRequest(BaseModel):
    source_file_id: Optional[str] = None
    episode_id: Optional[str] = None


class OpenClawProjectSettingsPayload(BaseModel):
    locale: Optional[str] = None
    aspect_ratio: Optional[str] = None
    style: Optional[str] = None
    generation_method: Optional[str] = None
    image_size: Optional[str] = None
    video_resolution: Optional[str] = None
    video_model: Optional[str] = None
    audio_model: Optional[str] = None
    audio_voice: Optional[str] = None


class OpenClawProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    aspect_ratio: str = "16:9"
    style_preset: str = "默认写实"
    episode_title: str = "第 1 集"
    source_text: Optional[str] = None
    settings: Optional[OpenClawProjectSettingsPayload] = None


class OpenClawProjectSettingsUpdateRequest(BaseModel):
    settings: OpenClawProjectSettingsPayload


class OpenClawEpisodeCreateRequest(BaseModel):
    title: str
    source_text: Optional[str] = None


class OpenClawQuestionAnswerPayload(BaseModel):
    question_id: str
    action: str = "confirm"
    answer: Optional[str] = None
    modifications: Dict[str, Any] = PydanticField(default_factory=dict)


class OpenClawWizardAnswerPayload(BaseModel):
    question_id: str
    action: str = "confirm"
    answers: Dict[str, Any] = PydanticField(default_factory=dict)


class OpenClawAttachmentPayload(BaseModel):
    type: str = "image"
    url: str
    thumbnail_url: Optional[str] = None
    name: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    metadata: Dict[str, Any] = PydanticField(default_factory=dict)


class OpenClawAgentChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: Optional[str] = None
    question_answer: Optional[OpenClawQuestionAnswerPayload] = None
    wizard_answer: Optional[OpenClawWizardAnswerPayload] = None
    attachments: List[OpenClawAttachmentPayload] = PydanticField(default_factory=list)


class OpenClawAgentChatResponse(BaseModel):
    session_id: str
    status: str
    reply: str
    actions: List[Dict[str, Any]] = PydanticField(default_factory=list)
    workspace: Dict[str, Any] = PydanticField(default_factory=dict)
    partial_reply: Optional[str] = None
    tasks: List[Dict[str, Any]] = PydanticField(default_factory=list)
    project_changes: List[Dict[str, Any]] = PydanticField(default_factory=list)
    pending_question: Optional[Dict[str, Any]] = None


class OpenClawAssetItem(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_word: Optional[str] = None
    aliases: Optional[List[str]] = None
    file_url: Optional[str] = None


class OpenClawAssetExtractRequest(BaseModel):
    source_text: Optional[str] = None
    resource_types: Optional[List[str]] = None
    import_to_platform: bool = True


class OpenClawAssetImportRequest(BaseModel):
    characters: List[OpenClawAssetItem] = []
    scenes: List[OpenClawAssetItem] = []
    props: List[OpenClawAssetItem] = []
    overwrite_existing: bool = True


class ProductizedExternalBaseModel(BaseModel):
    model_config = {"extra": "forbid", "protected_namespaces": ()}


class CreativeBase64UploadRequest(ProductizedExternalBaseModel):
    filename: str
    content_type: str
    data_base64: str


class CreativeOwnershipPayload(ProductizedExternalBaseModel):
    ownership_mode: str = "standalone"
    project_id: Optional[str] = None
    episode_id: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None


class CreativeImageEstimateRequest(CreativeOwnershipPayload):
    mode: str = "text_to_image"
    model_code: str = "nano-banana-pro"
    model: Optional[str] = None
    resolution: str = "2k"
    quality: Optional[str] = None
    aspect_ratio: str = "16:9"
    reference_images: List[str] = PydanticField(default_factory=list)


class CreativeVideoEstimateRequest(CreativeOwnershipPayload):
    video_type: Optional[str] = "standard"
    model: Optional[str] = None
    model_code: Optional[str] = None
    generation_type: Optional[str] = None
    resolution: str = "720p"
    duration: int = 5
    aspect_ratio: str = "16:9"
    image_refs: List[str] = PydanticField(default_factory=list)
    video_refs: List[str] = PydanticField(default_factory=list)
    audio_refs: List[str] = PydanticField(default_factory=list)
    reference_images: List[str] = PydanticField(default_factory=list)
    reference_videos: List[str] = PydanticField(default_factory=list)
    first_frame: Optional[str] = None
    last_frame: Optional[str] = None
    motion_strength: Optional[str] = None
    audio_enabled: bool = False
    camera_fixed: bool = False
    quality_mode: Optional[str] = None
    real_person_mode: bool = False
    web_search: bool = False
    style: Optional[str] = None
    image_ref_entries: List[Dict[str, Any]] = PydanticField(default_factory=list)
    video_ref_entries: List[Dict[str, Any]] = PydanticField(default_factory=list)
    audio_ref_entries: List[Dict[str, Any]] = PydanticField(default_factory=list)


class CreativeImageGenerateRequest(CreativeImageEstimateRequest):
    prompt: str
    negative_prompt: Optional[str] = None


class CreativeVideoGenerateRequest(CreativeVideoEstimateRequest):
    prompt: str
    start_frame: Optional[str] = None
    audio_url: Optional[str] = None


class CreativeAudioEstimateRequest(CreativeOwnershipPayload):
    ability_type: str
    tier_code: Optional[str] = None
    model_code: Optional[str] = None
    voice_id: Optional[str] = None
    voice_source_type: str = "system"
    script_text: Optional[str] = None
    text_file_url: Optional[str] = None
    preview_text: Optional[str] = None
    prompt: Optional[str] = None
    emotion: Optional[str] = None
    speed: Optional[float] = None
    volume: Optional[float] = None
    pitch: Optional[float] = None
    sample_rate: Optional[int] = None
    bitrate: Optional[int] = None
    audio_format: Optional[str] = None
    channel_count: Optional[int] = None
    subtitle_enabled: bool = False
    language_boost: Optional[str] = None
    watermark_enabled: bool = False
    clone_reference_file: Optional[str] = None
    clone_prompt_audio: Optional[str] = None
    clone_prompt_text: Optional[str] = None
    preview_tier_code: Optional[str] = None
    noise_reduction: bool = False
    volume_normalization: bool = False
    submit_mode: Optional[str] = None


class CreativeAudioGenerateRequest(CreativeAudioEstimateRequest):
    pass


class CreativeAssetGenerateRequest(CreativeOwnershipPayload):
    asset_type: str
    name: str
    prompt: str
    description: Optional[str] = None
    trigger_word: Optional[str] = None
    aliases: List[str] = PydanticField(default_factory=list)
    model_code: str = "nano-banana-pro"
    model: Optional[str] = None
    resolution: str = "2k"
    aspect_ratio: str = "1:1"
    reference_images: List[str] = PydanticField(default_factory=list)


CREATIVE_EDITING_SOURCE_UPLOADED_VIDEO = "uploaded_video"
CREATIVE_EDITING_SOURCE_UPLOADED_IMAGE = "uploaded_image"
CREATIVE_EDITING_SOURCE_PANEL_VIDEO = "panel_video"
CREATIVE_EDITING_SOURCE_PANEL_IMAGE = "panel_image"
VALID_CREATIVE_EDITING_SOURCE_KINDS = {
    CREATIVE_EDITING_SOURCE_UPLOADED_VIDEO,
    CREATIVE_EDITING_SOURCE_UPLOADED_IMAGE,
    CREATIVE_EDITING_SOURCE_PANEL_VIDEO,
    CREATIVE_EDITING_SOURCE_PANEL_IMAGE,
}
VALID_CREATIVE_EDITING_TRANSITIONS = {"cut", "fade", "dissolve", "wipe"}


class CreativeEditingSourceAsset(ProductizedExternalBaseModel):
    asset_id: str
    source_kind: str = CREATIVE_EDITING_SOURCE_UPLOADED_VIDEO
    panel_id: Optional[str] = None
    name: str = ""
    video_url: Optional[str] = None
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    source_duration_seconds: Optional[float] = None
    has_audio: Optional[bool] = None
    default_caption_text: Optional[str] = None


class CreativeEditingTimelineClip(ProductizedExternalBaseModel):
    clip_id: str
    asset_id: str
    enabled: bool = True
    sequence: int = 1
    source_in_seconds: float = 0.0
    source_out_seconds: Optional[float] = None
    play_duration_seconds: Optional[float] = None
    transition_to_next: Optional[str] = "cut"
    caption_text: Optional[str] = None


class CreativeEditingMusicTrack(ProductizedExternalBaseModel):
    audio_url: Optional[str] = None
    enabled: bool = False
    volume: float = 0.3
    start_seconds: float = 0.0
    duration_seconds: Optional[float] = None
    start_seconds: float = 0.0
    duration_seconds: Optional[float] = None


class CreativeEditingDraftDocument(ProductizedExternalBaseModel):
    version: int = 1
    ownership_mode: str = "standalone"
    project_id: Optional[str] = None
    episode_id: Optional[str] = None
    source_assets: List[CreativeEditingSourceAsset] = PydanticField(default_factory=list)
    timeline_clips: List[CreativeEditingTimelineClip] = PydanticField(default_factory=list)
    music_track: Optional[CreativeEditingMusicTrack] = None
    use_transitions: bool = True
    transition_duration: float = 0.5
    playhead_seconds: float = 0.0
    zoom_level: float = 1.0
    selected_clip_id: Optional[str] = None


class CreativeEditingExecutionRequest(ProductizedExternalBaseModel):
    ownership_mode: str = "standalone"
    project_id: Optional[str] = None
    episode_id: Optional[str] = None
    document: CreativeEditingDraftDocument


class CreativeEditingComposeRequest(CreativeEditingExecutionRequest):
    pass


class CreativeEditingJianyingDraftRequest(CreativeEditingExecutionRequest):
    draft_path: Optional[str] = None
    jianying_version: str = "6"
    include_subtitles: bool = True


class CreativeEditingDraftSaveRequest(ProductizedExternalBaseModel):
    ownership_mode: str = "standalone"
    project_id: Optional[str] = None
    episode_id: Optional[str] = None
    updated_at: Optional[str] = None
    document: CreativeEditingDraftDocument


# ==========================================
# AI 原生无限画布
# ==========================================

CANVAS_NODE_TYPE_PROJECT_ROOT = "project_root"
CANVAS_NODE_TYPE_SCRIPT_EPISODE = "script_episode"
CANVAS_NODE_TYPE_SCRIPT = "script"
CANVAS_NODE_TYPE_ASSET_TABLE = "asset_table"
CANVAS_NODE_TYPE_STORYBOARD_TABLE = "storyboard_table"
CANVAS_NODE_TYPE_IMAGE = "image"
CANVAS_NODE_TYPE_VIDEO = "video"
CANVAS_NODE_TYPE_AUDIO = "audio"
CANVAS_NODE_TYPE_EDIT = "edit"
CANVAS_NODE_TYPE_GROUP = "group"
VALID_CANVAS_NODE_TYPES = {
    CANVAS_NODE_TYPE_PROJECT_ROOT,
    CANVAS_NODE_TYPE_SCRIPT_EPISODE,
    CANVAS_NODE_TYPE_SCRIPT,
    CANVAS_NODE_TYPE_ASSET_TABLE,
    CANVAS_NODE_TYPE_STORYBOARD_TABLE,
    CANVAS_NODE_TYPE_IMAGE,
    CANVAS_NODE_TYPE_VIDEO,
    CANVAS_NODE_TYPE_AUDIO,
    CANVAS_NODE_TYPE_EDIT,
    CANVAS_NODE_TYPE_GROUP,
}

CANVAS_EDGE_TYPE_STRUCTURE = "structure"
CANVAS_EDGE_TYPE_SEQUENCE = "sequence"
CANVAS_EDGE_TYPE_GENERATION = "generation"
CANVAS_EDGE_TYPE_VISUAL = "visual"
CANVAS_EDGE_TYPE_DATA_FLOW = "data_flow"
CANVAS_EDGE_TYPE_REFERENCE = "reference"
CANVAS_EDGE_TYPE_TRIGGER = "trigger"
CANVAS_EDGE_TYPE_ORCHESTRATION = "orchestration"
VALID_CANVAS_EDGE_TYPES = {
    CANVAS_EDGE_TYPE_STRUCTURE,
    CANVAS_EDGE_TYPE_SEQUENCE,
    CANVAS_EDGE_TYPE_GENERATION,
    CANVAS_EDGE_TYPE_VISUAL,
    CANVAS_EDGE_TYPE_DATA_FLOW,
    CANVAS_EDGE_TYPE_REFERENCE,
    CANVAS_EDGE_TYPE_TRIGGER,
    CANVAS_EDGE_TYPE_ORCHESTRATION,
}

CANVAS_SYNC_STATUS_CLEAN = "clean"
CANVAS_SYNC_STATUS_DIRTY_LOCAL = "dirty_local"
CANVAS_SYNC_STATUS_STALE = "stale"
CANVAS_SYNC_STATUS_ORPHANED = "orphaned"
CANVAS_SYNC_STATUS_CONFLICT = "conflict"
VALID_CANVAS_SYNC_STATUSES = {
    CANVAS_SYNC_STATUS_CLEAN,
    CANVAS_SYNC_STATUS_DIRTY_LOCAL,
    CANVAS_SYNC_STATUS_STALE,
    CANVAS_SYNC_STATUS_ORPHANED,
    CANVAS_SYNC_STATUS_CONFLICT,
}

CANVAS_AI_CAPABILITIES = {
    "script_write",
    "script_rewrite",
    "script_split",
    "asset_extract",
    "asset_merge",
    "storyboard_generate",
    "storyboard_enhance",
    "prompt_generate",
    "image_generate",
    "image_regenerate",
}


def normalize_canvas_node_type(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_CANVAS_NODE_TYPES else CANVAS_NODE_TYPE_SCRIPT


def normalize_canvas_edge_type(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_CANVAS_EDGE_TYPES else CANVAS_EDGE_TYPE_DATA_FLOW


def normalize_canvas_sync_status(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_CANVAS_SYNC_STATUSES else CANVAS_SYNC_STATUS_CLEAN


class CanvasViewportPayload(BaseModel):
    x: float = 0.0
    y: float = 0.0
    zoom: float = 1.0


class CanvasWorkspacePatchRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    viewport: Optional[CanvasViewportPayload] = None


class CanvasNodeCreateRequest(BaseModel):
    type: str
    title: str = ""
    position: Dict[str, float] = PydanticField(default_factory=dict)
    size: Optional[Dict[str, float]] = None
    status: str = "idle"
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    source_sub_id: Optional[str] = None
    bootstrap_key: Optional[str] = None
    sync_status: str = CANVAS_SYNC_STATUS_CLEAN
    data: Dict[str, Any] = PydanticField(default_factory=dict)
    context: Dict[str, Any] = PydanticField(default_factory=dict)
    ai_config: Dict[str, Any] = PydanticField(default_factory=dict)
    meta: Dict[str, Any] = PydanticField(default_factory=dict)


class CanvasNodeUpdateRequest(BaseModel):
    title: Optional[str] = None
    position: Optional[Dict[str, float]] = None
    size: Optional[Dict[str, float]] = None
    status: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    source_sub_id: Optional[str] = None
    bootstrap_key: Optional[str] = None
    sync_status: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None
    ai_config: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


class CanvasEdgeCreateRequest(BaseModel):
    source: str
    target: str
    type: str = CANVAS_EDGE_TYPE_DATA_FLOW
    mapping: List[Dict[str, Any]] = PydanticField(default_factory=list)
    label: Optional[str] = None


class CanvasEdgeUpdateRequest(BaseModel):
    type: Optional[str] = None
    mapping: Optional[List[Dict[str, Any]]] = None
    label: Optional[str] = None


class CanvasNodeActionRequest(BaseModel):
    payload: Dict[str, Any] = PydanticField(default_factory=dict)


class CanvasNodeSyncRequest(BaseModel):
    payload: Dict[str, Any] = PydanticField(default_factory=dict)


class ProjectCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    aspect_ratio: str = "16:9"
    style_preset: str = "默认写实"
    default_storyboard_mode: str = STORYBOARD_MODE_COMIC
    workflow_settings_json: Optional[Dict[str, Any]] = None
    openMode: Optional[str] = None


class ProjectEpisodeCreateRequest(BaseModel):
    episodeNo: Optional[int] = None
    title: str
    rawScript: Optional[str] = None
    insertAfterEpisodeId: Optional[str] = None


class EpisodeScriptPatchRequest(BaseModel):
    rawScript: str
    updatedAt: Optional[str] = None


class AssetPatchRequest(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    negativePrompt: Optional[str] = None
    sortOrder: Optional[int] = None
    updatedAt: Optional[str] = None


class StoryboardShotPatchRequest(BaseModel):
    shotNo: Optional[str] = None
    description: Optional[str] = None
    imagePrompt: Optional[str] = None
    videoPrompt: Optional[str] = None
    durationSec: Optional[float] = None
    sortOrder: Optional[int] = None
    updatedAt: Optional[str] = None


class GenerationUnitCreateRequest(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    negativePrompt: Optional[str] = None
    modelId: Optional[str] = None
    params: Dict[str, Any] = PydanticField(default_factory=dict)


class GenerationUnitInputCreateRequest(BaseModel):
    sourceUnitId: Optional[str] = None
    sourceMediaId: Optional[str] = None
    inputType: str
    role: Optional[str] = None
    weight: Optional[float] = None
    sortOrder: Optional[int] = None


class GenerationUnitRunRequest(BaseModel):
    prompt: Optional[str] = None
    modelId: Optional[str] = None
    params: Dict[str, Any] = PydanticField(default_factory=dict)


class CanvasNodeVisibilityRequest(BaseModel):
    hidden: bool = True


# ==========================================
# Sluvo 独立画布相关
# ==========================================

SLUVO_PROJECT_STATUS_ACTIVE = "active"
SLUVO_PROJECT_STATUS_ARCHIVED = "archived"
SLUVO_PROJECT_STATUS_DELETED = "deleted"
VALID_SLUVO_PROJECT_STATUSES = {
    SLUVO_PROJECT_STATUS_ACTIVE,
    SLUVO_PROJECT_STATUS_ARCHIVED,
    SLUVO_PROJECT_STATUS_DELETED,
}
SLUVO_PROJECT_VISIBILITY_PRIVATE = "private"
SLUVO_PROJECT_VISIBILITY_MEMBERS = "project_members"
SLUVO_PROJECT_VISIBILITY_TEAM = "team"
VALID_SLUVO_PROJECT_VISIBILITIES = {
    SLUVO_PROJECT_VISIBILITY_PRIVATE,
    SLUVO_PROJECT_VISIBILITY_MEMBERS,
    SLUVO_PROJECT_VISIBILITY_TEAM,
}
SLUVO_MEMBER_ROLE_OWNER = "owner"
SLUVO_MEMBER_ROLE_EDITOR = "editor"
SLUVO_MEMBER_ROLE_VIEWER = "viewer"
VALID_SLUVO_MEMBER_ROLES = {
    SLUVO_MEMBER_ROLE_OWNER,
    SLUVO_MEMBER_ROLE_EDITOR,
    SLUVO_MEMBER_ROLE_VIEWER,
}
VALID_SLUVO_NODE_TYPES = {"text", "image", "video", "audio", "upload", "generation", "agent", "group", "note"}
VALID_SLUVO_EDGE_TYPES = {"reference", "dependency", "generation", "sequence", "group", "custom"}
VALID_SLUVO_AGENT_ACTION_STATUSES = {"proposed", "approved", "running", "succeeded", "failed", "cancelled"}
VALID_SLUVO_AGENT_MODEL_CODES = {"deepseek-v4-flash", "deepseek-v4-pro"}
SLUVO_COMMUNITY_CANVAS_STATUS_PUBLISHED = "published"
SLUVO_COMMUNITY_CANVAS_STATUS_UNPUBLISHED = "unpublished"
SLUVO_COMMUNITY_AGENT_STATUS_PUBLISHED = "published"
SLUVO_COMMUNITY_AGENT_STATUS_UNPUBLISHED = "unpublished"


def normalize_sluvo_project_status(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_SLUVO_PROJECT_STATUSES else SLUVO_PROJECT_STATUS_ACTIVE


def normalize_sluvo_project_visibility(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_SLUVO_PROJECT_VISIBILITIES else SLUVO_PROJECT_VISIBILITY_MEMBERS


def normalize_sluvo_member_role(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_SLUVO_MEMBER_ROLES else SLUVO_MEMBER_ROLE_VIEWER


def normalize_sluvo_node_type(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_SLUVO_NODE_TYPES else "text"


def normalize_sluvo_edge_type(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_SLUVO_EDGE_TYPES else "custom"


def normalize_sluvo_agent_model_code(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_SLUVO_AGENT_MODEL_CODES else "deepseek-v4-flash"


class SluvoProjectCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    visibility: str = SLUVO_PROJECT_VISIBILITY_MEMBERS
    settings: Dict[str, Any] = PydanticField(default_factory=dict)
    coverUrl: Optional[str] = None


class SluvoProjectUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    visibility: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    coverUrl: Optional[str] = None


class SluvoCommunityCanvasPublishRequest(BaseModel):
    title: str
    description: Optional[str] = None
    tags: List[str] = PydanticField(default_factory=list)
    coverUrl: Optional[str] = None


class SluvoAgentTemplateCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    avatarUrl: Optional[str] = None
    coverUrl: Optional[str] = None
    profileKey: str = "custom_agent"
    modelCode: str = "deepseek-v4-flash"
    rolePrompt: str = ""
    useCases: List[str] = PydanticField(default_factory=list)
    inputTypes: List[str] = PydanticField(default_factory=list)
    outputTypes: List[str] = PydanticField(default_factory=list)
    tools: List[str] = PydanticField(default_factory=list)
    approvalPolicy: Dict[str, Any] = PydanticField(default_factory=dict)
    examples: List[Dict[str, Any]] = PydanticField(default_factory=list)


class SluvoAgentTemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    avatarUrl: Optional[str] = None
    coverUrl: Optional[str] = None
    profileKey: Optional[str] = None
    modelCode: Optional[str] = None
    rolePrompt: Optional[str] = None
    useCases: Optional[List[str]] = None
    inputTypes: Optional[List[str]] = None
    outputTypes: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    approvalPolicy: Optional[Dict[str, Any]] = None
    examples: Optional[List[Dict[str, Any]]] = None
    memory: Optional[Dict[str, Any]] = None


class SluvoCommunityAgentPublishRequest(BaseModel):
    title: str
    description: Optional[str] = None
    tags: List[str] = PydanticField(default_factory=list)
    coverUrl: Optional[str] = None


class SluvoProjectMemberCreateRequest(BaseModel):
    userId: Optional[str] = None
    email: Optional[str] = None
    role: str = SLUVO_MEMBER_ROLE_VIEWER


class SluvoProjectMemberUpdateRequest(BaseModel):
    role: str


class SluvoCanvasPatchRequest(BaseModel):
    expectedRevision: Optional[int] = None
    title: Optional[str] = None
    viewport: Optional[Dict[str, Any]] = None
    snapshot: Optional[Dict[str, Any]] = None
    schemaVersion: Optional[int] = None


class SluvoCanvasNodeCreateRequest(BaseModel):
    parentNodeId: Optional[str] = None
    nodeType: str = "text"
    title: str = ""
    position: Dict[str, float] = PydanticField(default_factory=dict)
    size: Optional[Dict[str, float]] = None
    zIndex: int = 0
    rotation: float = 0.0
    status: str = "idle"
    hidden: bool = False
    locked: bool = False
    collapsed: bool = False
    data: Dict[str, Any] = PydanticField(default_factory=dict)
    ports: Dict[str, Any] = PydanticField(default_factory=dict)
    aiConfig: Dict[str, Any] = PydanticField(default_factory=dict)
    style: Dict[str, Any] = PydanticField(default_factory=dict)


class SluvoCanvasNodeUpdateRequest(BaseModel):
    expectedRevision: Optional[int] = None
    parentNodeId: Optional[str] = None
    nodeType: Optional[str] = None
    title: Optional[str] = None
    position: Optional[Dict[str, float]] = None
    size: Optional[Dict[str, float]] = None
    zIndex: Optional[int] = None
    rotation: Optional[float] = None
    status: Optional[str] = None
    hidden: Optional[bool] = None
    locked: Optional[bool] = None
    collapsed: Optional[bool] = None
    data: Optional[Dict[str, Any]] = None
    ports: Optional[Dict[str, Any]] = None
    aiConfig: Optional[Dict[str, Any]] = None
    style: Optional[Dict[str, Any]] = None
    deleted: Optional[bool] = None


class SluvoCanvasEdgeCreateRequest(BaseModel):
    sourceNodeId: str
    targetNodeId: str
    sourcePortId: Optional[str] = None
    targetPortId: Optional[str] = None
    edgeType: str = "custom"
    label: Optional[str] = None
    data: Dict[str, Any] = PydanticField(default_factory=dict)
    style: Dict[str, Any] = PydanticField(default_factory=dict)
    hidden: bool = False


class SluvoCanvasEdgeUpdateRequest(BaseModel):
    expectedRevision: Optional[int] = None
    sourceNodeId: Optional[str] = None
    targetNodeId: Optional[str] = None
    sourcePortId: Optional[str] = None
    targetPortId: Optional[str] = None
    edgeType: Optional[str] = None
    label: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    style: Optional[Dict[str, Any]] = None
    hidden: Optional[bool] = None
    deleted: Optional[bool] = None


class SluvoCanvasBatchRequest(BaseModel):
    expectedRevision: Optional[int] = None
    title: Optional[str] = None
    viewport: Optional[Dict[str, Any]] = None
    snapshot: Optional[Dict[str, Any]] = None
    nodes: List[Dict[str, Any]] = PydanticField(default_factory=list)
    edges: List[Dict[str, Any]] = PydanticField(default_factory=list)
    deletedNodeIds: List[str] = PydanticField(default_factory=list)
    deletedEdgeIds: List[str] = PydanticField(default_factory=list)


class SluvoCanvasAssetBase64UploadRequest(BaseModel):
    filename: str
    contentType: str
    dataBase64: str
    mediaType: Optional[str] = None
    nodeId: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    durationSeconds: Optional[float] = None
    metadata: Dict[str, Any] = PydanticField(default_factory=dict)


class SluvoAgentSessionCreateRequest(BaseModel):
    canvasId: Optional[str] = None
    targetNodeId: Optional[str] = None
    title: Optional[str] = None
    agentProfile: str = "canvas_agent"
    modelCode: str = "deepseek-v4-flash"
    mode: str = "semi_auto"
    contextSnapshot: Dict[str, Any] = PydanticField(default_factory=dict)


class SluvoAgentRunCreateRequest(BaseModel):
    canvasId: Optional[str] = None
    targetNodeId: Optional[str] = None
    goal: str
    sourceSurface: str = "panel"
    agentProfile: str = "auto"
    agentTemplateId: Optional[str] = None
    modelCode: str = "deepseek-v4-flash"
    mode: str = "semi_auto"
    contextSnapshot: Dict[str, Any] = PydanticField(default_factory=dict)


class SluvoAgentRunContinueRequest(BaseModel):
    content: str
    contextSnapshot: Dict[str, Any] = PydanticField(default_factory=dict)


class SluvoAgentRunConfirmCostRequest(BaseModel):
    artifactIds: List[str] = PydanticField(default_factory=list)
    confirmed: bool = True


class SluvoAgentMessageSendRequest(BaseModel):
    content: Optional[str] = None
    payload: Dict[str, Any] = PydanticField(default_factory=dict)
    turnId: Optional[str] = None
    proposedAction: Optional[Dict[str, Any]] = None


class SluvoTextNodeAnalyzeRequest(BaseModel):
    nodeTitle: Optional[str] = None
    content: Optional[str] = None
    instruction: Optional[str] = None
    modelCode: str = "deepseek-v4-flash"


# ==========================================
# 统一 Assistant Runtime v2 相关
# ==========================================

class AssistantSessionCreateRequest(BaseModel):
    episode_id: Optional[str] = None
    title: Optional[str] = None
    channel: str = "internal"
    profile: str = "director"
    linked_external_session_id: Optional[str] = None


class AssistantSessionUpdateRequest(BaseModel):
    episode_id: Optional[str] = None
    automation_mode: Optional[str] = None  # auto / semi / step


class AssistantAttachmentPayload(BaseModel):
    type: str = "image"
    url: str
    thumbnail_url: Optional[str] = None
    name: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    metadata: Dict[str, Any] = PydanticField(default_factory=dict)


class AssistantMessageSendRequest(BaseModel):
    content: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    target: Optional[str] = None
    attachments: List[AssistantAttachmentPayload] = PydanticField(default_factory=list)


class AssistantQuestionAnswerRequest(BaseModel):
    action: str = "confirm"
    answer: Optional[str] = None
    modifications: Optional[Dict[str, Any]] = None
    answers: Dict[str, Any] = PydanticField(default_factory=dict)


class AssistantAgentActionRequest(BaseModel):
    action_type: str
    payload: Dict[str, Any] = PydanticField(default_factory=dict)


class AssistantBridgeLinkRequest(BaseModel):
    external_session_id: Optional[str] = None


class AssistantBridgeImportRequest(BaseModel):
    import_type: str
    mode: Optional[str] = None
    episode_id: Optional[str] = None
    name: Optional[str] = None
    external_session_id: Optional[str] = None


class AgentWorkflowMutationRequest(BaseModel):
    instruction: Optional[str] = None


class AgentWorkflowConfirmRequest(BaseModel):
    action: str = "confirm"
    instruction: Optional[str] = None


# ==========================================
# 神鹿AI导演 Agent 相关
# ==========================================

class DirectorAgentSessionCreateRequest(BaseModel):
    script_id: str
    episode_id: Optional[str] = None
    title: Optional[str] = None


class DirectorAgentSessionUpdateRequest(BaseModel):
    episode_id: Optional[str] = None
    title: Optional[str] = None


class DirectorAgentMessageSendRequest(BaseModel):
    content: str
    context: Optional[Dict[str, Any]] = None


class DirectorAgentMessageConfirmRequest(BaseModel):
    action: str  # confirm/reject
    modifications: Optional[Dict[str, Any]] = None


class DirectorAgentContextResponse(BaseModel):
    script: Dict[str, Any]
    episode: Optional[Dict[str, Any]] = None
    panels_summary: Dict[str, Any]
    shared_resources: Dict[str, Any]
    missing_context: List[str]


class DirectorAgentMessagePayload(BaseModel):
    task_type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    estimated_items: Optional[int] = None
    estimated_cost: Optional[int] = None
    requires_confirmation: Optional[bool] = None
    preview: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    items_created: Optional[int] = None
    warnings: Optional[List[str]] = None
    next_actions: Optional[List[Dict[str, Any]]] = None
    action_type: Optional[str] = None
    impact: Optional[Dict[str, Any]] = None
    confirmation_id: Optional[str] = None
    expires_at: Optional[str] = None
