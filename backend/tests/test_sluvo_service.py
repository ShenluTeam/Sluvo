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
    GenerationRecord,
    RoleEnum,
    SluvoAgentArtifact,
    SluvoAgentRun,
    SluvoAgentStep,
    SluvoCanvasAsset,
    SluvoCanvasEdge,
    SluvoCanvasMutation,
    SluvoCanvasNode,
    SluvoProject,
    SluvoProjectMember,
    Team,
    TeamMemberLink,
    User,
)
from schemas import (
    SluvoAgentSessionCreateRequest,
    SluvoAgentTemplateCreateRequest,
    SluvoCanvasBatchRequest,
    SluvoCanvasEdgeCreateRequest,
    SluvoCanvasNodeCreateRequest,
    SluvoCanvasNodeUpdateRequest,
    SluvoProjectCreateRequest,
    SluvoProjectMemberCreateRequest,
    SluvoTextNodeAnalyzeRequest,
)
from services.sluvo_service import (
    SLUVO_PERMISSION_AGENT,
    SLUVO_PERMISSION_MANAGE,
    SLUVO_PERMISSION_READ,
    SLUVO_PERMISSION_WRITE,
    add_sluvo_project_member,
    analyze_sluvo_text_node,
    append_sluvo_agent_event,
    apply_sluvo_canvas_batch,
    approve_sluvo_agent_action,
    build_sluvo_agent_action_payload,
    create_sluvo_agent_action,
    create_sluvo_agent_run,
    create_sluvo_agent_session,
    create_sluvo_agent_template,
    create_sluvo_canvas_asset_upload,
    create_sluvo_edge,
    create_sluvo_node,
    create_sluvo_project,
    get_or_create_main_canvas,
    confirm_sluvo_agent_run_cost,
    list_sluvo_project_agent_sessions,
    list_sluvo_project_agent_runs,
    require_sluvo_project_access,
    resolve_sluvo_agent_route,
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


def test_sluvo_canvas_batch_creates_client_id_edges_atomically():
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="Atomic"))
        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)

        result = apply_sluvo_canvas_batch(
            session,
            canvas,
            SluvoCanvasBatchRequest(
                expectedRevision=canvas.revision,
                nodes=[
                    {
                        "nodeType": "note",
                        "title": "A",
                        "position": {"x": 0, "y": 0},
                        "data": {"clientId": "client-a"},
                    },
                    {
                        "nodeType": "note",
                        "title": "B",
                        "position": {"x": 300, "y": 0},
                        "data": {"clientId": "client-b"},
                    },
                ],
                edges=[
                    {
                        "sourceNodeId": "",
                        "targetNodeId": "",
                        "sourcePortId": "right",
                        "targetPortId": "left",
                        "edgeType": "reference",
                        "data": {
                            "clientId": "edge-ab",
                            "sourceClientId": "client-a",
                            "targetClientId": "client-b",
                        },
                    }
                ],
            ),
            user=owner,
        )

        nodes_by_client_id = {node["data"]["clientId"]: node for node in result["nodes"]}
        assert set(nodes_by_client_id) == {"client-a", "client-b"}
        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        assert edge["sourceNodeId"] == nodes_by_client_id["client-a"]["id"]
        assert edge["targetNodeId"] == nodes_by_client_id["client-b"]["id"]
        assert edge["data"]["clientId"] == "edge-ab"


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
            model_code="deepseek-v4-flash",
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


def test_sluvo_agent_auto_route_selects_specialist_profiles():
    with _make_session() as session:
        prompt_route = resolve_sluvo_agent_route(
            session,
            requested_profile="auto",
            prompt="请优化这个 prompt，让它适合视频生成",
            context={},
            selected_nodes=[],
        )
        storyboard_route = resolve_sluvo_agent_route(
            session,
            requested_profile="auto",
            prompt="把这段剧情拆分成分镜和首帧视频链路",
            context={},
            selected_nodes=[],
        )
        explicit_route = resolve_sluvo_agent_route(
            session,
            requested_profile="consistency_checker",
            prompt="请看一下",
            context={},
            selected_nodes=[],
        )
        story_route = resolve_sluvo_agent_route(
            session,
            requested_profile="auto",
            prompt="我有一个动画短片灵感，请提取角色、场景、道具并拆分镜",
            context={},
            selected_nodes=[],
        )

        assert prompt_route["profile"] == "prompt_polisher"
        assert prompt_route["actionType"] == "prompt.rewrite"
        assert storyboard_route["profile"] == "storyboard_director"
        assert storyboard_route["actionType"] == "workflow.plan"
        assert explicit_route["profile"] == "consistency_checker"
        assert explicit_route["actionType"] == "agent.report"
        assert story_route["profile"] == "story_director"
        assert story_route["actionType"] == "workflow.plan"


def test_sluvo_agent_run_creates_timeline_canvas_writes_and_cost_records():
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="Agent Run Project"))
        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)
        context_node = create_sluvo_node(
            session,
            canvas,
            SluvoCanvasNodeCreateRequest(
                nodeType="text",
                title="雨夜信号",
                position={"x": 10, "y": 20},
                data={"clientId": "ctx-1", "directType": "prompt_note", "prompt": "雨夜少年追逐神秘信号"},
            ),
            user=owner,
        )

        timeline = create_sluvo_agent_run(
            session,
            project=project,
            user=owner,
            team=team,
            canvas_id=canvas.id,
            target_node_id=None,
            goal="拆成角色、场景、分镜和生成占位",
            source_surface="panel",
            agent_profile="auto",
            agent_template_id=None,
            model_code="deepseek-v4-flash",
            mode="semi_auto",
            context_snapshot={
                "selectedNodes": [
                    {
                        "id": encode_id(context_node.id),
                        "clientId": "ctx-1",
                        "title": "雨夜信号",
                        "position": {"x": 10, "y": 20},
                        "prompt": "雨夜少年追逐神秘信号",
                    }
                ]
            },
        )

        assert timeline["run"]["status"] == "waiting_cost_confirmation"
        assert len(timeline["steps"]) >= 4
        assert session.exec(select(SluvoAgentRun)).first()
        assert session.exec(select(SluvoAgentStep)).first()
        assert session.exec(select(SluvoAgentArtifact)).first()
        assert session.exec(select(SluvoCanvasMutation).where(SluvoCanvasMutation.actor_type == "agent")).first()

        runs = list_sluvo_project_agent_runs(session, project=project, limit=12)
        assert runs[0]["run"]["id"] == timeline["run"]["id"]

        run = session.exec(select(SluvoAgentRun)).first()
        media_artifacts = session.exec(
            select(SluvoAgentArtifact).where(
                SluvoAgentArtifact.run_id == run.id,
                SluvoAgentArtifact.write_policy == "requires_cost_confirmation",
            )
        ).all()
        assert media_artifacts
        confirmed = confirm_sluvo_agent_run_cost(
            session,
            run=run,
            user=owner,
            team=team,
            artifact_ids=[item.id for item in media_artifacts],
            confirmed=True,
        )
        assert confirmed["run"]["status"] == "running"
        assert session.exec(select(GenerationRecord)).first()


def test_sluvo_agent_panel_patch_writes_products_not_agent_nodes():
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="Agent Products"))
        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)
        source_node = create_sluvo_node(
            session,
            canvas,
            SluvoCanvasNodeCreateRequest(
                nodeType="note",
                title="原始提示词",
                position={"x": 10, "y": 20},
                data={
                    "clientId": "source-prompt",
                    "directType": "prompt_note",
                    "prompt": "古风少女站在雨夜长街，电影感，浅景深",
                },
            ),
            user=owner,
        )
        agent_session = create_sluvo_agent_session(
            session,
            project=project,
            user=owner,
            team=team,
            canvas_id=canvas.id,
            target_node_id=None,
            title="创作总监",
            agent_profile="auto",
            model_code="deepseek-v4-flash",
            mode="semi_auto",
            context_snapshot={},
        )

        action_payload, reply = build_sluvo_agent_action_payload(
            session,
            agent_session=agent_session,
            content="请优化提示词",
            payload={
                "agentProfile": "auto",
                "modelCode": "deepseek-v4-flash",
                "contextSnapshot": {
                    "selectedNodes": [
                        {
                            "id": encode_id(source_node.id),
                            "title": "原始提示词",
                            "directType": "prompt_note",
                            "prompt": "古风少女站在雨夜长街，电影感，浅景深",
                            "position": {"x": 10, "y": 20},
                        }
                    ]
                },
            },
        )

        assert action_payload["actionType"] == "prompt.rewrite"
        assert reply["resolvedProfile"] == "prompt_polisher"
        assert len(action_payload["patch"]["nodes"]) == 1
        assert action_payload["patch"]["nodes"][0]["nodeType"] == "note"
        assert action_payload["patch"]["nodes"][0]["data"]["source"] == "canvas_agent_panel"
        assert "古风少女" in action_payload["patch"]["nodes"][0]["data"]["prompt"]
        assert len(action_payload["patch"]["edges"]) == 1
        assert action_payload["patch"]["edges"][0]["sourceNodeId"] == encode_id(source_node.id)


def test_sluvo_agent_new_story_prompt_builds_production_pipeline():
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="Story Pipeline"))
        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)
        agent_session = create_sluvo_agent_session(
            session,
            project=project,
            user=owner,
            team=team,
            canvas_id=canvas.id,
            target_node_id=None,
            title="创作总监",
            agent_profile="auto",
            model_code="deepseek-v4-flash",
            mode="semi_auto",
            context_snapshot={},
        )

        action_payload, reply = build_sluvo_agent_action_payload(
            session,
            agent_session=agent_session,
            content="一个关于雨夜少年追逐神秘信号的动画短片灵感，请提取角色、场景、道具，然后拆分镜。",
            payload={
                "agentProfile": "auto",
                "modelCode": "deepseek-v4-flash",
                "contextSnapshot": {"selectedNodes": []},
            },
        )

        nodes = action_payload["patch"]["nodes"]
        titles = {node["title"] for node in nodes}
        node_types = {node["nodeType"] for node in nodes}
        assert action_payload["actionType"] == "workflow.plan"
        assert reply["resolvedProfile"] == "story_director"
        assert len(nodes) == 6
        assert "故事总览" in titles
        assert "角色 / 道具提取" in titles
        assert "场景设定" in titles
        assert "分镜计划" in titles
        assert "首帧图片生成" in titles
        assert "镜头视频生成" in titles
        assert "agent" not in node_types
        assert len(action_payload["patch"]["edges"]) >= 6


def test_sluvo_text_node_analysis_returns_node_local_markdown():
    result = analyze_sluvo_text_node(
        SluvoTextNodeAnalyzeRequest(
            nodeTitle="宣传片灵感",
            content="做一个北京的宣传片",
            instruction="提取角色、场景、道具，并继续拆分镜。",
            modelCode="deepseek-v4-flash",
        )
    )

    assert result["modelCode"] == "deepseek-v4-flash"
    assert "content" in result
    assert "### 场景" in result["content"] or "分镜" in result["content"]
    assert "action" not in result


def test_sluvo_custom_agent_template_shapes_context_and_history():
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="Custom Agent"))
        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)
        template = create_sluvo_agent_template(
            session,
            user=owner,
            team=team,
            payload=SluvoAgentTemplateCreateRequest(
                name="角色设定师",
                description="专门整理角色设定",
                modelCode="deepseek-v4-pro",
                rolePrompt="只输出角色设定，不处理视频执行。",
                useCases=["角色关系", "角色外观"],
                inputTypes=["text"],
                outputTypes=["note"],
                tools=["read_canvas", "propose_canvas_patch"],
                approvalPolicy={"mode": "always_review"},
            ),
        )
        agent_session = create_sluvo_agent_session(
            session,
            project=project,
            user=owner,
            team=team,
            canvas_id=canvas.id,
            target_node_id=None,
            title="角色设定师",
            agent_profile=encode_id(template.id),
            model_code="",
            mode="semi_auto",
            context_snapshot={"agentTemplateId": encode_id(template.id), "sourceSurface": "panel"},
        )

        action_payload, reply = build_sluvo_agent_action_payload(
            session,
            agent_session=agent_session,
            content="请整理主角设定",
            payload={
                "agentProfile": encode_id(template.id),
                "contextSnapshot": {
                    "agentTemplateId": encode_id(template.id),
                    "sourceSurface": "panel",
                    "selectedNodes": [],
                },
            },
        )
        action = create_sluvo_agent_action(session, agent_session=agent_session, action_payload=action_payload)

        assert reply["agentName"] == "角色设定师"
        assert reply["modelCode"] == "deepseek-v4-pro"
        assert action_payload["input"]["contextSummary"]["agentTemplateId"] == encode_id(template.id)
        assert action_payload["input"]["contextSummary"]["sourceSurface"] == "panel"

        history = list_sluvo_project_agent_sessions(session, project=project)
        assert len(history) == 1
        assert history[0]["session"]["id"] == encode_id(agent_session.id)
        assert history[0]["latestAction"]["id"] == encode_id(action.id)


def test_sluvo_agent_node_target_context_and_approval_updates_node_state():
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="Agent Node"))
        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)
        agent_node = create_sluvo_node(
            session,
            canvas,
            SluvoCanvasNodeCreateRequest(
                nodeType="agent",
                title="节点 Agent",
                position={"x": 20, "y": 30},
                data={"directType": "agent_node", "agentName": "节点 Agent"},
            ),
            user=owner,
        )
        agent_session = create_sluvo_agent_session(
            session,
            project=project,
            user=owner,
            team=team,
            canvas_id=canvas.id,
            target_node_id=agent_node.id,
            title="节点 Agent",
            agent_profile="auto",
            model_code="deepseek-v4-flash",
            mode="semi_auto",
            context_snapshot={"sourceSurface": "node", "targetNodeId": encode_id(agent_node.id)},
        )
        action_payload, _reply = build_sluvo_agent_action_payload(
            session,
            agent_session=agent_session,
            content="请分析上游并生成建议",
            payload={
                "agentProfile": "auto",
                "modelCode": "deepseek-v4-flash",
                "contextSnapshot": {
                    "sourceSurface": "node",
                    "targetNodeId": encode_id(agent_node.id),
                    "selectedNodes": [],
                },
            },
        )
        action = create_sluvo_agent_action(session, agent_session=agent_session, action_payload=action_payload)
        approved = approve_sluvo_agent_action(session, action, user=owner)
        refreshed_node = session.get(SluvoCanvasNode, agent_node.id)

        assert approved.status == "succeeded"
        assert action_payload["targetNodeId"] == encode_id(agent_node.id)
        assert action_payload["input"]["contextSummary"]["sourceSurface"] == "node"
        assert "agentLastActionStatus" in refreshed_node.data_json
        assert "succeeded" in refreshed_node.data_json


def test_sluvo_agent_patch_accepts_client_source_node_id():
    with _make_session() as session:
        team, owner, _editor, _viewer, _admin, _links = _seed_team(session)
        create_sluvo_project(session, user=owner, team=team, payload=SluvoProjectCreateRequest(title="Agent Client IDs"))
        project = session.exec(select(SluvoProject)).first()
        canvas = get_or_create_main_canvas(session, project)
        source_node = create_sluvo_node(
            session,
            canvas,
            SluvoCanvasNodeCreateRequest(
                nodeType="note",
                title="灵感节点",
                position={"x": 0, "y": 0},
                data={"clientId": "direct-client-source", "directType": "prompt_note", "prompt": "雨夜少年追逐神秘信号"},
            ),
            user=owner,
        )
        agent_session = create_sluvo_agent_session(
            session,
            project=project,
            user=owner,
            team=team,
            canvas_id=canvas.id,
            target_node_id=None,
            title="创作总监",
            agent_profile="auto",
            model_code="deepseek-v4-flash",
            mode="semi_auto",
            context_snapshot={},
        )
        action_payload, _reply = build_sluvo_agent_action_payload(
            session,
            agent_session=agent_session,
            content="请根据选区生成创作建议",
            payload={
                "agentProfile": "auto",
                "modelCode": "deepseek-v4-flash",
                "contextSnapshot": {
                    "selectedNodes": [
                        {
                            "id": "direct-prompt_note-local",
                            "clientId": "direct-client-source",
                            "title": "灵感节点",
                            "prompt": "雨夜少年追逐神秘信号",
                            "position": {"x": 0, "y": 0},
                        }
                    ]
                },
            },
        )
        action = create_sluvo_agent_action(session, agent_session=agent_session, action_payload=action_payload)
        approved = approve_sluvo_agent_action(session, action, user=owner)
        edges = session.exec(select(SluvoCanvasEdge).where(SluvoCanvasEdge.source_node_id == source_node.id)).all()

        assert approved.status == "succeeded"
        assert edges
