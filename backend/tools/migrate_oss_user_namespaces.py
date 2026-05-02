from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlmodel import Session, select

from core.config import settings
from database import engine
from models import Episode, GenerationRecord, Panel, Script, SharedResource, SharedResourceVersion, StorageObject, TeamMemberLink, TemporaryUploadAsset, User, VoiceAsset
from services.oss_service import bucket, build_user_object_key, object_key_from_url, url_from_object_key
from services.storage_service import commit_storage_object, ensure_user_storage_namespace, mark_old_object_deleted, mark_pending_old_delete


@dataclass
class MigrationItem:
    source_type: str
    source_id: int
    field_name: str
    owner_user_id: Optional[int]
    old_url: str
    old_key: str
    media_type: str
    status: str = "pending"
    new_key: str = ""
    new_url: str = ""
    reason: str = ""
    old_deleted: bool = False


SCAN_TEXT_COLUMNS = [
    ("generationrecord", "preview_url"),
    ("generationrecord", "thumbnail_url"),
    ("panel", "image_url"),
    ("panel", "video_url"),
    ("panel", "file_url"),
    ("panel", "thumbnail_url"),
    ("panel", "video_thumbnail_url"),
    ("panel", "history_urls_json"),
    ("panel", "video_history_json"),
    ("sharedresource", "file_url"),
    ("sharedresource", "thumbnail_url"),
    ("sharedresourceversion", "file_url"),
    ("temporaryuploadasset", "file_url"),
    ("temporaryuploadasset", "thumbnail_url"),
    ("voiceasset", "preview_audio_url"),
    ("episode", "composed_video_url"),
    ("episode", "composed_video_thumbnail_url"),
]


def _now_tag() -> str:
    return datetime.utcnow().strftime("%Y%m%d%H%M%S")


def _first_team_user_id(session: Session, team_id: Optional[int]) -> Optional[int]:
    if not team_id:
        return None
    link = session.exec(
        select(TeamMemberLink)
        .where(TeamMemberLink.team_id == team_id)
        .order_by(TeamMemberLink.joined_at.asc())
    ).first()
    return int(link.user_id) if link and link.user_id else None


def _script_owner_user_id(session: Session, script_id: Optional[int]) -> Optional[int]:
    script = session.get(Script, script_id) if script_id else None
    return _first_team_user_id(session, script.team_id) if script else None


def _episode_owner_user_id(session: Session, episode_id: Optional[int]) -> Optional[int]:
    episode = session.get(Episode, episode_id) if episode_id else None
    return _script_owner_user_id(session, episode.script_id) if episode else None


def _media_type_from_url(url: str, field_name: str) -> str:
    lowered = f"{field_name} {url}".lower()
    if any(token in lowered for token in [".mp4", ".webm", ".mov", "video"]):
        return "video"
    if any(token in lowered for token in [".mp3", ".wav", ".m4a", "audio"]):
        return "audio"
    if any(token in lowered for token in [".txt", ".srt", ".md", "text"]):
        return "text"
    if any(token in lowered for token in [".jpg", ".jpeg", ".png", ".webp", ".gif", "image", "thumbnail"]):
        return "image"
    return "other"


def _iter_urls_from_value(value: Any) -> Iterable[str]:
    if not value:
        return []
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            urls = []
            for item in parsed:
                if isinstance(item, str):
                    urls.append(item)
                elif isinstance(item, dict):
                    urls.extend(str(item.get(key) or "") for key in ["url", "file_url", "preview_url", "thumbnail_url"])
            return [url for url in urls if url]
    if isinstance(value, str):
        return [value]
    return []


def _is_migratable_oss_url(url: str) -> tuple[bool, str]:
    key = object_key_from_url(url)
    if not key:
        return False, ""
    if key.startswith("users/"):
        return False, key
    return True, key


def _owner_for_record(session: Session, source_type: str, record: Any) -> Optional[int]:
    if source_type == "generationrecord":
        return int(record.user_id) if record.user_id else None
    if source_type == "panel":
        return _episode_owner_user_id(session, record.episode_id)
    if source_type == "sharedresource":
        return _script_owner_user_id(session, record.script_id)
    if source_type == "sharedresourceversion":
        resource = session.get(SharedResource, record.resource_id)
        return _script_owner_user_id(session, resource.script_id) if resource else None
    if source_type == "temporaryuploadasset":
        return None
    if source_type == "voiceasset":
        return int(record.user_id) if record.user_id else None
    if source_type == "episode":
        return _script_owner_user_id(session, record.script_id)
    return None


def collect_items(session: Session, *, user_id: Optional[int], limit: int) -> list[MigrationItem]:
    model_specs = [
        ("generationrecord", GenerationRecord, ["preview_url", "thumbnail_url"]),
        ("panel", Panel, ["image_url", "video_url", "file_url", "thumbnail_url", "video_thumbnail_url", "history_urls_json", "video_history_json"]),
        ("sharedresource", SharedResource, ["file_url", "thumbnail_url"]),
        ("sharedresourceversion", SharedResourceVersion, ["file_url"]),
        ("temporaryuploadasset", TemporaryUploadAsset, ["file_url", "thumbnail_url"]),
        ("voiceasset", VoiceAsset, ["preview_audio_url"]),
        ("episode", Episode, ["composed_video_url", "composed_video_thumbnail_url"]),
    ]
    items: list[MigrationItem] = []
    seen: set[tuple[str, int, str, str]] = set()
    for source_type, model, fields in model_specs:
        records = session.exec(select(model).order_by(model.id.asc())).all()
        for record in records:
            owner_user_id = _owner_for_record(session, source_type, record)
            if user_id and owner_user_id != user_id:
                continue
            for field_name in fields:
                for url in _iter_urls_from_value(getattr(record, field_name, None)):
                    ok, key = _is_migratable_oss_url(url)
                    if not ok:
                        continue
                    identity = (source_type, int(record.id), field_name, key)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    items.append(
                        MigrationItem(
                            source_type=source_type,
                            source_id=int(record.id),
                            field_name=field_name,
                            owner_user_id=owner_user_id,
                            old_url=url,
                            old_key=key,
                            media_type=_media_type_from_url(url, field_name),
                        )
                    )
                    if limit and len(items) >= limit:
                        return items
    return items


def _replace_in_value(value: Any, old_url: str, new_url: str) -> Any:
    if not isinstance(value, str):
        return value
    return value.replace(old_url, new_url)


def update_database_reference(session: Session, item: MigrationItem) -> None:
    model_map = {
        "generationrecord": GenerationRecord,
        "panel": Panel,
        "sharedresource": SharedResource,
        "sharedresourceversion": SharedResourceVersion,
        "temporaryuploadasset": TemporaryUploadAsset,
        "voiceasset": VoiceAsset,
        "episode": Episode,
    }
    model = model_map[item.source_type]
    record = session.get(model, item.source_id)
    if not record:
        raise RuntimeError("record no longer exists")
    current = getattr(record, item.field_name)
    setattr(record, item.field_name, _replace_in_value(current, item.old_url, item.new_url))
    if hasattr(record, "storage_object_key") and item.source_type in {"sharedresource", "temporaryuploadasset"}:
        record.storage_object_key = item.new_key
    if hasattr(record, "updated_at"):
        record.updated_at = datetime.utcnow()
    session.add(record)
    session.commit()


def old_key_reference_count(session: Session, old_key: str) -> int:
    total = 0
    for table, column in SCAN_TEXT_COLUMNS:
        try:
            total += int(session.exec(text(f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE :needle").bindparams(needle=f"%{old_key}%")).one())
        except Exception:
            continue
    return total


def copy_and_verify(old_key: str, new_key: str) -> int:
    if not bucket:
        raise RuntimeError("OSS bucket is not configured")
    old_meta = bucket.head_object(old_key)
    old_size = int(getattr(old_meta, "content_length", 0) or 0)
    try:
        new_meta = bucket.head_object(new_key)
    except Exception:
        bucket.copy_object(settings.OSS_BUCKET_NAME, old_key, new_key)
        new_meta = bucket.head_object(new_key)
    new_size = int(getattr(new_meta, "content_length", 0) or 0)
    if old_size != new_size:
        raise RuntimeError(f"copy size mismatch old={old_size} new={new_size}")
    return new_size


def _existing_migration(session: Session, old_key: str, owner_user_id: int) -> Optional[StorageObject]:
    return session.exec(
        select(StorageObject)
        .where(StorageObject.old_object_key == old_key)
        .where(StorageObject.owner_user_id == owner_user_id)
        .order_by(StorageObject.id.asc())
    ).first()


def delete_old_if_unreferenced(session: Session, item: MigrationItem) -> bool:
    if old_key_reference_count(session, item.old_key) > 0:
        item.status = "pending_old_delete"
        item.reason = "old key still referenced"
        mark_pending_old_delete(session, item.old_key)
        return False
    try:
        bucket.delete_object(item.old_key)
        item.old_deleted = True
        mark_old_object_deleted(session, item.old_key)
        return True
    except Exception as exc:
        item.status = "pending_old_delete"
        item.reason = f"delete failed: {exc}"
        mark_pending_old_delete(session, item.old_key)
        return False


def migrate_item(session: Session, item: MigrationItem, *, dry_run: bool, delete_old: bool, delete_old_after_commit: bool) -> MigrationItem:
    if not item.owner_user_id:
        item.status = "unresolved"
        item.reason = "owner user could not be resolved"
        return item
    if item.old_key.startswith("users/"):
        item.status = "skipped"
        item.reason = "already migrated"
        return item
    ensure_user_storage_namespace(session, item.owner_user_id)
    existing = _existing_migration(session, item.old_key, item.owner_user_id)
    item.new_key = existing.object_key if existing else build_user_object_key(
        owner_user_id=item.owner_user_id,
        filename=item.old_key.rsplit("/", 1)[-1],
        media_type=item.media_type,
    )
    item.new_url = url_from_object_key(item.new_key)
    if item.new_key == item.old_key:
        item.status = "skipped"
        item.reason = "new key equals old key"
        return item
    if dry_run:
        item.status = "dry_run"
        return item

    try:
        file_size = copy_and_verify(item.old_key, item.new_key)
        update_database_reference(session, item)
        if not existing:
            commit_storage_object(
                session,
                owner_user_id=item.owner_user_id,
                object_key=item.new_key,
                old_object_key=item.old_key,
                media_type=item.media_type,
                file_size=file_size,
                source_type=item.source_type,
                source_id=item.source_id,
                status="migrated",
                release_reserved=False,
            )
        item.status = "db_updated"
        if delete_old and delete_old_after_commit:
            if delete_old_if_unreferenced(session, item):
                item.status = "old_deleted"
    except Exception as exc:
        item.status = "failed"
        item.reason = str(exc)
    return item


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate OSS objects into per-user namespaces.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--delete-old", action="store_true")
    parser.add_argument("--delete-old-after-commit", action="store_true")
    parser.add_argument("--report", default=f"storage_migration_report_{_now_tag()}.jsonl")
    parser.add_argument("--csv-report")
    args = parser.parse_args()

    report_path = Path(args.report)
    csv_report_path = Path(args.csv_report) if args.csv_report else report_path.with_suffix(".csv")
    summary: dict[str, int] = {}
    with Session(engine) as session:
        items = collect_items(session, user_id=args.user_id, limit=args.batch_size)
        csv_exists = csv_report_path.exists()
        with report_path.open("a", encoding="utf-8") as handle, csv_report_path.open("a", newline="", encoding="utf-8") as csv_handle:
            csv_writer = csv.DictWriter(csv_handle, fieldnames=list(MigrationItem.__dataclass_fields__.keys()))
            if not csv_exists:
                csv_writer.writeheader()
            for item in items:
                result = migrate_item(
                    session,
                    item,
                    dry_run=args.dry_run,
                    delete_old=args.delete_old,
                    delete_old_after_commit=args.delete_old_after_commit,
                )
                summary[result.status] = summary.get(result.status, 0) + 1
                row = asdict(result)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                csv_writer.writerow(row)
    print(json.dumps({"summary": summary, "report": str(report_path), "csv_report": str(csv_report_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
