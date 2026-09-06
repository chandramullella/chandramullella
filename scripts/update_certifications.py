"""
Fetch Credly badges for a user and regenerate the categorized certifications
section of a markdown file (e.g. README.md), between the markers:

    <!-- START CREDLY BADGES -->
    ...generated content...
    <!-- END CREDLY BADGES -->

Badges are grouped into sections by matching their title against the regex
patterns in CATEGORIES (checked top to bottom, first match wins). Anything
that doesn't match lands in the "Other" section. Add/adjust patterns below
as your badge collection grows (e.g. an "Azure" category).

Environment variables:
    CREDLY_USERNAME   Credly profile username (required)
    BADGE_SIZE        Image size, e.g. "85x85" (default: 85x85)
    BADGE_SORT_BY     "issued" or "updated" (default: issued) - controls
                       which timestamp badges are sorted by, newest first
    README_FILE       Path to the markdown file to update (default: README.md)
    GITHUB_OUTPUT     If set (provided automatically by GitHub Actions),
                       writes `changed=true|false` so the workflow can decide
                       whether to commit.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import requests

CREDLY_USERNAME = os.environ.get("CREDLY_USERNAME", "")
BADGE_SIZE = os.environ.get("BADGE_SIZE", "85x85")
SORT_BY = os.environ.get("BADGE_SORT_BY", "issued")
README_FILE = os.environ.get("README_FILE", "README.md")

START = "<!-- START CREDLY BADGES -->"
END = "<!-- END CREDLY BADGES -->"

# (Section title, emoji, [regex patterns matched against the lowercased badge name])
CATEGORIES: list[tuple[str, str, list[str]]] = [
    ("Amazon (AWS)", "☁️", [r"\baws\b", r"\bamazon\b"]),
    ("Kubernetes", "⎈", [r"kubernetes", r"\bcka\b", r"ckad", r"\bcks\b", r"kcna", r"kcsa", r"gitops"]),
    ("Google Cloud (GCP)", "🌐", [r"google cloud", r"\bgcp\b", r"cloud engineer", r"cloud architect", r"cloud digital leader"]),
]
OTHER_TITLE, OTHER_EMOJI = "Other", "📚"


def fetch_badges(username: str) -> list[dict]:
    """Pull the public badge list from Credly's JSON endpoint."""
    url = f"https://www.credly.com/users/{username}/badges.json"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json().get("data", [])

    badges = []
    for badge in data:
        badge_id = badge.get("id")
        template = badge.get("badge_template", {}) or {}
        name = (template.get("name") or "").strip()
        image_url = (template.get("image_url") or "").strip()
        state = badge.get("state", "accepted")

        if not (badge_id and name and image_url) or state == "revoked":
            continue

        sort_key = ""
        if SORT_BY == "updated":
            sort_key = badge.get("updated_at") or badge.get("issued_at") or ""
        else:
            sort_key = badge.get("issued_at") or badge.get("updated_at") or ""

        image_url = image_url.replace(
            "https://images.credly.com/images/",
            f"https://images.credly.com/size/{BADGE_SIZE}/images/",
        )
        badges.append(
            {
                "name": name,
                "url": f"https://www.credly.com/badges/{badge_id}",
                "image_url": image_url,
                "sort_key": sort_key,
            }
        )

    badges.sort(key=lambda b: b["sort_key"], reverse=True)
    return badges


def categorize(badges: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {title: [] for title, _emoji, _patterns in CATEGORIES}
    buckets[OTHER_TITLE] = []

    for badge in badges:
        name_lower = badge["name"].lower()
        placed = False
        for title, _emoji, patterns in CATEGORIES:
            if any(re.search(p, name_lower) for p in patterns):
                buckets[title].append(badge)
                placed = True
                break
        if not placed:
            buckets[OTHER_TITLE].append(badge)

    return buckets


def render_section(buckets: dict[str, list[dict]]) -> str:
    titles = [t for t, _e, _p in CATEGORIES] + [OTHER_TITLE]
    emojis = {t: e for t, e, _p in CATEGORIES}
    emojis[OTHER_TITLE] = OTHER_EMOJI

    blocks = []
    for title in titles:
        items = buckets.get(title, [])
        if not items:
            continue
        lines = "\n".join(f"[![{b['name']}]({b['image_url']})]({b['url']})" for b in items)
        blocks.append(f"### {emojis[title]} {title}\n{lines}")

    return "\n\n".join(blocks)


def update_readme(path: Path, new_section: str) -> bool:
    content = path.read_text(encoding="utf-8")
    if START not in content or END not in content:
        print(f"ERROR: markers not found in {path}", file=sys.stderr)
        sys.exit(1)

    before, rest = content.split(START, 1)
    _old, after = rest.split(END, 1)
    new_content = f"{before}{START}\n{new_section}\n{END}{after}"

    if new_content == content:
        return False

    path.write_text(new_content, encoding="utf-8")
    return True


def main() -> None:
    if not CREDLY_USERNAME:
        print("ERROR: CREDLY_USERNAME environment variable is required.", file=sys.stderr)
        sys.exit(1)

    badges = fetch_badges(CREDLY_USERNAME)
    print(f"Fetched {len(badges)} badge(s) from Credly for '{CREDLY_USERNAME}'.")

    buckets = categorize(badges)
    for title, items in buckets.items():
        print(f"  {title}: {len(items)}")

    section = render_section(buckets)
    changed = update_readme(Path(README_FILE), section)

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")

    print("README updated." if changed else "No changes needed.")


if __name__ == "__main__":
    main()