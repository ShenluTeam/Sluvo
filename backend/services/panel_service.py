from __future__ import annotations

import base64
from datetime import datetime

from fastapi import HTTPException
from sqlmodel import Session, select

from models import Episode, ExtraImage, Panel, Team
from schemas import normalize_panel_type
from services.access_service import require_episode_team_access, require_panel_team_access
from services.oss_service import upload_bytes_to_oss_with_meta
from services.storyboard_mode_service import recompute_episode_dependencies


def create_panel(
    session: Session,
    team: Team,
    episode_id: int,
    insert_at: int | None = None,
    panel_type: str | None = None,
) -> Panel:
    now = datetime.utcnow()
    episode = require_episode_team_access(session, team, episode_id)
    normalized_panel_type = normalize_panel_type(panel_type)
    if insert_at is not None:
        existing = session.exec(
            select(Panel).where(Panel.episode_id == episode_id, Panel.sequence_num >= insert_at).order_by(Panel.sequence_num.desc())
        ).all()
        for panel in existing:
            panel.sequence_num += 1
            panel.updated_at = now
            session.add(panel)
        new_panel = Panel(
            episode_id=episode_id,
            sequence_num=insert_at,
            panel_type=normalized_panel_type,
            storyboard_mode=getattr(episode, "storyboard_mode", "commentary") or "commentary",
            updated_at=now,
        )
    else:
        last_panel = session.exec(
            select(Panel).where(Panel.episode_id == episode_id).order_by(Panel.sequence_num.desc())
        ).first()
        next_seq = (last_panel.sequence_num + 1) if last_panel else 1
        new_panel = Panel(
            episode_id=episode_id,
            sequence_num=next_seq,
            panel_type=normalized_panel_type,
            storyboard_mode=getattr(episode, "storyboard_mode", "commentary") or "commentary",
            updated_at=now,
        )
    episode.updated_at = now
    session.add(episode)
    session.add(new_panel)
    session.commit()
    recompute_episode_dependencies(session, episode_id)
    session.commit()
    session.refresh(new_panel)
    return new_panel


def delete_panel(session: Session, team: Team, panel_id: int) -> None:
    now = datetime.utcnow()
    panel = require_panel_team_access(session, team, panel_id)
    episode_id = panel.episode_id
    episode = session.get(Episode, episode_id)
    session.delete(panel)
    session.commit()
    remaining = session.exec(select(Panel).where(Panel.episode_id == episode_id).order_by(Panel.sequence_num)).all()
    for idx, item in enumerate(remaining):
        item.sequence_num = idx + 1
        item.updated_at = now
        session.add(item)
    if episode:
        episode.updated_at = now
        session.add(episode)
    session.commit()
    recompute_episode_dependencies(session, episode_id)
    session.commit()


def reorder_panels(session: Session, team: Team, episode_id: int, panel_id: int, new_index: int) -> None:
    now = datetime.utcnow()
    episode = require_episode_team_access(session, team, episode_id)
    panels = session.exec(select(Panel).where(Panel.episode_id == episode_id).order_by(Panel.sequence_num.asc())).all()
    target_panel = next((panel for panel in panels if panel.id == panel_id), None)
    if not target_panel:
        raise HTTPException(status_code=404, detail="Panel not found")
    panels.remove(target_panel)
    panels.insert(new_index, target_panel)
    for idx, panel in enumerate(panels):
        panel.sequence_num = idx + 1
        panel.updated_at = now
        session.add(panel)
    episode.updated_at = now
    session.add(episode)
    session.commit()
    recompute_episode_dependencies(session, episode_id)
    session.commit()


def list_panels(session: Session, team: Team, episode_id: int):
    require_episode_team_access(session, team, episode_id)
    return session.exec(select(Panel).where(Panel.episode_id == episode_id).order_by(Panel.sequence_num.asc())).all()


def upload_extra_image(session: Session, team: Team, episode_id: int, image_base64: str, *, owner_user_id: int | None = None) -> str:
    require_episode_team_access(session, team, episode_id)
    if not image_base64.startswith("data:image"):
        raise HTTPException(status_code=400, detail="Invalid image format, expected base64 data URI.")

    header, encoded = image_base64.split(",", 1)
    image_data = base64.b64decode(encoded)
    mime_type = header.split(":")[1].split(";")[0]
    ext = "png"
    if "jpeg" in mime_type or "jpg" in mime_type:
        ext = "jpg"
    elif "webp" in mime_type:
        ext = "webp"

    upload_meta = upload_bytes_to_oss_with_meta(
        image_data,
        filename=f"extra.{ext}",
        content_type=mime_type,
        owner_user_id=owner_user_id,
        media_type="image",
        source_type="extra_image",
        source_id=episode_id,
    )
    final_url = upload_meta["file_url"]
    episode = session.get(Episode, episode_id)
    if episode:
        episode.updated_at = datetime.utcnow()
        session.add(episode)
    session.add(ExtraImage(episode_id=episode_id, image_base64=final_url))
    session.commit()
    return final_url


def list_extra_images(session: Session, team: Team, episode_id: int):
    require_episode_team_access(session, team, episode_id)
    return session.exec(select(ExtraImage).where(ExtraImage.episode_id == episode_id)).all()


def delete_extra_image(session: Session, team: Team, episode_id: int, image_id: int) -> None:
    require_episode_team_access(session, team, episode_id)
    image = session.exec(
        select(ExtraImage).where(ExtraImage.id == image_id, ExtraImage.episode_id == episode_id)
    ).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        if bucket and image.image_base64.startswith(settings.OSS_DOMAIN):
            object_name = image.image_base64.replace(f"{settings.OSS_DOMAIN}/", "")
            bucket.delete_object(object_name)
    except Exception:
        pass
    episode = session.get(Episode, episode_id)
    if episode:
        episode.updated_at = datetime.utcnow()
        session.add(episode)
    session.delete(image)
    session.commit()
