"""Release notes ("Hva er nytt"): static/changelog.json, newest first, one entry per published update."""
import datetime
import json
from pathlib import Path

LOG = json.loads((Path(__file__).resolve().parents[1] / "static/changelog.json").read_text(encoding="utf-8"))


def test_entries_are_numbered_newest_first_without_gaps():
    assert LOG, "the changelog is empty"
    assert [e["n"] for e in LOG] == list(range(len(LOG), 0, -1))


def test_every_entry_has_a_date_and_notes_in_norwegian_and_english():
    dates = []
    for e in LOG:
        assert set(e) == {"n", "date", "no", "en"}, e
        dates.append(datetime.date.fromisoformat(e["date"]))
        for lang in ("no", "en"):
            txt = e[lang]
            assert set(txt) == {"title", "items"}, (e["n"], lang)
            assert isinstance(txt["title"], str) and txt["title"].strip()
            assert txt["items"] and all(isinstance(x, str) and x.strip() for x in txt["items"])
        assert len(e["no"]["items"]) == len(e["en"]["items"]), f"update {e['n']}: the translations differ"
    assert dates == sorted(dates, reverse=True), "dates must not go backwards"
    assert dates[0] <= datetime.date.today() + datetime.timedelta(days=1)
