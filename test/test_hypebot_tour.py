import hypebot_tour
import music_metadata
import sys
import time
import types


ARTIST_HTML = """
<html>
<head>
<script type="application/ld+json">
[
  {
    "@context": "http://schema.org",
    "@type": "MusicEvent",
    "name": "A Forest of Stars @ Audio",
    "startDate": "2026-11-26T18:30:00Z",
    "url": "https://www.bandsintown.com/e/1038095137-a-forest-of-stars",
    "location": {
      "@type": "Place",
      "name": "Audio",
      "address": {
        "@type": "PostalAddress",
        "addressRegion": "GB",
        "addressLocality": "Glasgow",
        "streetAddress": "14 Midland St",
        "postalCode": "G1 4PP"
      },
      "geo": {
        "@type": "GeoCoordinates",
        "latitude": "55.8575783",
        "longitude": "-4.2579604"
      }
    },
    "performer": {"@type": "PerformingGroup", "name": "A Forest of Stars"},
    "offers": {
      "@type": "Offer",
      "url": "https://www.bandsintown.com/e/1038095137-a-forest-of-stars",
      "price": 65,
      "priceCurrency": "USD"
    }
  }
]
</script>
<script type="application/ld+json">
{
  "@context": "http://schema.org",
  "@type": "MusicGroup",
  "name": "A Forest of Stars"
}
</script>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [{
    "@type": "Question",
    "name": "Is A Forest of Stars on tour?",
    "acceptedAnswer": {
      "@type": "Answer",
      "text": "Yes, A Forest of Stars is currently on tour."
    }
  }]
}
</script>
</head>
</html>
"""


def test_parse_artist_page_extracts_jsonld_events():
    result = hypebot_tour.parse_artist_page(ARTIST_HTML, "https://concerts.hypebot.com/artist/a/328642-a-forest-of-stars")

    assert result["artist"] == "A Forest of Stars"
    assert len(result["events"]) == 1
    event = result["events"][0]
    assert event["date"] == "2026-11-26"
    assert event["time"] == "18:30"
    assert event["month"] == "Nov"
    assert event["day"] == "26"
    assert event["venue"] == "Audio"
    assert event["city"] == "Glasgow"
    assert event["price"] == "65 USD"
    assert event["url"] == "https://www.bandsintown.com/e/1038095137-a-forest-of-stars"
    assert result["message"] == "Yes, A Forest of Stars is currently on tour."


def test_parse_artist_links_extracts_index_artist_pages():
    html = """
    <a href="/artist/a/1241311-alcest">Alcest</a>
    <a href="/artist/a/328642-a-forest-of-stars">A Forest of Stars</a>
    <a href="/artist/a/328642-a-forest-of-stars">A Forest of Stars</a>
    """

    links = hypebot_tour.parse_artist_links(html, artist="A Forest of Stars", limit=2)

    assert links[0] == {
        "name": "A Forest of Stars",
        "url": "https://concerts.hypebot.com/artist/a/328642-a-forest-of-stars",
    }
    assert len(links) == 2


def test_parse_artist_links_can_require_exact_artist_match():
    html = """
    <a href="/artist/b/1729-behemoth">BEHEMOTH</a>
    <a href="/artist/b/26335-blink-182">Blink-182</a>
    """

    assert hypebot_tour.parse_artist_links(html, artist="Blur", limit=1, exact_artist=True) == []


def test_parse_artist_links_rejects_partial_name_match():
    html = """
    <a href="/artist/h/123-huey">Huey</a>
    <a href="/artist/h/456-huey-lewis-and-the-news">Huey Lewis and the News</a>
    """

    links = hypebot_tour.parse_artist_links(html, artist="Huey Lewis", limit=1, exact_artist=True)

    assert links == [{
        "name": "Huey Lewis and the News",
        "url": "https://concerts.hypebot.com/artist/h/456-huey-lewis-and-the-news",
    }]


def test_parse_artist_links_uses_fuzzy_artist_match_after_exact_miss():
    html = """
    <a href="/artist/a/328642-a-forest-of-stars">A Forest of Stars</a>
    <a href="/artist/a/1241311-alcest">Alcest</a>
    """

    links = hypebot_tour.parse_artist_links(html, artist="Forest Stars", limit=1, exact_artist=True)

    assert links == [{
        "name": "A Forest of Stars",
        "url": "https://concerts.hypebot.com/artist/a/328642-a-forest-of-stars",
    }]


def test_artist_tour_hypebot_empty_falls_back_to_ai():
    fake_hypebot = types.SimpleNamespace(
        fetch_artist_concerts=lambda **kwargs: {
            "artist": kwargs.get("artist", ""),
            "events": [],
            "source": "Hypebot/Bandsintown",
        }
    )
    fake_ai = types.SimpleNamespace(
        fetch_tour=lambda *args, **kwargs: {
            "artist": args[0],
            "events": [{"date": "2026-01-01", "venue": "AI Hall"}],
            "source": "Duck.ai",
        }
    )
    fake_db = types.SimpleNamespace(
        save_artist_tour=lambda key, payload: None,
        get_artist_tour=lambda key, max_age: None,
    )
    old_modules = {name: sys.modules.get(name) for name in ("hypebot_tour", "tour_ai", "db")}
    sys.modules["hypebot_tour"] = fake_hypebot
    sys.modules["tour_ai"] = fake_ai
    sys.modules["db"] = fake_db
    try:
        result = music_metadata.artist_tour("", "Example Artist", live=True, tour_source="hypebot")
        assert result["events"][0]["venue"] == "AI Hall"
        assert result["fallback_from"] == "Hypebot/Bandsintown"
    finally:
        for name, module in old_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_artist_tour_hypebot_no_tour_message_does_not_fallback_to_ai():
    fake_hypebot = types.SimpleNamespace(
        fetch_artist_concerts=lambda **kwargs: {
            "artist": kwargs.get("artist", ""),
            "pages": [{"artist": kwargs.get("artist", ""), "events": []}],
            "events": [],
            "message": "No, Sade is not currently on tour.",
            "source": "Hypebot/Bandsintown",
        }
    )
    fake_ai = types.SimpleNamespace(
        fetch_tour=lambda *args, **kwargs: {
            "artist": args[0],
            "events": [{"date": "2026-01-01", "venue": "AI Hall"}],
            "source": "Duck.ai",
        }
    )
    fake_db = types.SimpleNamespace(
        save_artist_tour=lambda key, payload: None,
        get_artist_tour=lambda key, max_age: None,
    )
    old_modules = {name: sys.modules.get(name) for name in ("hypebot_tour", "tour_ai", "db")}
    sys.modules["hypebot_tour"] = fake_hypebot
    sys.modules["tour_ai"] = fake_ai
    sys.modules["db"] = fake_db
    try:
        result = music_metadata.artist_tour("", "Sade", live=True, tour_source="hypebot")
        assert result["events"] == []
        assert result["message"] == "No, Sade is not currently on tour."
        assert "fallback_from" not in result
    finally:
        for name, module in old_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_artist_tour_payload_url_forces_hypebot_direct_fetch():
    captured = {}
    saved = {}

    def fake_fetch_artist_concerts(**kwargs):
        captured.update(kwargs)
        return {
            "artist": kwargs.get("artist", ""),
            "events": [{"date": "2026-11-26", "venue": "Audio"}],
            "pages": [{"artist": "A Forest of Stars", "url": kwargs.get("url", ""), "events": []}],
            "source": "Hypebot/Bandsintown",
        }

    fake_hypebot = types.SimpleNamespace(fetch_artist_concerts=fake_fetch_artist_concerts)
    fake_ai = types.SimpleNamespace(
        fetch_tour=lambda *args, **kwargs: {
            "artist": args[0],
            "events": [{"date": "2026-01-01", "venue": "AI Hall"}],
            "source": "Duck.ai",
        }
    )
    fake_db = types.SimpleNamespace(
        save_artist_tour=lambda key, payload: saved.update({"key": key, "payload": payload}),
        get_artist_tour=lambda key, max_age: None,
    )
    old_modules = {name: sys.modules.get(name) for name in ("hypebot_tour", "tour_ai", "db")}
    sys.modules["hypebot_tour"] = fake_hypebot
    sys.modules["tour_ai"] = fake_ai
    sys.modules["db"] = fake_db
    try:
        url = "https://concerts.hypebot.com/artist/a/328642-a-forest-of-stars"
        result = music_metadata.artist_tour(
            "",
            "A Forest of Stars",
            live=False,
            tour_source="ai",
            tour_url=url,
        )
        assert captured["url"] == url
        assert result["events"][0]["venue"] == "Audio"
        assert result["source"] == "Hypebot/Bandsintown"
        assert result["hypebot_url"] == url
        assert result["artist_url"] == url
        assert result["tour_url"] == url
        assert result["cached_at_iso"]
        assert result["expires_at_iso"]
        assert saved["payload"]["hypebot_url"] == url
    finally:
        for name, module in old_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_artist_tour_stale_cache_marks_refresh_needed():
    old_cached_at = time.time() - music_metadata._TOUR_CACHE_TTL - 5
    fake_db = types.SimpleNamespace(
        save_artist_tour=lambda key, payload: None,
        get_artist_tour=lambda key, max_age: {
            "artist": "Sade",
            "events": [],
            "source": "Hypebot/Bandsintown",
            "message": "No, Sade is not currently on tour.",
            "cached_at": old_cached_at,
        },
    )
    old_db = sys.modules.get("db")
    sys.modules["db"] = fake_db
    try:
        result = music_metadata.artist_tour("", "Sade", live=False)
        assert result["pending"] is True
        assert result["refresh_needed"] is True
        assert result["stale"] is True
        assert result["cached_at_iso"]
        assert result["expires_at_iso"]
    finally:
        if old_db is None:
            sys.modules.pop("db", None)
        else:
            sys.modules["db"] = old_db
