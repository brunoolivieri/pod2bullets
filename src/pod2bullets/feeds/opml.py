"""OPML import and export preserving subscription categories/lists."""

import xml.etree.ElementTree as ET
from typing import Any


def parse_opml(opml_content: str) -> list[dict[str, Any]]:
    """Parse OPML XML content and extract feeds grouped by category/folder."""
    root = ET.fromstring(opml_content)
    body = root.find("body")
    if body is None:
        return []

    results = []

    def process_outline(outline: ET.Element, current_category: str | None = None):
        xml_url = outline.get("xmlUrl") or outline.get("xmlurl")
        text = outline.get("text") or outline.get("title") or "Sem Nome"
        html_url = outline.get("htmlUrl") or outline.get("htmlurl")

        if xml_url:
            results.append(
                {
                    "title": text,
                    "rss_url": xml_url,
                    "site_url": html_url,
                    "category": current_category,
                }
            )
        else:
            # It is a folder/category node
            new_cat = text if text else current_category
            for child in outline.findall("outline"):
                process_outline(child, new_cat)

    for top_outline in body.findall("outline"):
        process_outline(top_outline)

    return results


def generate_opml(feeds_with_lists: list[dict[str, Any]]) -> str:
    """Generate OPML XML string from feeds and their lists."""
    root = ET.Element("opml", version="2.0")
    head = ET.SubElement(root, "head")
    title = ET.SubElement(head, "title")
    title.text = "pod2bullets Subscriptions"
    body = ET.SubElement(root, "body")

    # Group by category
    categories: dict[str, list[dict]] = {}
    uncategorized = []

    for item in feeds_with_lists:
        cat = item.get("category")
        if cat:
            categories.setdefault(cat, []).append(item)
        else:
            uncategorized.append(item)

    for cat_name, cat_feeds in categories.items():
        cat_outline = ET.SubElement(body, "outline", text=cat_name, title=cat_name)
        for feed in cat_feeds:
            ET.SubElement(
                cat_outline,
                "outline",
                type="rss",
                text=feed["title"],
                title=feed["title"],
                xmlUrl=feed["rss_url"],
                htmlUrl=feed.get("site_url") or "",
            )

    for feed in uncategorized:
        ET.SubElement(
            body,
            "outline",
            type="rss",
            text=feed["title"],
            title=feed["title"],
            xmlUrl=feed["rss_url"],
            htmlUrl=feed.get("site_url") or "",
        )

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
