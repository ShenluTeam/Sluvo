import pytest
from fastapi import HTTPException
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.security import encode_id
from models import (
    RoleEnum,
    SluvoCanvasAsset,
    SluvoCanvasMutation,
    SluvoProject,
    SluvoProjectMember,
    Team,
    TeamMemberLink,
    User,
)
from schemas import (
    SluvoAgentSessionCreateRequest,
    SluvoCanvasBatchRequest,
    SluvoCanvasEdgeCreateRequest,
    SluvoCanvasNodeCreateRequest,
    SluvoCanvasNodeUpdateRequest,
    SluvoProjectCreateRequest,
    SluvoProjectMemberCreateRequest,
)
from services.sluvo_service import (
    SLUVO_PERMISSION_AGENT,
    SLUVO_PERMISSION_MANAGE,
    SLUVO_PERMISSION_READ,
    SLUVO_PERMISSION_WRITE,
    add_sluvo_project_member,
    append_sluvo_agent_event,
    apply_sluvo_canvas_batch,
    approve_sluvo_agent_action,
    create_sluvo_agent_action,
    create_sluvo_agent_session,
    create_sluvo_canvas_asset_upload,
    create_sluvo_edge,
    create_sluvo_node,
    create_sluvo_project,
    get_or_create_main_canvas,
    require_sluvo_project_access,
    update_sluvo_node,
)


@compiles(LONGTEXT, "sqlite")
def _compile_longtext_sqlite(_type, _compiler, **_kwargs):
    return "TEXT"


def _make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _user(email: str, nickname: str) -> User:
    return User(email=email, hashed_password="x", nickname=nickname, session_token=f"token-{email}")


def _seed_team(session: Session):
    team = Team(name="Sluvo Team")
    owner = _user("owner@example.com", "Owner")
    editor = _user("editor@example.com", "Editor")
    viewer = _user("viewer@example.com", "Viewer")
    admin = _user("admin@example.com", "Admin")
    session.add(team)
    session.add(owner)
    session.add(editor)
    session.add(viewer)
    session.add(admin)
    session.commit()
    for item in [team, owner, editor, viewer, admin]:
        session.refresh(item)
    links = {
        "owner": TeamMemberLink(team_id=team.id, user_id=owner.id, role=RoleEnum.EDITOR),
        "editor": TeamMemberLink(team_id=team.id, user_id=editor.id, role=RoleEnum.EDITOR),
        "viewer": TeamMemberLink(team_id=team.id, user_id=viewer.id, role=RoleEnum.VIEWER),
        "admin": TeamMemberLink(team_id=team.id, user_id=admin.id, role=RoleEnum.ADMIN),
    }
    session.add_all(links.values())
    session.commit()
    return team, owner, editor, viewer, admin, links


def test_sluvo_project_canvas_node_edge_asset_and_unique_member_index():
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        created = create_sluvo_project(
            session,
            user=owner,
            team=team,
            payload=SluvoProjectCreateRequest(title="独立画布", visibility="project_members"),
        )
        project_id = created["project"]["id"]
        assert created["project"]["title"] == "独立画布"
        assert created["canvas"]["canvasKey"] == "main"

        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)
        node = create_sluvo_node(
            session,
            canvas,
            SluvoCanvasNodeCreateRequest(nodeType="image", title="图片节点", position={"x": 10, "y": 20}),
            user=owner,
        )
        second = create_sluvo_node(
            session,
            canvas,
            SluvoCanvasNodeCreateRequest(nodeType="text", title="提示词", position={"x": 120, "y": 20}),
            user=owner,
        )
        edge = create_sluvo_edge(
            session,
            canvas,
            SluvoCanvasEdgeCreateRequest(
                sourceNodeId=encode_id(second.id),
                targetNodeId=encode_id(node.id),
                edgeType="reference",
            ),
        )
        asset = SluvoCanvasAsset(
            project_id=project.id,
            canvas_id=canvas.id,
            node_id=node.id,
            owner_user_id=owner.id,
            media_type="image",
            source_type="upload",
            url="https://example.com/a.png",
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)

        assert node.node_type == "image"
        assert edge.edge_type == "reference"
        assert asset.project_id == project.id

        duplicate = SluvoProjectMember(project_id=project.id, user_id=owner.id, role="viewer")
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()


def test_sluvo_project_member_permissions_and_team_admin_fallback():
    with _make_session() as session:
        team, owner, editor, viewer, admin, links = _seed_team(session)
        bundle = create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="权限项目"))
        project_id = bundle["project"]["id"]
        project = session.exec(select(SluvoProject)).first()

        add_sluvo_project_member(
            session,
            project=project,
            inviter=owner,
            payload=SluvoProjectMemberCreateRequest(userId=encode_id(editor.id), role="editor"),
        )
        add_sluvo_project_member(
            session,
            project=project,
            inviter=owner,
            payload=SluvoProjectMemberCreateRequest(userId=encode_id(viewer.id), role="viewer"),
        )

        require_sluvo_project_access(
            session,
            user=editor,
            team=team,
            team_member=links["editor"],
            project_id=project.id,
            permission=SLUVO_PERMISSION_WRITE,
        )
        require_sluvo_project_access(
            session,
            user=editor,
            team=team,
            team_member=links["editor"],
            project_id=project.id,
            permission=SLUVO_PERMISSION_AGENT,
        )
        require_sluvo_project_access(
            session,
            user=admin,
            team=team,
            team_member=links["admin"],
            project_id=project.id,
            permission=SLUVO_PERMISSION_MANAGE,
        )
        require_sluvo_project_access(
            session,
            user=viewer,
            team=team,
            team_member=links["viewer"],
            project_id=project.id,
            permission=SLUVO_PERMISSION_READ,
        )
        with pytest.raises(HTTPException) as exc:
            require_sluvo_project_access(
                session,
                user=viewer,
                team=team,
                team_member=links["viewer"],
                project_id=project.id,
                permission=SLUVO_PERMISSION_WRITE,
            )
        assert exc.value.status_code == 403


def test_sluvo_canvas_revision_conflict_and_batch_snapshot_mutation():
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="Revision"))
        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)
        node = create_sluvo_node(session, canvas, SluvoCanvasNodeCreateRequest(title="Node"), user=owner)

        with pytest.raises(HTTPException) as exc:
            update_sluvo_node(
                session,
                canvas,
                node,
                SluvoCanvasNodeUpdateRequest(expectedRevision=999, title="Stale"),
                user=owner,
            )
        assert exc.value.status_code == 409

        before_revision = canvas.revision
        result = apply_sluvo_canvas_batch(
            session,
            canvas,
            SluvoCanvasBatchRequest(
                expectedRevision=before_revision,
                snapshot={"nodes": [{"id": encode_id(node.id)}], "edges": []},
                nodes=[{"id": encode_id(node.id), "expectedRevision": node.revision, "title": "Updated"}],
            ),
            user=owner,
        )
        assert result["canvas"]["revision"] == before_revision + 1
        assert result["canvas"]["snapshot"]["nodes"][0]["id"] == encode_id(node.id)
        assert session.exec(select(SluvoCanvasMutation)).first().mutation_type in {"node.create", "canvas.batch"}


def test_sluvo_canvas_asset_upload_persists_asset(monkeypatch):
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="Upload"))
        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)
        node = create_sluvo_node(session, canvas, SluvoCanvasNodeCreateRequest(nodeType="upload", title="上传"), user=owner)

        def fake_upload(*_args, **_kwargs):
            return {
                "file_url": "https://oss.example.com/sluvo/a.png",
                "thumbnail_url": "https://oss.example.com/sluvo/a-thumb.png",
                "storage_object_key": "users/1/sluvo/a.png",
                "original_filename": "a.png",
                "mime_type": "image/png",
                "file_size": 7,
            }

        monkeypatch.setattr("services.sluvo_service._upload_bytes_to_oss_with_meta", fake_upload)
        result = create_sluvo_canvas_asset_upload(
            session,
            canvas=canvas,
            user=owner,
            content=b"pngdata",
            filename="a.png",
            content_type="image/png",
            media_type="image",
            node_id=encode_id(node.id),
            width=100,
            height=80,
        )

        asset = session.exec(select(SluvoCanvasAsset)).first()
        assert result["asset"]["url"] == "https://oss.example.com/sluvo/a.png"
        assert asset.project_id == project.id
        assert asset.canvas_id == canvas.id
        assert asset.node_id == node.id
        assert asset.width == 100
        assert asset.height == 80


def test_sluvo_agent_session_event_action_approval_writes_mutation():
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="Agent"))
        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)

        agent_session = create_sluvo_agent_session(
            session,
            project=project,
            user=owner,
            team=team,
            canvas_id=canvas.id,
            target_node_id=None,
            title="Agent",
            agent_profile="canvas_agent",
            mode="semi_auto",
            context_snapshot={"goal": "test"},
        )
        event = append_sluvo_agent_event(
            session,
            agent_session=agent_session,
            role="user",
            event_type="message",
            payload={"content": "add note"},
        )
        action = create_sluvo_agent_action(
            session,
            agent_session=agent_session,
            action_payload={
                "actionType": "canvas.patch",
                "patch": {
                    "expectedRevision": canvas.revision,
                    "nodes": [{"nodeType": "note", "title": "Agent Note", "position": {"x": 1, "y": 2}}],
                },
            },
        )
        approved = approve_sluvo_agent_action(session, action, user=owner)

        assert event.sequence_no == 1
        assert approved.status == "succeeded"
        assert session.exec(select(SluvoCanvasMutation).where(SluvoCanvasMutation.actor_type == "agent")).first()
