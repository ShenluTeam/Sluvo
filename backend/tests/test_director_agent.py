import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agents.director_agent import DirectorAgent


def test_save_script_candidate_uses_latest_script_artifact_when_payload_empty():
    agent = DirectorAgent(session=None)

    draft = agent._candidate_script_draft(
        {
            "latest_artifacts": {
                "script_draft": {
                    "artifact_type": "script_draft",
                    "content": "场景一：路边·黄昏\n阿福追着离开的面包车。",
                }
            },
            "current_script": "",
            "latest_user_message": "",
        },
        payload={},
    )

    assert draft == "场景一：路边·黄昏\n阿福追着离开的面包车。"


def test_save_script_candidate_falls_back_to_latest_user_message():
    agent = DirectorAgent(session=None)

    draft = agent._candidate_script_draft(
        {
            "latest_artifacts": {},
            "current_script": "",
            "latest_user_message": "【剧本正文】\n场景一：废弃厂房·黎明\n阿福挡在油桶前。",
        },
        payload={},
    )

    assert "阿福挡在油桶前" in draft
