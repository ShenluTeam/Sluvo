from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import BigInteger, Boolean, Column, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from datetime import datetime, date
from enum import Enum
import uuid

# ==========================================
# 0. 枚举类型定义 (增强数据约束)
# ==========================================
class RoleEnum(str, Enum):
    ADMIN = "admin"       # 管理员/主理人(最高权限，财务与人员管理)
    DIRECTOR = "director" # 导演/剪辑师(可创建分镜、修改所有镜头)
    EDITOR = "editor"     # 创作者/员工(只能编辑被分配的特定剧本/剧集)
    VIEWER = "viewer"     # 审阅人/资方(仅限预览，无法生成和消耗算力)

class InvitationStatusEnum(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"

class ResourceTypeEnum(str, Enum):
    LORA = "lora"               # 风格/角色 Lora 模型
    CHARACTER_REF = "character" # 角色三视图/设定图
    SCENE_REF = "scene"         # 场景参考图
    PROP_REF = "prop"           # 道具参考图

class TaskStatusEnum(str, Enum):
    IDLE = "idle" 
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class VIPTierEnum(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    TEAM = "team"

class OrderStatusEnum(str, Enum):
    PENDING = "pending"     # 待支付
    PAID = "paid"           # 已支付
    CANCELLED = "cancelled" # 已取消/超时

# ==========================================
# 1. 用户与团队(多租户权限体系)
# ==========================================

class TeamMemberLink(SQLModel, table=True):
    team_id: Optional[int] = Field(default=None, foreign_key="team.id", primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", primary_key=True)
    role: RoleEnum = Field(default=RoleEnum.EDITOR) # 默认给较低权限，防越权
    point_quota: Optional[int] = Field(default=None)  # Max points this member can consume. None means unlimited.
    point_quota_used: int = Field(default=0)          # Accumulated consumed points for quota control.
    joined_at: datetime = Field(default_factory=datetime.utcnow)

class User(SQLModel, table=True):
    # --- 1. 核心主键 ---
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # --- 2. 基础账号信息 ---
    email: str = Field(unique=True, index=True)
    hashed_password: str
    session_token: Optional[str] = Field(default=None, index=True, unique=True)
    storage_namespace: Optional[str] = Field(default=None, sa_column=Column(String(64), unique=True, nullable=True, index=True))
    email_verified: bool = Field(default=False) # 邮箱是否已验证
    
    # --- 3. 用户资料库 ---
    nickname: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = Field(default=None) 
    
    # --- 4. 商业化钱币(双轨制灵感值) ---
    permanent_points: int = Field(default=0) # 用户起步额度 (永久有效)
    temporary_points: int = Field(default=0)   # 临时灵感值(每日盲盒/邀请奖励)
    temporary_expire_at: Optional[datetime] = Field(default=None) # 临时点数过期时间
    
    # --- 5. 增长黑客与拉新 ---
    invite_code: str = Field(default_factory=lambda: str(uuid.uuid4().hex)[:8], unique=True, index=True)
    invited_by: Optional[str] = Field(default=None) # 记录是谁拉他注册的
    last_daily_bonus_date: Optional[date] = Field(default=None) # 记录最后一次抽每日盲盒的日期
    
    # --- 6. 会员权益体系 ---
    vip_tier: VIPTierEnum = Field(default=VIPTierEnum.FREE)
    vip_expire_time: Optional[datetime] = Field(default=None)
    last_vip_grant_date: Optional[date] = Field(default=None) # 记录上个月是否已经发过VIP定额积分
    
    # --- 7. 第三方绑定与系统管控 ---
    wechat_openid: Optional[str] = Field(default=None, unique=True, index=True) 
    phone_number: Optional[str] = Field(default=None, unique=True, index=True)  
    is_active: bool = Field(default=True) 
    last_login_at: Optional[datetime] = Field(default=None) 
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # 【新增】风控和系统管理后台字段
    register_ip: Optional[str] = Field(default=None)
    last_login_ip: Optional[str] = Field(default=None)
    is_superadmin: bool = Field(default=False)
    
    # --- 8. 关联关系 ---
    teams: List["Team"] = Relationship(back_populates="members", link_model=TeamMemberLink)
    orders: List["Order"] = Relationship(back_populates="user")
    point_logs: List["PointLog"] = Relationship(back_populates="user")

class Team(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    
    # --- 团队版核心：公对公算力池 ---
    is_team_billing: bool = Field(default=False) # 开启后，团队成员消耗扣除这里的积分
    team_points: int = Field(default=0)          # 团队公有资产池
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # 关联关系
    members: List[User] = Relationship(back_populates="teams", link_model=TeamMemberLink)
    scripts: List["Script"] = Relationship(back_populates="team", cascade_delete=True)
    point_logs: List["PointLog"] = Relationship(back_populates="team")

class TeamInvitation(SQLModel, table=True):
    __tablename__ = "team_invitation"

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    token: str = Field(default_factory=lambda: uuid.uuid4().hex, unique=True, index=True)
    role: RoleEnum = Field(default=RoleEnum.EDITOR)
    target_email: Optional[str] = Field(default=None, index=True)
    invited_by_user_id: int = Field(foreign_key="user.id", index=True)
    accepted_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    status: InvitationStatusEnum = Field(default=InvitationStatusEnum.PENDING, index=True)
    expire_at: datetime
    accepted_at: Optional[datetime] = Field(default=None)
    revoked_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ==========================================
# 2. 订单与账单流水(商业化闭环基础)
# ==========================================

class Order(SQLModel, table=True):
    """充值订单表：灵活定价，不写死任何价格，全看实际支付"""
    id: Optional[int] = Field(default=None, primary_key=True)
    order_no: str = Field(default_factory=lambda: f"ORD{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6]}", unique=True, index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    
    package_name: str # 例如: "爆肝创作包", "Pro连续包月"
    pay_amount: float # 实际支付的人民币金额
    points_added: int # 本次充值实际发放的灵感值总量
    
    status: OrderStatusEnum = Field(default=OrderStatusEnum.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    paid_at: Optional[datetime] = Field(default=None)
    
    user: User = Relationship(back_populates="orders")

class PointLog(SQLModel, table=True):
    """Points ledger for every consume/income action."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    team_id: Optional[int] = Field(default=None, foreign_key="team.id", index=True)
    
    change_amount: int # 正数为增加(如+100)，负数为消耗(如-30)
    balance_after: int # 变动后的钱包余额
    action_type: str   # 例如: "daily_bonus"(每日盲盒), "generate_video"(视频生成), "top_up"(充值)
    description: str   # 例如: "调用Veo生成大明崇祯纪事第1集第5镜"
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: Optional[User] = Relationship(back_populates="point_logs")
    team: Optional[Team] = Relationship(back_populates="point_logs")

# ==========================================
# 3. 漫剧生产流：剧本 -> 剧集 -> 分镜
# ==========================================

class Script(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    name: str
    description: Optional[str] = None
    source_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    openclaw_settings_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    workflow_settings_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    aspect_ratio: str = Field(default="16:9")
    style_preset: str = Field(default="默认写实")
    last_accessed_at: Optional[datetime] = Field(default_factory=datetime.utcnow, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    team: Team = Relationship(back_populates="scripts")
    episodes: List["Episode"] = Relationship(back_populates="script", cascade_delete=True)
    shared_resources: List["SharedResource"] = Relationship(back_populates="script", cascade_delete=True)

class Episode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    sequence_num: int = Field(default=1) 
    title: str
    source_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    storyboard_mode: str = Field(default="commentary", sa_column=Column(String(32), nullable=False, index=True))
    workflow_override_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    composed_video_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    composed_video_thumbnail_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    composed_video_updated_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    script: Script = Relationship(back_populates="episodes")
    panels: List["Panel"] = Relationship(back_populates="episode", cascade_delete=True)


class ScriptWorkflowState(SQLModel, table=True):
    __tablename__ = "script_workflow_state"
    __table_args__ = (UniqueConstraint("script_id", name="uq_script_workflow_state_script_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    current_stage: str = Field(default="INIT", sa_column=Column(String(64), nullable=False, index=True))
    stage_status: str = Field(default="idle", sa_column=Column(String(32), nullable=False, index=True))
    current_step_key: str = Field(default="demand_understanding", sa_column=Column(String(64), nullable=False, index=True))
    mode: str = Field(default="semi_auto", sa_column=Column(String(32), nullable=False, index=True))
    pause_policy: str = Field(default="stage_boundary_and_cost", sa_column=Column(String(64), nullable=False))
    pending_confirmation_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    result_summary_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    result_detail_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    quality_assessment_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    recommended_actions_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    adjustment_actions_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    history_versions_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    last_agent_run_at: Optional[datetime] = Field(default=None, index=True)
    last_user_decision_at: Optional[datetime] = Field(default=None, index=True)
    version: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class EpisodeWorkflowState(SQLModel, table=True):
    __tablename__ = "episode_workflow_state"
    __table_args__ = (UniqueConstraint("episode_id", name="uq_episode_workflow_state_episode_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    episode_id: int = Field(foreign_key="episode.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    current_stage: str = Field(default="ASSET_EXTRACTION", sa_column=Column(String(64), nullable=False, index=True))
    stage_status: str = Field(default="idle", sa_column=Column(String(32), nullable=False, index=True))
    current_step_key: str = Field(default="asset_extraction", sa_column=Column(String(64), nullable=False, index=True))
    mode: str = Field(default="semi_auto", sa_column=Column(String(32), nullable=False, index=True))
    pause_policy: str = Field(default="stage_boundary_and_cost", sa_column=Column(String(64), nullable=False))
    pending_confirmation_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    result_summary_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    result_detail_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    quality_assessment_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    recommended_actions_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    adjustment_actions_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    history_versions_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    last_agent_run_at: Optional[datetime] = Field(default=None, index=True)
    last_user_decision_at: Optional[datetime] = Field(default=None, index=True)
    version: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

class ExtraImage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: int = Field(index=True)
    image_base64: str = Field(sa_column=Column(LONGTEXT))

class Panel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: int = Field(foreign_key="episode.id", index=True)
    sequence_num: int = Field(default=1) 
    task_id: Optional[str] = Field(default=None, index=True)
    title: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    scene: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    character: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    prop: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    panel_type: Optional[str] = Field(default=None, sa_column=Column(String(32), nullable=True))
    storyboard_mode: str = Field(default="commentary", sa_column=Column(String(32), nullable=False, index=True))
    text_span_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    recommended_duration_seconds: int = Field(default=6)
    grid_count: int = Field(default=1, index=True)
    pacing: Optional[str] = Field(default=None, sa_column=Column(String(32)))
    rhythm: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    continuity_note: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    scene_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    multi_shot_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    multi_shot_video_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    reference_assets_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    reference_images_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    auto_asset_reference_enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    segment_no: Optional[int] = Field(default=None, index=True)
    segment_summary: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    narrative_purpose: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    panel_type_reason: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    segment_prompt_summary: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    narration_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    dialogue_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    segment_break: bool = Field(default=False, index=True)
    dependency_panel_id: Optional[int] = Field(default=None, index=True)
    shot_type: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    camera_motion: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    composition: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    previous_storyboard_path: Optional[str] = Field(default=None, sa_column=Column(String(512)))
    transition_to_next: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    image_framing: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    video_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    nine_grid_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    original_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    entity_bindings_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    current_revision_id: Optional[int] = Field(default=None, index=True)
    prompt: str = Field(default="") 
    prompt_zh: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    negative_prompt: Optional[str] = None
    status: TaskStatusEnum = Field(default=TaskStatusEnum.IDLE)
    generation_status: str = Field(default="idle", sa_column=Column(String(32), nullable=False, index=True))
    image_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    video_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))  # ===== NEW: 视频链接 =====
    file_url: Optional[str] = Field(default=None, sa_column=Column(String(255))) 
    thumbnail_url: Optional[str] = Field(default=None, sa_column=Column(String(255))) 
    video_thumbnail_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    transfer_status: int = Field(default=0) # 0=初始状态 1=已生成临时链接 2=转存OSS中 3=完成持久化
    history_urls_json: str = Field(default="[]", sa_column=Column(LONGTEXT)) 
    video_history_json: str = Field(default="[]", sa_column=Column(LONGTEXT)) 
    note: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    episode: Episode = Relationship(back_populates="panels")
    revisions: List["PanelRevision"] = Relationship(back_populates="panel", cascade_delete=True)
    grid_cells: List["PanelGridCell"] = Relationship(back_populates="panel", cascade_delete=True)

# ==========================================
# 4. 核心痛点：全局共享资源库
# ==========================================

class SharedResource(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    resource_type: str = Field(sa_column=Column(String(32), nullable=False))
    name: str                            
    file_url: str
    thumbnail_url: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    aliases: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    storage_object_key: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    original_filename: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    mime_type: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    file_size: Optional[int] = Field(default=None)
    trigger_word: Optional[str] = None   
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    script: Script = Relationship(back_populates="shared_resources")
    versions: List["SharedResourceVersion"] = Relationship(back_populates="resource", cascade_delete=True)


class SharedResourceVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    resource_id: int = Field(foreign_key="sharedresource.id", index=True)
    version_tag: str = Field(default="v1", sa_column=Column(String(100)))
    appearance_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    file_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    trigger_word: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    start_seq: Optional[int] = Field(default=None)
    end_seq: Optional[int] = Field(default=None)
    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    resource: SharedResource = Relationship(back_populates="versions")


class PanelRevision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    panel_id: int = Field(foreign_key="panel.id", index=True)
    revision_no: int = Field(default=1, index=True)
    source: str = Field(default="content", sa_column=Column(String(32)))
    title: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    scene: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    character: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    prop: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    panel_type: Optional[str] = Field(default=None, sa_column=Column(String(32), nullable=True))
    storyboard_mode: str = Field(default="commentary", sa_column=Column(String(32), nullable=False, index=True))
    text_span_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    recommended_duration_seconds: int = Field(default=6)
    grid_count: int = Field(default=1, index=True)
    pacing: Optional[str] = Field(default=None, sa_column=Column(String(32)))
    rhythm: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    continuity_note: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    scene_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    multi_shot_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    multi_shot_video_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    reference_assets_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    reference_images_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    auto_asset_reference_enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    segment_no: Optional[int] = Field(default=None, index=True)
    segment_summary: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    narrative_purpose: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    panel_type_reason: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    segment_prompt_summary: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    narration_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    dialogue_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    segment_break: bool = Field(default=False, index=True)
    dependency_panel_id: Optional[int] = Field(default=None, index=True)
    shot_type: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    camera_motion: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    composition: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    previous_storyboard_path: Optional[str] = Field(default=None, sa_column=Column(String(512)))
    transition_to_next: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    prompt: str = Field(default="", sa_column=Column(LONGTEXT))
    nine_grid_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    video_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    image_framing: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    original_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    entity_bindings_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    generation_status: str = Field(default="idle", sa_column=Column(String(32), nullable=False, index=True))
    note: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    panel: Panel = Relationship(back_populates="revisions")


class PanelGridCell(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    panel_id: int = Field(foreign_key="panel.id", index=True)
    cell_index: int = Field(default=1, index=True)
    start_second: float = Field(default=0.0, sa_column=Column(Float, nullable=False, default=0.0))
    end_second: float = Field(default=0.0, sa_column=Column(Float, nullable=False, default=0.0))
    duration_seconds: float = Field(default=0.0, sa_column=Column(Float, nullable=False, default=0.0))
    shot_description: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    action_description: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    dialogue_excerpt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    speech_items_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    performance_focus: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    mouth_sync_required: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    shot_type: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    camera_motion: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    composition: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    lighting: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    ambiance: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    camera_position: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    camera_direction: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    shot_purpose: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    image_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    video_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    image_prompt_structured_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    video_prompt_structured_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    character_refs_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    scene_refs_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    prop_refs_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    asset_status: str = Field(default="idle", sa_column=Column(String(32), nullable=False, index=True))
    image_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    image_history_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    video_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    video_thumbnail_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    video_history_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    binding_suggestions_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    note: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    panel: Panel = Relationship(back_populates="grid_cells")

# ==========================================
# 5. 生图通道与定价配置表
# ==========================================
class ChannelSettings(SQLModel, table=True):
    """Configurable generation channels and pricing."""
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: str = Field(unique=True, index=True)  # 例如: "nano-banana-pro"
    name: str                                         # 例如: "达卡 NB 普通"
    description: Optional[str] = None
    cost_points: int = Field(default=3)               # 每次调用消耗的基础灵感值
    is_active: bool = Field(default=True)             # 是否在前端展示并可用
    is_vip_only: bool = Field(default=False)          # 是否仅限VIP使用
    sort_order: int = Field(default=0)                # 排序权重
    created_at: datetime = Field(default_factory=datetime.utcnow)

# ==========================================
# 6. 邮箱验证码
# ==========================================
class EmailVerificationCode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    code: str
    purpose: str = Field(default="register", index=True)
    expire_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExternalProviderCredential(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    token_encrypted: str = Field(sa_column=Column(LONGTEXT))
    token_masked: str = Field(sa_column=Column(String(255), nullable=False))
    token_hash: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    token_prefix: Optional[str] = Field(default=None, sa_column=Column(String(24), index=True))
    is_active: bool = Field(default=True, index=True)
    openclaw_api_enabled: bool = Field(default=False, index=True)
    expires_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExternalAgentSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    episode_id: Optional[int] = Field(default=None, foreign_key="episode.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    base_id: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    base_name: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    provider_episode_id: Optional[str] = Field(default=None, sa_column=Column(String(255), index=True))
    session_id: Optional[str] = Field(default=None, sa_column=Column(String(255), index=True))
    settings_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    workspace_snapshot_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    last_reply_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    status: str = Field(default="idle", sa_column=Column(String(64), nullable=False, index=True))
    is_active: bool = Field(default=False, index=True)
    last_synced_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExternalAgentMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_ref_id: int = Field(foreign_key="externalagentsession.id", index=True)
    role: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    message: str = Field(default="", sa_column=Column(LONGTEXT))
    reply_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    reply_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    actions_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    workspace_snapshot_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExternalAgentFileMapping(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_ref_id: int = Field(foreign_key="externalagentsession.id", index=True)
    provider_file_id: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    provider_docu_type: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    provider_name: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    internal_target_type: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    internal_target_id: Optional[int] = Field(default=None, index=True)
    snapshot_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GenerationRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    record_type: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    ownership_mode: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    script_id: Optional[int] = Field(default=None, foreign_key="script.id", index=True)
    episode_id: Optional[int] = Field(default=None, foreign_key="episode.id", index=True)
    target_type: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    target_id: Optional[int] = Field(default=None, index=True)
    task_id: Optional[str] = Field(default=None, sa_column=Column(String(255), index=True))
    status: str = Field(default="queued", sa_column=Column(String(32), nullable=False, index=True))
    preview_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    thumbnail_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    prompt: str = Field(default="", sa_column=Column(LONGTEXT))
    negative_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    params_internal_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    params_public_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    estimate_points: Optional[int] = Field(default=None)
    actual_points: Optional[int] = Field(default=None)
    points_status: Optional[str] = Field(default="free", sa_column=Column(String(32), nullable=True))
    error_code_public: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    error_message_public: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    error_message_internal: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class VoiceAsset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider_voice_id: str = Field(sa_column=Column(String(255), nullable=False, unique=True, index=True))
    voice_type: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    source_type: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    display_name: str = Field(sa_column=Column(String(255), nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    preview_audio_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    created_at_source: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    last_used_at: Optional[datetime] = Field(default=None, index=True)
    activation_billed_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class TemporaryUploadAsset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content_hash: str = Field(sa_column=Column(String(64), nullable=False, unique=True, index=True))
    media_type: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    storage_object_key: str = Field(sa_column=Column(String(255), nullable=False, unique=True))
    file_url: str = Field(sa_column=Column(LONGTEXT))
    thumbnail_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    original_filename: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    mime_type: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    file_size: int = Field(default=0)
    duration_seconds: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    has_audio: Optional[bool] = Field(default=None, sa_column=Column(Boolean, nullable=True))
    width: Optional[int] = Field(default=None, nullable=True)
    height: Optional[int] = Field(default=None, nullable=True)
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class StorageObject(SQLModel, table=True):
    __tablename__ = "storage_object"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)
    object_key: str = Field(sa_column=Column(String(512), nullable=False, unique=True, index=True))
    old_object_key: Optional[str] = Field(default=None, sa_column=Column(String(512), nullable=True, index=True))
    media_type: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    file_size: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0))
    status: str = Field(default="active", sa_column=Column(String(32), nullable=False, index=True))
    source_type: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
    source_id: Optional[int] = Field(default=None, index=True)
    old_deleted_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class UserStorageUsage(SQLModel, table=True):
    __tablename__ = "user_storage_usage"

    user_id: int = Field(foreign_key="user.id", primary_key=True)
    used_bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0))
    reserved_bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0))
    quota_bytes_snapshot: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class EpisodeAssetLink(SQLModel, table=True):
    __tablename__ = "episode_asset_link"
    __table_args__ = (UniqueConstraint("episode_id", "resource_id", name="uq_episode_asset_link_episode_resource"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    episode_id: int = Field(foreign_key="episode.id", index=True)
    resource_id: int = Field(foreign_key="sharedresource.id", index=True)
    sort_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class StoryboardShotAssetLink(SQLModel, table=True):
    __tablename__ = "storyboard_shot_asset_link"
    __table_args__ = (UniqueConstraint("panel_id", "resource_id", name="uq_storyboard_shot_asset_link_panel_resource"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    episode_id: int = Field(foreign_key="episode.id", index=True)
    panel_id: int = Field(foreign_key="panel.id", index=True)
    resource_id: int = Field(foreign_key="sharedresource.id", index=True)
    role: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    sort_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class MediaAsset(SQLModel, table=True):
    __tablename__ = "media_asset"

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    media_type: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    url: str = Field(sa_column=Column(LONGTEXT, nullable=False))
    thumbnail_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    width: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    height: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    duration_seconds: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    source_record_id: Optional[int] = Field(default=None, foreign_key="generationrecord.id", index=True)
    metadata_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class GenerationUnit(SQLModel, table=True):
    __tablename__ = "generation_unit"

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    episode_id: Optional[int] = Field(default=None, foreign_key="episode.id", index=True)
    unit_type: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    owner_type: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
    owner_id: Optional[int] = Field(default=None, index=True)
    prompt: str = Field(default="", sa_column=Column(LONGTEXT))
    negative_prompt: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    model_id: Optional[str] = Field(default=None, sa_column=Column(String(128), nullable=True))
    params_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    status: str = Field(default="empty", sa_column=Column(String(32), nullable=False, index=True))
    current_media_id: Optional[int] = Field(default=None, foreign_key="media_asset.id", index=True)
    generation_record_id: Optional[int] = Field(default=None, foreign_key="generationrecord.id", index=True)
    versions_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class GenerationUnitInput(SQLModel, table=True):
    __tablename__ = "generation_unit_input"

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    target_unit_id: int = Field(foreign_key="generation_unit.id", index=True)
    source_unit_id: Optional[int] = Field(default=None, foreign_key="generation_unit.id", index=True)
    source_media_id: Optional[int] = Field(default=None, foreign_key="media_asset.id", index=True)
    input_type: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    role: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
    weight: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    sort_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    metadata_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class DomainEvent(SQLModel, table=True):
    __tablename__ = "domain_event"

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    event_type: str = Field(sa_column=Column(String(128), nullable=False, index=True))
    entity_type: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    entity_id: int = Field(index=True)
    payload_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class MembershipPlan(SQLModel, table=True):
    __tablename__ = "membership_plan"

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(sa_column=Column(String(64), nullable=False, unique=True, index=True))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    status: str = Field(default="active", sa_column=Column(String(32), nullable=False, index=True))
    scope_type: str = Field(default="both", sa_column=Column(String(16), nullable=False, index=True))
    sort_order: int = Field(default=100, sa_column=Column(Integer, nullable=False, default=100))
    priority_default: int = Field(default=100, sa_column=Column(Integer, nullable=False, default=100))
    max_storyboard_concurrency: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    max_resource_concurrency: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    max_media_concurrency: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    max_audio_concurrency: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    storage_quota_bytes: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    description: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    is_default: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    is_builtin: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class UserMembership(SQLModel, table=True):
    __tablename__ = "user_membership"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    plan_id: int = Field(foreign_key="membership_plan.id", index=True)
    starts_at: Optional[datetime] = Field(default=None, index=True)
    expires_at: Optional[datetime] = Field(default=None, index=True)
    enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    remark: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class TeamMembership(SQLModel, table=True):
    __tablename__ = "team_membership"

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    plan_id: int = Field(foreign_key="membership_plan.id", index=True)
    starts_at: Optional[datetime] = Field(default=None, index=True)
    expires_at: Optional[datetime] = Field(default=None, index=True)
    enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    remark: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class UserMembershipOverride(SQLModel, table=True):
    __tablename__ = "user_membership_override"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True, unique=True)
    enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    effective_priority: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    max_storyboard_concurrency: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    max_resource_concurrency: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    max_media_concurrency: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    max_audio_concurrency: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    storage_quota_bytes: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    remark: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class TaskJob(SQLModel, table=True):
    __tablename__ = "task_job"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(sa_column=Column(String(64), nullable=False, unique=True, index=True))
    task_type: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    queue_name: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    status: str = Field(default="queued", sa_column=Column(String(32), nullable=False, index=True))
    priority: int = Field(default=100, sa_column=Column(Integer, nullable=False, default=100))
    provider: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    team_id: Optional[int] = Field(default=None, foreign_key="team.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    script_id: Optional[int] = Field(default=None, foreign_key="script.id", index=True)
    episode_id: Optional[int] = Field(default=None, foreign_key="episode.id", index=True)
    ownership_mode: Optional[str] = Field(default=None, sa_column=Column(String(32), index=True))
    scope_type: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    scope_id: Optional[int] = Field(default=None, index=True)
    task_category: Optional[str] = Field(default=None, sa_column=Column(String(32), index=True))
    membership_source: Optional[str] = Field(default=None, sa_column=Column(String(32), index=True))
    membership_plan_id: Optional[int] = Field(default=None, foreign_key="membership_plan.id", index=True)
    membership_plan_name: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    membership_subject_type: Optional[str] = Field(default=None, sa_column=Column(String(32), index=True))
    membership_subject_id: Optional[int] = Field(default=None, index=True)
    concurrency_limit: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    actual_cost_cny: Optional[float] = Field(default=0.0, sa_column=Column(Float, nullable=True))
    charged_points: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    actual_points: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    points_status: Optional[str] = Field(default="free", sa_column=Column(String(32), nullable=True, index=True))
    billing_detail_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    upstream_task_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    callback_token: Optional[str] = Field(default=None, sa_column=Column(String(128), nullable=True, index=True))
    next_poll_at: Optional[datetime] = Field(default=None, index=True)
    poll_attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    callback_received_at: Optional[datetime] = Field(default=None, index=True)
    generation_record_id: Optional[int] = Field(default=None, foreign_key="generationrecord.id", index=True)
    payload_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    result_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    progress: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    stage: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    message: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    error_code: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    error_message: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    retry_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    max_retries: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    scheduled_at: Optional[datetime] = Field(default=None, index=True)
    started_at: Optional[datetime] = Field(default=None, index=True)
    finished_at: Optional[datetime] = Field(default=None, index=True)
    heartbeat_at: Optional[datetime] = Field(default=None, index=True)
    lease_expires_at: Optional[datetime] = Field(default=None, index=True)
    worker_id: Optional[str] = Field(default=None, sa_column=Column(String(128), index=True))
    cancel_requested_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CreativeEditingDraft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    ownership_mode: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    script_id: Optional[int] = Field(default=None, foreign_key="script.id", index=True)
    episode_id: Optional[int] = Field(default=None, foreign_key="episode.id", index=True)
    document_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    version: int = Field(default=1, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# ==========================================
# 7.5 AI 原生无限画布
# ==========================================

class CanvasWorkspace(SQLModel, table=True):
    __tablename__ = "canvas_workspace"
    __table_args__ = (UniqueConstraint("script_id", name="uq_canvas_workspace_script_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    title: str = Field(default="AI 原生画布", sa_column=Column(String(255), nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    viewport_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CanvasNode(SQLModel, table=True):
    __tablename__ = "canvas_node"
    __table_args__ = (UniqueConstraint("workspace_id", "bootstrap_key", name="uq_canvas_node_workspace_bootstrap_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="canvas_workspace.id", index=True)
    type: str = Field(default="script", sa_column=Column(String(64), nullable=False, index=True))
    title: str = Field(default="", sa_column=Column(String(255), nullable=False))
    position_x: float = Field(default=0.0)
    position_y: float = Field(default=0.0)
    width: Optional[float] = Field(default=None)
    height: Optional[float] = Field(default=None)
    status: str = Field(default="idle", sa_column=Column(String(32), nullable=False, index=True))
    source_type: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    source_id: Optional[int] = Field(default=None, index=True)
    source_sub_id: Optional[int] = Field(default=None, index=True)
    bootstrap_key: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    sync_status: str = Field(default="clean", sa_column=Column(String(32), nullable=False, index=True))
    snapshot_version: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    source_version: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    source_updated_at: Optional[datetime] = Field(default=None, index=True)
    last_synced_at: Optional[datetime] = Field(default=None, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)
    domain_type: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
    domain_id: Optional[int] = Field(default=None, index=True)
    parent_node_id: Optional[int] = Field(default=None, foreign_key="canvas_node.id", index=True)
    collapsed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    hidden: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    locked: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1))
    data_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    context_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    ai_config_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    meta_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    view_data_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CanvasEdge(SQLModel, table=True):
    __tablename__ = "canvas_edge"

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="canvas_workspace.id", index=True)
    source_node_id: int = Field(foreign_key="canvas_node.id", index=True)
    target_node_id: int = Field(foreign_key="canvas_node.id", index=True)
    edge_type: str = Field(default="data_flow", sa_column=Column(String(64), nullable=False, index=True))
    source_port_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True, index=True))
    target_port_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True, index=True))
    role: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
    domain_type: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
    domain_id: Optional[int] = Field(default=None, index=True)
    is_projection: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    hidden: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    mapping_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    label: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    view_data_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# ==========================================
# 7.6 Sluvo 独立画布产品线
# ==========================================

class SluvoProject(SQLModel, table=True):
    __tablename__ = "sluvo_project"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    title: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    description: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    status: str = Field(default="active", sa_column=Column(String(32), nullable=False, index=True))
    visibility: str = Field(default="project_members", sa_column=Column(String(32), nullable=False, index=True))
    settings_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    cover_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    last_opened_at: Optional[datetime] = Field(default=None, index=True)
    deleted_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SluvoProjectMember(SQLModel, table=True):
    __tablename__ = "sluvo_project_member"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_sluvo_project_member_project_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="sluvo_project.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    role: str = Field(default="viewer", sa_column=Column(String(32), nullable=False, index=True))
    invited_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SluvoCanvas(SQLModel, table=True):
    __tablename__ = "sluvo_canvas"
    __table_args__ = (UniqueConstraint("project_id", "canvas_key", name="uq_sluvo_canvas_project_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="sluvo_project.id", index=True)
    canvas_key: str = Field(default="main", sa_column=Column(String(64), nullable=False, index=True))
    title: str = Field(default="Main Canvas", sa_column=Column(String(255), nullable=False))
    viewport_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    snapshot_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    schema_version: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1))
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1, index=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SluvoCanvasNode(SQLModel, table=True):
    __tablename__ = "sluvo_canvas_node"

    id: Optional[int] = Field(default=None, primary_key=True)
    canvas_id: int = Field(foreign_key="sluvo_canvas.id", index=True)
    parent_node_id: Optional[int] = Field(default=None, foreign_key="sluvo_canvas_node.id", index=True)
    node_type: str = Field(default="text", sa_column=Column(String(64), nullable=False, index=True))
    title: str = Field(default="", sa_column=Column(String(255), nullable=False))
    position_x: float = Field(default=0.0)
    position_y: float = Field(default=0.0)
    width: Optional[float] = Field(default=None)
    height: Optional[float] = Field(default=None)
    z_index: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0, index=True))
    rotation: float = Field(default=0.0)
    status: str = Field(default="idle", sa_column=Column(String(32), nullable=False, index=True))
    hidden: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False, index=True))
    locked: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    collapsed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    data_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    ports_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    ai_config_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    style_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1, index=True))
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    updated_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    deleted_at: Optional[datetime] = Field(default=None, index=True)


class SluvoCanvasEdge(SQLModel, table=True):
    __tablename__ = "sluvo_canvas_edge"

    id: Optional[int] = Field(default=None, primary_key=True)
    canvas_id: int = Field(foreign_key="sluvo_canvas.id", index=True)
    source_node_id: int = Field(foreign_key="sluvo_canvas_node.id", index=True)
    target_node_id: int = Field(foreign_key="sluvo_canvas_node.id", index=True)
    source_port_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True, index=True))
    target_port_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True, index=True))
    edge_type: str = Field(default="custom", sa_column=Column(String(64), nullable=False, index=True))
    label: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    data_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    style_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    hidden: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False, index=True))
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1, index=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    deleted_at: Optional[datetime] = Field(default=None, index=True)


class SluvoCanvasAsset(SQLModel, table=True):
    __tablename__ = "sluvo_canvas_asset"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="sluvo_project.id", index=True)
    canvas_id: Optional[int] = Field(default=None, foreign_key="sluvo_canvas.id", index=True)
    node_id: Optional[int] = Field(default=None, foreign_key="sluvo_canvas_node.id", index=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)
    media_type: str = Field(default="image", sa_column=Column(String(32), nullable=False, index=True))
    source_type: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
    url: str = Field(sa_column=Column(LONGTEXT, nullable=False))
    thumbnail_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    storage_object_id: Optional[int] = Field(default=None, foreign_key="storage_object.id", index=True)
    mime_type: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    file_size: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    width: Optional[int] = Field(default=None)
    height: Optional[int] = Field(default=None)
    duration_seconds: Optional[float] = Field(default=None)
    metadata_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    deleted_at: Optional[datetime] = Field(default=None, index=True)


class SluvoCommunityCanvas(SQLModel, table=True):
    __tablename__ = "sluvo_community_canvas"
    __table_args__ = (UniqueConstraint("source_project_id", name="uq_sluvo_community_canvas_source_project"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    source_project_id: int = Field(foreign_key="sluvo_project.id", index=True)
    source_canvas_id: int = Field(foreign_key="sluvo_canvas.id", index=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    title: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    description: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    cover_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    tags_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    status: str = Field(default="published", sa_column=Column(String(32), nullable=False, index=True))
    snapshot_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    nodes_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    edges_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    viewport_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    schema_version: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1))
    view_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    fork_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    published_at: Optional[datetime] = Field(default=None, index=True)
    unpublished_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SluvoAgentTemplate(SQLModel, table=True):
    __tablename__ = "sluvo_agent_template"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    name: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    description: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    avatar_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    cover_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    profile_key: str = Field(default="custom_agent", sa_column=Column(String(64), nullable=False, index=True))
    model_code: str = Field(default="deepseek-v4-flash", sa_column=Column(String(64), nullable=False, index=True))
    role_prompt: str = Field(default="", sa_column=Column(LONGTEXT))
    use_cases_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    input_types_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    output_types_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    tools_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    approval_policy_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    examples_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    memory_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    status: str = Field(default="active", sa_column=Column(String(32), nullable=False, index=True))
    forked_from_publication_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    deleted_at: Optional[datetime] = Field(default=None, index=True)


class SluvoCommunityAgent(SQLModel, table=True):
    __tablename__ = "sluvo_community_agent"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_agent_id: int = Field(foreign_key="sluvo_agent_template.id", index=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    title: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    description: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    cover_url: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    tags_json: str = Field(default="[]", sa_column=Column(LONGTEXT))
    template_snapshot_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    status: str = Field(default="published", sa_column=Column(String(32), nullable=False, index=True))
    view_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    fork_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    published_at: Optional[datetime] = Field(default=None, index=True)
    unpublished_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SluvoAgentSession(SQLModel, table=True):
    __tablename__ = "sluvo_agent_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="sluvo_project.id", index=True)
    canvas_id: int = Field(foreign_key="sluvo_canvas.id", index=True)
    target_node_id: Optional[int] = Field(default=None, foreign_key="sluvo_canvas_node.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    title: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    agent_profile: str = Field(default="canvas_agent", sa_column=Column(String(64), nullable=False, index=True))
    mode: str = Field(default="semi_auto", sa_column=Column(String(32), nullable=False, index=True))
    status: str = Field(default="active", sa_column=Column(String(32), nullable=False, index=True))
    context_snapshot_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    last_event_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SluvoAgentEvent(SQLModel, table=True):
    __tablename__ = "sluvo_agent_event"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="sluvo_agent_session.id", index=True)
    turn_id: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
    role: str = Field(default="user", sa_column=Column(String(32), nullable=False, index=True))
    event_type: str = Field(default="message", sa_column=Column(String(32), nullable=False, index=True))
    sequence_no: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0, index=True))
    payload_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SluvoAgentAction(SQLModel, table=True):
    __tablename__ = "sluvo_agent_action"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="sluvo_agent_session.id", index=True)
    project_id: int = Field(foreign_key="sluvo_project.id", index=True)
    canvas_id: int = Field(foreign_key="sluvo_canvas.id", index=True)
    target_node_id: Optional[int] = Field(default=None, foreign_key="sluvo_canvas_node.id", index=True)
    action_type: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    status: str = Field(default="proposed", sa_column=Column(String(32), nullable=False, index=True))
    input_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    patch_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    result_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    error_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    approved_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    executed_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SluvoCanvasMutation(SQLModel, table=True):
    __tablename__ = "sluvo_canvas_mutation"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="sluvo_project.id", index=True)
    canvas_id: int = Field(foreign_key="sluvo_canvas.id", index=True)
    actor_type: str = Field(default="user", sa_column=Column(String(32), nullable=False, index=True))
    actor_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    agent_session_id: Optional[int] = Field(default=None, foreign_key="sluvo_agent_session.id", index=True)
    agent_action_id: Optional[int] = Field(default=None, foreign_key="sluvo_agent_action.id", index=True)
    mutation_type: str = Field(default="canvas.update", sa_column=Column(String(64), nullable=False, index=True))
    revision_from: Optional[int] = Field(default=None)
    revision_to: Optional[int] = Field(default=None)
    patch_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# ==========================================
# 8. 统一 Assistant Runtime 会话与事件
# ==========================================

class AssistantSession(SQLModel, table=True):
    __tablename__ = "assistant_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    episode_id: Optional[int] = Field(default=None, foreign_key="episode.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    channel: str = Field(default="internal", sa_column=Column(String(32), nullable=False, index=True))
    profile: str = Field(default="director", sa_column=Column(String(64), nullable=False, index=True))
    status: str = Field(default="idle", sa_column=Column(String(32), nullable=False, index=True))
    title: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    linked_external_session_id: Optional[int] = Field(default=None, foreign_key="externalagentsession.id", index=True)
    metadata_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class AssistantTranscriptEvent(SQLModel, table=True):
    __tablename__ = "assistant_transcript_event"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="assistant_session.id", index=True)
    turn_id: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    role: Optional[str] = Field(default=None, sa_column=Column(String(32), index=True))
    event_type: str = Field(default="turn", sa_column=Column(String(32), nullable=False, index=True))
    block_type: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    sequence_no: int = Field(default=0, index=True)
    payload_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class AssistantPendingQuestion(SQLModel, table=True):
    __tablename__ = "assistant_pending_question"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="assistant_session.id", index=True)
    question_key: str = Field(default_factory=lambda: uuid.uuid4().hex, sa_column=Column(String(64), nullable=False, unique=True, index=True))
    question_type: str = Field(default="question", sa_column=Column(String(32), nullable=False, index=True))
    status: str = Field(default="pending", sa_column=Column(String(32), nullable=False, index=True))
    title: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    prompt_text: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))
    payload_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    answer_json: str = Field(default="{}", sa_column=Column(LONGTEXT))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    answered_at: Optional[datetime] = Field(default=None, index=True)


# ==========================================
# 9. 神鹿AI导演 Agent 会话与消息
# ==========================================

class DirectorAgentSession(SQLModel, table=True):
    """神鹿AI导演会话表"""
    __tablename__ = "director_agent_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id", index=True)
    episode_id: Optional[int] = Field(default=None, foreign_key="episode.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)

    # Agent标识（多Agent预留）
    agent_name: str = Field(default="shenlu_director", sa_column=Column(String(64)))

    # 会话状态
    status: str = Field(default="active", sa_column=Column(String(32), index=True))  # active/archived
    title: Optional[str] = Field(default=None, sa_column=Column(String(255)))

    # 上下文快照
    context_snapshot_json: str = Field(default="{}", sa_column=Column(LONGTEXT))

    # 会话配置（automation_mode 等）
    session_config_json: Optional[str] = Field(default=None, sa_column=Column(Text))

    # 最后交互
    last_message_at: Optional[datetime] = Field(default=None, index=True)
    last_action_type: Optional[str] = Field(default=None, sa_column=Column(String(64)))

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # 关联关系
    messages: List["DirectorAgentMessage"] = Relationship(back_populates="session", cascade_delete=True)


class DirectorAgentMessage(SQLModel, table=True):
    """神鹿AI导演消息表"""
    __tablename__ = "director_agent_message"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="director_agent_session.id", index=True)

    # 消息基础
    role: str = Field(sa_column=Column(String(32), nullable=False, index=True))  # user/agent
    content: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT))

    # 消息类型
    message_type: str = Field(default="text", sa_column=Column(String(32), index=True))  # text/plan/result/confirm

    # 结构化数据
    payload_json: str = Field(default="{}", sa_column=Column(LONGTEXT))

    # 任务关联
    task_type: Optional[str] = Field(default=None, sa_column=Column(String(64), index=True))
    task_status: Optional[str] = Field(default=None, sa_column=Column(String(32), index=True))  # pending/confirmed/executing/completed/rejected

    # 确认状态
    requires_confirmation: bool = Field(default=False, index=True)
    confirmation_status: Optional[str] = Field(default=None, sa_column=Column(String(32), index=True))  # pending/confirmed/rejected
    confirmed_at: Optional[datetime] = Field(default=None)
    confirmed_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    # 执行结果
    execution_result_json: str = Field(default="{}", sa_column=Column(LONGTEXT))

    # Agent元数据（多Agent预留）
    agent_name: Optional[str] = Field(default=None, sa_column=Column(String(64)))

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    # 关联关系
    session: DirectorAgentSession = Relationship(back_populates="messages")




