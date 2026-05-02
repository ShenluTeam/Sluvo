import re
from typing import Any, Dict, List, Tuple

from sqlmodel import Session, select

from models import Episode, Script
from services.delete_cleanup_service import cleanup_episode_dependencies

RAW_CHINESE_NUMERALS = "零〇一二三四五六七八九十百千万两"
HEADER_REGEX = re.compile(
    rf"""
    (?m)^\s*
    (?:\#{{1,6}}\s*)?
    (?P<title>
      (?:\[\s*|【\s*)?
      (?:
        第\s*(?:\d+|[{RAW_CHINESE_NUMERALS}]+)\s*(?:集|章)
        |
        \d+\.
      )
      (?:\s*[\]】])?
      (?:\s+[^\n\r]+)?
    )
    \s*$
    """,
    re.VERBOSE,
)


def _normalize_text(source_text: str) -> str:
    return (source_text or "").replace("\r\n", "\n").replace("\r", "\n")


def _build_episode_title(raw_title: str, fallback_index: int) -> str:
    title = (raw_title or "").strip()
    return title or f"Episode {fallback_index}"


def split_source_text(source_text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    text = _normalize_text(source_text)
    warnings: List[str] = []

    if not text.strip():
        return [], ["Source text is empty."]

    matches = list(HEADER_REGEX.finditer(text))
    if not matches:
        return [], ["No valid episode header was detected."]

    episodes: List[Dict[str, Any]] = []
    intro_text = text[:matches[0].start()].strip()

    for index, match in enumerate(matches, start=1):
        content_start = match.end()
        content_end = matches[index].start() if index < len(matches) else len(text)
        content = text[content_start:content_end].strip()

        if index == 1 and intro_text:
            content = f"{intro_text}\n\n{content}".strip()
            warnings.append("Leading text before the first header was merged into episode 1.")

        if not content:
            warnings.append(f"{_build_episode_title(match.group('title'), index)} has no body content.")

        episodes.append(
            {
                "sequence_num": index,
                "title": _build_episode_title(match.group("title"), index),
                "source_text": content,
            }
        )

    return episodes, warnings


def build_split_preview(source_text: str) -> Dict[str, Any]:
    episodes, warnings = split_source_text(source_text)
    return {
        "episodes": [
            {
                **item,
                "char_count": len((item.get("source_text") or "").strip()),
            }
            for item in episodes
        ],
        "warnings": warnings,
    }


def commit_episode_splits(
    session: Session,
    script: Script,
    episodes: List[Dict[str, Any]],
    replace_existing: bool,
) -> Dict[str, Any]:
    if not episodes:
        raise ValueError("No preview episodes are available to commit.")

    existing_episodes = session.exec(
        select(Episode)
        .where(Episode.script_id == script.id)
        .order_by(Episode.sequence_num.asc())
    ).all()

    deleted_count = 0
    base_sequence = 0

    if replace_existing:
        deleted_count = len(existing_episodes)
        for episode in existing_episodes:
            cleanup_episode_dependencies(session, episode.id)
            session.delete(episode)
        session.flush()
    else:
        base_sequence = max((episode.sequence_num for episode in existing_episodes), default=0)

    created_episodes: List[Episode] = []
    for index, item in enumerate(episodes, start=1):
        title = (item.get("title") or "").strip() or f"Episode {index}"
        episode_source_text = (item.get("source_text") or "").strip()

        new_episode = Episode(
            script_id=script.id,
            sequence_num=base_sequence + index,
            title=title,
            source_text=episode_source_text or None,
        )
        session.add(new_episode)
        created_episodes.append(new_episode)

    session.flush()

    return {
        "created_episodes": created_episodes,
        "deleted_count": deleted_count,
    }
