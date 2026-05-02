import json
import sys
from pathlib import Path

from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import Episode, Panel, Script, SharedResource, Team
from schemas import STORYBOARD_MODE_COMIC
from services.storyboard_mode_service import get_panel_reference_images


@compiles(LONGTEXT, "sqlite")
def _compile_longtext_sqlite(_type, _compiler, **_kwargs):
    return "TEXT"


def _make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_panel_reference_images_include_bound_asset_images_after_assets_are_generated():
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
            name="阿福",
            file_url="https://example.com/afu.png",
            description="小狗阿福",
        )
        session.add(resource)
        session.commit()
        session.refresh(resource)

        panel = Panel(
            episode_id=episode.id,
            sequence_num=1,
            title="阿福追车",
            storyboard_mode=STORYBOARD_MODE_COMIC,
            entity_bindings_json=json.dumps(
                {
                    "characters": [{"name": "阿福", "asset_id": resource.id, "match_type": "identity"}],
                    "scenes": [],
                    "props": [],
                },
                ensure_ascii=False,
            ),
            auto_asset_reference_enabled=True,
        )
        session.add(panel)
        session.commit()
        session.refresh(panel)

        assert get_panel_reference_images(session, panel) == ["https://example.com/afu.png"]

