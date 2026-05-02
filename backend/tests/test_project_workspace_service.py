import json
import sys
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.mysql import LONGTEXT

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import Episode, Panel, Script, SharedResource, SharedResourceVersion, Team
from services.project_workspace_service import build_project_workspace


@compiles(LONGTEXT, "sqlite")
def _compile_longtext_sqlite(_type, _compiler, **_kwargs):
    return "TEXT"


def _make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_build_project_workspace_creates_projection_nodes_and_links():
    with _make_session() as session:
        team = Team(name="Team A")
        session.add(team)
        session.commit()
        session.refresh(team)

        script = Script(team_id=team.id, name="测试项目", source_text="项目原文")
        session.add(script)
        session.commit()
        session.refresh(script)

        episode = Episode(script_id=script.id, sequence_num=1, title="第一集", source_text="第一集原文")
        session.add(episode)
        session.commit()
        session.refresh(episode)

        resource = SharedResource(
            script_id=script.id,
            resource_type="character",
            name="林川",
            file_url="https://example.com/resource.png",
            description="主角",
        )
        session.add(resource)
        session.commit()
        session.refresh(resource)

        version = SharedResourceVersion(
            resource_id=resource.id,
            version_tag="v1",
            appearance_prompt="30岁男性，黑色风衣",
            file_url="https://example.com/resource.png",
            is_default=True,
        )
        session.add(version)
        session.commit()

        panel = Panel(
            episode_id=episode.id,
            sequence_num=1,
            title="镜头 001",
            prompt="分镜图片提示词",
            video_prompt="分镜视频提示词",
            entity_bindings_json=json.dumps(
                {
                    "characters": [
                        {
                            "name": "林川",
                            "asset_id": resource.id,
                            "match_type": "identity",
                        }
                    ],
                    "scenes": [],
                    "props": [],
                },
                ensure_ascii=False,
            ),
        )
        session.add(panel)
        session.commit()
        session.refresh(panel)

        workspace = build_project_workspace(session, script)

        node_types = {item["nodeType"] for item in workspace["canvasNodes"]}
        assert "project_root" in node_types
        assert "script_episode" in node_types
        assert "asset_table" in node_types
        assert "storyboard_table" in node_types

        assert len(workspace["episodeAssetLinks"]) == 1
        assert len(workspace["storyboardShotAssetLinks"]) == 1
        assert workspace["storyboardShotAssetLinks"][0]["assetId"] == workspace["assets"][0]["id"]


def test_build_project_workspace_exposes_asset_prompt_from_default_version():
    with _make_session() as session:
        team = Team(name="Team B")
        session.add(team)
        session.commit()
        session.refresh(team)

        script = Script(team_id=team.id, name="测试资产项目")
        session.add(script)
        session.commit()
        session.refresh(script)

        episode = Episode(script_id=script.id, sequence_num=1, title="第一集")
        session.add(episode)
        session.commit()

        resource = SharedResource(
            script_id=script.id,
            resource_type="scene",
            name="地下车库",
            file_url="https://example.com/scene.png",
            description="场景说明",
        )
        session.add(resource)
        session.commit()
        session.refresh(resource)

        session.add(
            SharedResourceVersion(
                resource_id=resource.id,
                version_tag="v1",
                appearance_prompt="阴冷地下车库，混凝土立柱，蓝灰色光线",
                file_url="https://example.com/scene.png",
                is_default=True,
            )
        )
        session.commit()

        workspace = build_project_workspace(session, script)
        asset = workspace["assets"][0]
        assert asset["prompt"] == "阴冷地下车库，混凝土立柱，蓝灰色光线"
