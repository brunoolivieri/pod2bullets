"""Feed parser for RSS/Atom podcast feeds (metadata only)."""

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
                "published_at": entry.get("published"),
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
