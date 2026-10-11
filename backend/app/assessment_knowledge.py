"""Bounded retrieval of original local health topics for assessment citations."""

from pathlib import Path

from .knowledge import ALIASES, get_topic, official_topic_url, search_topics

MAX_TERMS = 8
MAX_RESULTS = 5
_CANONICAL = {
    alias.casefold(): title
    for title, aliases in ALIASES.items()
    for alias in [title, *aliases]
}


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _terms(episode: dict) -> list[str]:
    symptoms = episode.get("symptoms", [])
    values = [episode.get("diagnosis_name", "")]
    if isinstance(symptoms, list):
        values.extend(symptoms[:20])
    terms, seen = [], set()
    for value in values:
        term = _text(value).strip()
        if (not term or len(term) > 80 or len(term.split()) > 8
                or term.casefold() in seen):
            continue
        seen.add(term.casefold())
        terms.append(term)
        if len(terms) == MAX_TERMS:
            break
    return terms


def retrieve_evidence(path: Path, episode: dict, limit: int = 5) -> list[dict]:
    """OR symptom/diagnosis searches; never search free notes or fetch URLs.

    Chinese originals rank first. Aliases only expand retrieval; excerpts and
    provenance remain unchanged source text, with no diagnostic interpretation.
    """
    count = min(MAX_RESULTS, max(0, limit))
    if not count or not path.is_file():
        return []
    candidates, searched = {}, {}
    for term in _terms(episode):
        queries = dict.fromkeys([term, _CANONICAL.get(term.casefold(), term)])
        for query in queries:
            key = query.casefold()
            if key not in searched:
                searched[key] = search_topics(path, query, page=1, page_size=50)["items"]
            for topic in searched[key]:
                topic_id = _text(topic.get("id"))
                if not topic_id or not official_topic_url(_text(topic.get("source_url"))):
                    continue
                candidate = candidates.setdefault(topic_id, {"topic": topic, "terms": []})
                if term not in candidate["terms"]:
                    candidate["terms"].append(term)
    def direct_matches(item):
        topic = item["topic"]
        names = {_text(value).casefold() for value in [topic.get("title"), *topic.get("aliases", [])]}
        return sum(term.casefold() in names or _CANONICAL.get(term.casefold(), term).casefold() in names
                   or (topic.get("language") == "Chinese" and term in _text(topic.get("title")))
                   for term in item["terms"])

    ranked = sorted(candidates.values(), key=lambda item: (
        -direct_matches(item), item["topic"].get("language") != "Chinese", -len(item["terms"])))
    direct = [item for item in ranked if direct_matches(item)]
    if direct:
        ranked = direct  # Do not fill remaining slots with incidental substring hits.
    evidence = []
    for candidate in ranked[:count]:
        topic = get_topic(path, candidate["topic"]["id"])
        if not topic or not official_topic_url(_text(topic.get("source_url"))):
            continue
        evidence.append({
            "id": _text(topic.get("id")), "title": _text(topic.get("title")),
            "excerpt": _text(topic.get("summary"))[:800],
            **{key: _text(topic.get(key)) for key in (
                "source_url", "source", "published_at", "imported_at")},
            "matched_terms": candidate["terms"],
        })
    return evidence
