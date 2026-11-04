"""Feed parser for RSS/Atom podcast feeds (metadata only)."""

from email.utils import parsedate_to_datetime
from typing import Any

import feedparser


def parse_podcast_feed(xml_content: str) -> dict[str, Any]:
    """Parse RSS/Atom content and extract podcast metadata and episodes."""
    parsed = feedparser.parse(xml_content)
    feed_data = parsed.feed

    title = feed_data.get("title", "Sem Título").strip()
    description = feed_data.get("description", "").strip()
    site_url = feed_data.get("link", "")
    image_url = ""
    if "image" in feed_data and "href" in feed_data.image:
        image_url = feed_data.image.href
    elif "itunes_image" in feed_data and isinstance(feed_data.itunes_image, dict):
        image_url = feed_data.itunes_image.get("href", "")

    episodes = []
    for entry in parsed.entries:
        # Enclosures with audio type
        audio_url = None
        audio_ext = "mp3"
        for enc in entry.get("enclosures", []):
            enc_type = enc.get("type", "")
            if "audio" in enc_type or enc.get("href", "").endswith(
                (".mp3", ".m4a", ".ogg", ".opus", ".wav")
            ):
                audio_url = enc.get("href")
                if audio_url:
                    parts = audio_url.split("?")[0].split(".")
                    if len(parts) > 1 and len(parts[-1]) <= 4:
                        audio_ext = parts[-1].lower()
                break

        if not audio_url:
            continue

        guid = entry.get("id") or entry.get("guid") or audio_url
        ep_title = entry.get("title", "Episódio sem título").strip()
        summary = entry.get("summary") or entry.get("description") or ""

        # Extract episode image or fallback to feed image
        ep_image = image_url
        if "image" in entry and isinstance(entry.image, dict) and "href" in entry.image:
            ep_image = entry.image["href"]
        elif (
            "itunes_image" in entry
            and isinstance(entry.itunes_image, dict)
            and "href" in entry.itunes_image
        ):
            ep_image = entry.itunes_image["href"]

        # Normalize published_at to ISO-8601 so SQLite ORDER BY published_at DESC sorts newest first
        raw_pub = entry.get("published") or entry.get("updated")
        iso_pub = raw_pub
        if raw_pub:
            try:
                dt = parsedate_to_datetime(raw_pub)
                iso_pub = dt.isoformat()
            except Exception:
                if "published_parsed" in entry and entry.published_parsed:
                    t = entry.published_parsed
                    iso_pub = (
                        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"
                        f"T{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}+00:00"
                    )

        duration_sec = None
        if "itunes_duration" in entry:
            dur_str = str(entry.itunes_duration)
            try:
                parts = [int(p) for p in dur_str.split(":")]
                if len(parts) == 3:
                    duration_sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
                elif len(parts) == 2:
                    duration_sec = parts[0] * 60 + parts[1]
                elif len(parts) == 1:
                    duration_sec = parts[0]
            except Exception:
                duration_sec = None

        episodes.append(
            {
                "guid": str(guid),
                "title": ep_title,
                "audio_url": audio_url,
                "audio_ext": audio_ext,
                "image_url": ep_image,
                "published_at": iso_pub,
                "duration_seconds": duration_sec,
                "summary": summary,
            }
        )

    return {
        "title": title,
        "description": description,
        "site_url": site_url,
        "image_url": image_url,
        "episodes": episodes,
    }
