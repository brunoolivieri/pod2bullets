"""Naming and slugification helpers."""

import re
import unicodedata


def slugify(text: str, max_length: int = 80) -> str:
    """Generate a clean URL/filename safe slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    if not text:
        text = "unnamed"
    return text[:max_length].rstrip("-")
