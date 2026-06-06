import tour_ai


def test_extract_json_array_accepts_events_object():
    payload = """
    {
      "artist": "Example",
      "events": [
        {"date": "2026-08-14", "place": "Paris", "venue": "Zenith"}
      ]
    }
    """
    events = tour_ai._extract_json_array(payload)
    assert isinstance(events, list)
    assert events and events[0]["venue"] == "Zenith"
