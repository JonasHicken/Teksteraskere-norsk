"""Release notes ("Hva er nytt"): static/changelog.json, newest first, one entry per published update."""
import datetime
import json
from pathlib import Path

LOG = json.loads((Path(__file__).resolve().parents[1] / "static/changelog.json").read_text(encoding="utf-8"))


def test_entries_are_numbered_newest_first_without_gaps():
    assert LOG, "the changelog is empty"
    assert [e["n"] for e in LOG] == list(range(len(LOG), 0, -1))


def test_every_entry_has_a_date_a_title_and_notes():
    dates = []
    for e in LOG:
        assert set(e) == {"n", "date", "title", "items"}, e
        dates.append(datetime.date.fromisoformat(e["date"]))
        assert isinstance(e["title"], str) and e["title"].strip()
        assert e["items"] and all(isinstance(x, str) and x.strip() for x in e["items"])
    assert dates == sorted(dates, reverse=True), "dates must not go backwards"
    assert dates[0] <= datetime.date.today() + datetime.timedelta(days=1)
