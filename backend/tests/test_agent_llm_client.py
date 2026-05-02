import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agents.base_agent import BaseAgent
from services.agents.llm_client import chat_json
from services.deepseek_hybrid_router import resolve_deepseek_agent_route
from services.deepseek_model_policy import normalize_deepseek_model


class _FakeAgent(BaseAgent):
    agent_name = "storyboard_agent"
    agent_label = "分镜导演"

    def run(self, context):
        raise NotImplementedError

    def execute_action(self, context, action, payload=None):
        raise NotImplementedError


def test_hybrid_router_defaults_to_flash_for_simple_tasks():
    route = resolve_deepseek_agent_route(
        {
            "task_kind": "simple_chat",
            "estimated_text_tokens": 200,
            "segment_count": 2,
            "character_count": 2,
            "expected_tool_calls": 0,
            "user_intent_flags": [],
            "previous_failures": 0,
        }
    )
    assert route["model"] == "deepseek-v4-flash"
    assert route["thinking_enabled"] is False
    assert route["route_tag"] == "flash_default"


def test_prompt_bundle_contains_system_and_user_messages():
    agent = _FakeAgent(session=None)
    bundle = agent.build_prompt_bundle(
        context={
            "creative_stage": "storyboard_pending",
            "creative_stage_label": "分镜拆解",
            "agent_context_preview": {"script_summary": "摘要"},
            "workspace_facts_preview": {"panel_count": 8, "resource_counts": {"characters": 3}},
            "current_script": "A" * 1200,
        },
        task_goal="生成分镜摘要",
        latest_instruction="把这一段拆成分镜，并给我一个下一步建议",
        action_space=[{"type": "save_storyboard", "label": "写入分镜"}],
    )
    assert bundle["llm_model_used"] == "deepseek-v4-flash"
    assert bundle["llm_route"]["thinking_enabled"] is True
    assert bundle["messages_preview"][0]["role"] == "system"
    assert bundle["messages_preview"][1]["role"] == "user"


def test_hybrid_router_uses_flash_thinking_for_hard_case():
    route = resolve_deepseek_agent_route(
        {
            "task_kind": "storyboard_planning",
            "estimated_text_tokens": 12000,
            "segment_count": 24,
            "character_count": 8,
            "expected_tool_calls": 3,
            "user_intent_flags": ["deep_reasoning", "storyboard"],
            "previous_failures": 0,
        }
    )
    assert route["model"] == "deepseek-v4-flash"
    assert route["thinking_enabled"] is True
    assert route["route_tag"] == "flash_thinking_hard_case"


def test_legacy_model_names_normalize_to_v4_flash():
    assert normalize_deepseek_model("deepseek-chat", thinking_enabled=False) == ("deepseek-v4-flash", False)
    assert normalize_deepseek_model("deepseek-chat", thinking_enabled=True) == ("deepseek-v4-flash", False)
    assert normalize_deepseek_model("deepseek-reasoner", thinking_enabled=False) == ("deepseek-v4-flash", True)


def test_chat_json_can_stream_reasoning_and_content():
    reasoning_updates = []

    class _Delta:
        def __init__(self, *, reasoning_content=None, content=None):
            self.reasoning_content = reasoning_content
            self.content = content

    class _Choice:
        def __init__(self, delta):
            self.delta = delta

    class _Chunk:
        def __init__(self, delta):
            self.choices = [_Choice(delta)]

    fake_stream = [
        _Chunk(_Delta(reasoning_content="第一步分析。")),
        _Chunk(_Delta(reasoning_content="第二步分析。")),
        _Chunk(_Delta(content='{"message":"ok"')),
        _Chunk(_Delta(content=',"artifacts":{}}')),
    ]

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_stream

    with patch("services.agents.llm_client.build_client", return_value=fake_client):
        payload = chat_json(
            model="deepseek-reasoner",
            messages=[{"role": "user", "content": "hello"}],
            on_reasoning=reasoning_updates.append,
            thinking_enabled=False,
            max_tokens=1000,
            route_tag="test",
        )

    assert payload["message"] == "ok"
    called_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert called_kwargs["model"] == "deepseek-v4-flash"
    assert called_kwargs["extra_body"]["thinking"]["type"] == "enabled"
    assert reasoning_updates[-1] == "第一步分析。第二步分析。"
