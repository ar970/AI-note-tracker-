"""[4] Video links.

The rule that makes this useful instead of noise: **only surface links for
concepts the lecturer moved past quickly.** "Here are five videos about
marketing" is something a student can get from a search box and will ignore.
"You were lost when he did price elasticity in ninety seconds, here is that
one idea explained properly" is the actual need.

So the gate is `coverage == "rushed"` on the master artifact's concepts. If a
lecture was taught well, this section is empty, and that is the correct output.
"""

from __future__ import annotations

import urllib.parse

import requests

SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
MAX_CONCEPTS = 5

# Ranking bonus, not a hard filter — a hard allowlist returns nothing for most
# Indian syllabus topics, which is worse than a slightly noisier list.
TRUSTED_CHANNELS = {
    "khan academy", "nptel", "mit opencourseware", "3blue1brown", "crashcourse",
    "veritasium", "ted-ed", "unacademy", "byju's", "physics wallah", "neso academy",
    "gate smashers", "statquest with josh starmer", "harvard business review",
    "yale courses", "stanford graduate school of business", "computerphile",
}


def build_query(concept: str, course: str | None) -> str:
    """Bias toward explanation, away from full lecture recordings — a student
    who missed ninety seconds will not watch another fifty-minute lecture."""
    subject = (course or "").split("—")[0].strip()
    return " ".join(part for part in [concept, subject, "explained"] if part)


def search_url(query: str) -> str:
    return "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query})


def _score(channel: str, title: str) -> int:
    score = 0
    if channel.strip().lower() in TRUSTED_CHANNELS:
        score += 10
    lowered = title.lower()
    if any(word in lowered for word in ("explained", "tutorial", "introduction", "basics")):
        score += 2
    if any(word in lowered for word in ("full lecture", "complete course", "marathon", "one shot")):
        score -= 3
    return score


def _api_search(query: str, api_key: str, limit: int = 3) -> list[dict]:
    response = requests.get(
        SEARCH_ENDPOINT,
        params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": 8,
            "videoCategoryId": "27",  # Education
            "relevanceLanguage": "en",
            "safeSearch": "strict",
            "key": api_key,
        },
        timeout=30,
    )
    response.raise_for_status()
    items = response.json().get("items", [])

    results = [
        {
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
        }
        for item in items
        if item.get("id", {}).get("videoId")
    ]
    results.sort(key=lambda r: -_score(r["channel"], r["title"]))
    return results[:limit]


def attach(artifact: dict, api_key: str | None) -> dict:
    """Populate `artifact["videos"]`. Never fails the run — this is a garnish."""
    rushed = [c for c in artifact.get("concepts", []) if c.get("coverage") == "rushed"]
    rushed.sort(key=lambda c: -c.get("weight", 0.0))
    course = (artifact.get("session") or {}).get("course")

    videos = []
    for concept in rushed[:MAX_CONCEPTS]:
        query = build_query(concept["name"], course)
        entry = {
            "concept": concept["name"],
            "why": "The lecturer moved past this quickly.",
            "query": query,
            "search_url": search_url(query),
            "links": [],
        }
        if api_key:
            try:
                entry["links"] = _api_search(query, api_key)
            except requests.RequestException as exc:
                entry["note"] = f"YouTube lookup failed ({exc}); use the search link."
        else:
            entry["note"] = "No YOUTUBE_API_KEY set — search link only."
        videos.append(entry)

    artifact["videos"] = videos
    return artifact
