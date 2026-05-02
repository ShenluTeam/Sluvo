from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent
BACKEND_ENV_FILE = BACKEND_DIR / ".env"

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///shenlu_saas.db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 10
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True
    DB_POOL_LOG_STATUS: bool = False
    
    # Hashids
    HASH_SALT: str = "shenlu_ai_secret_salt_2026_xYz"
    
    # WeChat
    WECHAT_APPID: str = ""
    WECHAT_SECRET: str = ""
    WECHAT_TOKEN: str = "shenlu2026"
    
    # RunningHub
    RUNNINGHUB_API_KEY: str = ""  
    WORKFLOW_ID: str = "1991550248581603329" 
    
    # Aliyun OSS
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_BUCKET_NAME: str = ""
    OSS_ENDPOINT: str = "oss-cn-beijing.aliyuncs.com"
    STORAGE_QUOTA_ENFORCE: bool = False
    STORAGE_FREE_QUOTA_GB: int = 5
    STORAGE_MEMBER_QUOTA_GB: int = 10
    
    # NanoBanana (Grsai)
    NANO_API_KEY: str = ""
    NANO_API_URL: str = "https://grsai.dakka.com.cn/v1/draw/nano-banana"
    NANO_RESULT_URL: str = "https://grsai.dakka.com.cn/v1/draw/result"

    # SuChuang
    SUCHUANG_KEY: str = ""
    
    # Email SMTP
    SMTP_HOST: str = "smtp.feishu.cn"
    SMTP_PORT: int = 465
    SMTP_SENDER_EMAIL: str = ""
    SMTP_SENDER_PASSWORD: str = ""
    
    # DeepSeek AI Director
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_STORY_SEGMENT_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_STORY_SEGMENT_PLANNER_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_STORY_GRID_EXPANDER_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_JSON_FIX_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_STORY_SEGMENT_CRITIC_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_STORY_SEGMENT_USE_STRICT_SCHEMA: bool = True
    DEEPSEEK_STORY_SEGMENT_PLANNER_ENABLE_THINKING: bool = False
    DEEPSEEK_STORY_SEGMENT_PLANNER_HARD_CASE_ENABLED: bool = True
    DEEPSEEK_STORY_SEGMENT_PLANNER_HARD_CASE_ROUTE: str = "thinking"
    DEEPSEEK_STORY_SEGMENT_PLANNER_HARD_CASE_TEXT_TOKENS: int = 6000
    DEEPSEEK_STORY_SEGMENT_PLANNER_HARD_CASE_ASSET_COUNT: int = 18
    DEEPSEEK_MAX_CONTEXT_TOKENS: int = 1000000
    DEEPSEEK_PLANNER_MAX_TOKENS: int = 4096
    DEEPSEEK_GRID_EXPANDER_MAX_TOKENS: int = 3072
    DEEPSEEK_BATCH_GRID_EXPANDER_MAX_TOKENS: int = 16000
    DEEPSEEK_JSON_FIX_MAX_TOKENS: int = 2048
    DEEPSEEK_ASSET_EXTRACTOR_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_ASSET_CHARACTER_ENRICH_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_ASSET_SCENE_ENRICH_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_ASSET_PROP_ENRICH_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_ASSET_CRITIC_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_ASSET_USE_STRICT_SCHEMA: bool = True
    DEEPSEEK_ASSET_CHARACTER_REASONER_FALLBACK: bool = True
    DEEPSEEK_ASSET_SCENE_PROP_REASONER_FALLBACK: bool = True
    DEEPSEEK_ASSET_EXTRACT_MAX_TOKENS: int = 4096
    DEEPSEEK_ASSET_ENRICH_MAX_TOKENS: int = 3072
    DEEPSEEK_ASSET_REPAIR_MAX_TOKENS: int = 2048
    DEEPSEEK_AGENT_DEFAULT_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_AGENT_THINKING_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_AGENT_REASONER_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_AGENT_DEFAULT_THINKING_ENABLED: bool = False
    DEEPSEEK_AGENT_PLANNING_THINKING_ENABLED: bool = True
    DEEPSEEK_AGENT_SIMPLE_MAX_TOKENS: int = 1000
    DEEPSEEK_AGENT_PLANNING_MAX_TOKENS: int = 4000
    DEEPSEEK_AGENT_REASONER_MAX_TOKENS: int = 4000
    DEEPSEEK_AGENT_REASONER_TEXT_TOKENS: int = 8000
    DEEPSEEK_AGENT_REASONER_SEGMENT_COUNT: int = 20
    DEEPSEEK_AGENT_REASONER_CHARACTER_COUNT: int = 6
    DEEPSEEK_AGENT_REASONER_TOOL_CALL_COUNT: int = 2
    DEEPSEEK_AGENT_REASONER_JSON_RETRY_COUNT: int = 2
    DEEPSEEK_AGENT_JSON_RETRY_TEMPERATURE: float = 0.1
    DEEPSEEK_AGENT_STREAM_TIMEOUT_SECONDS: int = 120

    # Audio / Dubbing
    MINIMAX_API_KEY: str = ""

    # Editing / CapCut
    FFMPEG_BINARY: str = "ffmpeg"
    FFPROBE_BINARY: str = "ffprobe"
    JIANYING_DRAFT_PATH_PLACEHOLDER: str = "C:/Users/YourName/Documents/JianyingPro/Drafts"

    # External AI Director Assistant
    EXTERNAL_PROVIDER_CREDENTIAL_SECRET: str = ""
    SHENLU_AGENT_API_BASE_URL: str = "https://ai.shenlu.top"
    OPENCLAW_PUBLIC_BASE_URL: str = "https://ai.shenlu.top"
    OPENCLAW_API_BASE_URL: str = "https://api.shenlu.top"
    SHENLU_AGENT_LOCAL_STUB_MODE: bool = False
    OPENCLAW_PUBLIC_PROVIDER_V2_ENABLED: bool = True
    TAVILY_API_KEY: str = ""
    TAVILY_MAX_RESULTS: int = 5
    TAVILY_TIMEOUT_SECONDS: int = 20
    
    # Task queue / worker
    REDIS_URL: str = "redis://localhost:6379/0"
    TASK_QUEUE_NAMESPACE: str = "aidrama"
    TASK_QUEUE_LEASE_SECONDS: int = 900
    TASK_QUEUE_HEARTBEAT_SECONDS: int = 30
    TASK_QUEUE_REDIS_BLOCK_SECONDS: int = 5
    TASK_QUEUE_RETRY_DELAY_SECONDS: int = 30
    TASK_QUEUE_SCAN_LIMIT: int = 100
    TASK_QUEUE_SUBMIT_MAX_CONCURRENCY: int = 16
    TASK_CALLBACK_BASE_URL: str = ""
    TASK_CALLBACK_SECRET: str = "aidrama-callback-secret"
    POLLER_TICK_SECONDS: int = 2
    POLLER_BATCH_LIMIT: int = 100
    RUNNINGHUB_IMAGE_QUERY_CONCURRENCY: int = 20
    RUNNINGHUB_VIDEO_QUERY_CONCURRENCY: int = 10
    SUCHUANG_QUERY_CONCURRENCY: int = 10
    MINIMAX_QUERY_CONCURRENCY: int = 10
    
    @property
    def RUNNINGHUB_URL(self) -> str:
        return f"https://www.runninghub.cn/openapi/v2/run/ai-app/{self.WORKFLOW_ID}"
        
    @property
    def QUERY_URL(self) -> str:
        return "https://www.runninghub.cn/openapi/v2/query"
        
    @property
    def UPLOAD_URL(self) -> str:
        return "https://www.runninghub.cn/openapi/v2/media/upload/binary"

    @property
    def OSS_DOMAIN(self) -> str:
        return f"https://{self.OSS_BUCKET_NAME}.{self.OSS_ENDPOINT}"
    
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
