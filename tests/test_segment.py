"""Segmentation (word timings -> subtitles) and the SRT format."""
import re

import pytest

from tekst import segment
from tekst.segment import make_cues, params, to_srt, ts, wrap_text

TS = r"\d{2}:\d{2}:\d{2},\d{3}"
BLOCK = re.compile(rf"^(\d+)\n({TS}) --> ({TS})\n((?:[^\n]+\n?)+)$")


def words_from(text, start=0.5, per_word=0.32, pause_after=None):
    """Turn a sentence into fake model words, evenly timed; pause_after = {index: extra seconds}."""
    out, t = [], start
    for k, w in enumerate(text.split()):
        out.append({"w": " " + w, "s": round(t, 3), "e": round(t + per_word - 0.05, 3), "p": 0.9})
        t += per_word + (pause_after or {}).get(k, 0.0)
    return out


def parse_srt(text):
    """Strict reader: numbered 1, 2, 3 ..., 'HH:MM:SS,mmm --> HH:MM:SS,mmm', 1+ text lines, one blank line between."""
    blocks = text.strip("\n").split("\n\n") if text.strip() else []
    out = []
    for k, b in enumerate(blocks, 1):
        m = BLOCK.match(b)
        assert m, f"bad block {k}: {b!r}"
        assert int(m.group(1)) == k
        out.append((m.group(2), m.group(3), m.group(4).rstrip("\n")))
    return out


# ----------------------------------------------------------------- timestamps
@pytest.mark.parametrize("sec, expected", [
    (0, "00:00:00,000"),
    (1.0004, "00:00:01,000"),
    (4.09, "00:00:04,090"),          # float noise must not give 4,089
    (59.9996, "00:01:00,000"),        # rounding carries into the minutes
    (3599.9999, "01:00:00,000"),
    (3723.456, "01:02:03,456"),
    (-0.5, "00:00:00,000"),
])
def test_timestamps(sec, expected):
    assert ts(sec) == expected


# ------------------------------------------------------------------------ SRT
def test_srt_is_strict_and_clean():
    cues = [
        {"start": 5.0, "end": 7.5, "text": "Kommer etter"},
        {"start": 0.6, "end": 4.09, "text": "Hei og velkommen\npresentasjonen."},
        {"start": 8.0, "end": 9.0, "text": "   "},                                   # empty: skipped
        {"start": 9.5, "end": 11.0, "text": "  Mellomrom  \n\n  og tom linje  "},
        {"start": 12.0, "end": 14.0, "text": "Æøå «sitat» – … “x” < & >"},
        {"start": 14.5, "end": 16.0, "text": "Tall alene:\n2019"},
        {"start": 16.5, "end": 18.0, "text": "Pil --> her"},
        {"start": 18.5, "end": 20.0, "text": "Windows\r\nlinjeskift"},
    ]
    blocks = parse_srt(to_srt(cues))
    assert [b[2] for b in blocks] == [
        "Hei og velkommen\npresentasjonen.", "Kommer etter", "Mellomrom\nog tom linje",
        "Æøå «sitat» – … “x” < & >", "Tall alene:\n2019", "Pil --> her", "Windows\nlinjeskift",
    ]
    assert blocks[0][:2] == ("00:00:00,600", "00:00:04,090")
    assert "\n\n\n" not in to_srt(cues)


def test_empty_project_gives_empty_file():
    assert to_srt([]) == ""


# ---------------------------------------------------------------- segmenting
LONG = ("I dag skal vi snakke om hvordan Telenor Norge har jobbet med bærekraft de siste fem årene, "
        "og hva vi har lært underveis. For det første er det viktig å forstå at utslippene våre har gått "
        "ned med 23 prosent siden 2019. Det er et resultat av mange små og store endringer i hele organisasjonen.")


def test_cues_follow_the_rules():
    p = params()
    cues = make_cues(words_from(LONG, pause_after={16: 0.8, 35: 0.8}), p)
    assert len(cues) > 3
    for k, c in enumerate(cues):
        lines = c["text"].split("\n")
        assert len(lines) <= 2
        assert all(len(l) <= p.max_chars + p.char_slack for l in lines), c["text"]
        assert c["end"] - c["start"] <= p.max_dur + 1e-6
        assert c["end"] > c["start"]
        if k:
            assert c["start"] - cues[k - 1]["end"] >= p.gap - 1e-6, "cues must not overlap"
    # nothing is lost or reordered
    assert " ".join(c["text"].replace("\n", " ") for c in cues) == LONG


def test_number_stays_with_its_unit():
    cues = make_cues(words_from(LONG), params())
    assert any("23 prosent" in c["text"].replace("\n", " ") for c in cues)


SAMPLES = [
    "Vi har jobbet med dette prosjektet i over to år nå, og vi er veldig stolte av resultatet vi har fått. "
    "Nå skal vi vise dere hvordan det fungerer i praksis for kundene våre.",
    "Det viktigste for oss er at de ansatte trives på jobben hver eneste dag. Derfor har vi satset mye på "
    "trivsel og et godt arbeidsmiljø. Det har gitt resultater som vi er stolte av i dag.",
    "Når vi ser på tallene fra i fjor, ser vi at salget økte betydelig i alle regionene våre. Spesielt i nord "
    "gikk det bra. Vi tror at det skyldes den nye strategien vi innførte tidlig på året.",
    "Hei og velkommen til denne videoen om sikkerhet på arbeidsplassen. I dag skal vi snakke om tre viktige "
    "ting som alle bør kjenne til. Først skal vi se på brannvern og rømningsveier i bygget.",
    "Kundene våre forventer rask levering og god service hver eneste gang de handler hos oss. Dette er noe vi "
    "tar på alvor. Vi har derfor investert i nye systemer som gjør hverdagen enklere for alle.",
]
ENDS = re.compile(r"[.!?…]$")


@pytest.mark.parametrize("text", SAMPLES)
def test_no_word_is_cut_off_from_its_sentence(text):
    """The end user's complaint: the last word of a sentence ended up alone in the next subtitle (or line)."""
    cues = make_cues(words_from(text), params())
    for a, b in zip(cues, cues[1:]):
        assert not (not ENDS.search(a["text"]) and ENDS.search(b["text"].split()[0])), (a["text"], b["text"])
    for c in cues:
        lines = c["text"].split("\n")
        if len(lines) == 2:
            assert not (ENDS.search(lines[1].split()[0]) and not ENDS.search(lines[0])), c["text"]


def test_a_line_may_go_a_little_over_the_limit_but_never_past_the_slack():
    p = params()
    lines = segment.split_lines([segment.Word(w, 0, 0) for w in
                                 "Vi har jobbet hardt med å forbedre rutinene, og nå ser vi resultatet".split()], p)[0]
    assert all(len(l) <= p.max_chars for l in lines)  # within the limit when that works well
    long_word = "x" * 45
    assert segment.split_lines([segment.Word(w, 0, 0) for w in ["Hei", long_word]], p)[0] == ["Hei", long_word]
    assert segment.split_lines([segment.Word(w, 0, 0) for w in ["Hei", "x" * 47]], p) is None  # past 42 + 4
    assert segment.split_lines([segment.Word(w, 0, 0) for w in ["Hei", long_word]], params(char_slack=0)) is None


def text_of(raw, **kw):
    return " ".join(c["text"].replace("\n", " ") for c in make_cues(words_from(raw), params(**kw)))


def test_abbreviations_are_written_out():
    assert text_of("Vi har f.eks. sett at bl.a. prisene har økt, osv. Neste år blir det ca. ti prosent bedre.") == (
        "Vi har for eksempel sett at blant annet prisene har økt, og så videre. "
        "Neste år blir det cirka ti prosent bedre.")
    assert text_of("F.eks. dette, feks det, og pga. været osv") == (
        "For eksempel dette, for eksempel det, og på grunn av været og så videre")
    assert text_of("Vi ser f. eks. at det går bra.") == "Vi ser for eksempel at det går bra."
    assert text_of("Dette gjeld t.d. bygget, dvs. alt.", lang="nn") == "Dette gjeld til dømes bygget, det vil seie alt."
    assert text_of("Ordet bla og kr står igjen.") == "Ordet bla og kroner står igjen."


def test_written_out_words_share_the_abbreviations_time():
    w = words_from("Vi ser f.eks. bygget")
    words = segment.expand_abbreviations([segment.Word(x["w"].strip(), x["s"], x["e"]) for x in w])
    assert [x.text for x in words] == ["Vi", "ser", "for", "eksempel", "bygget"]
    assert words[2].start == w[2]["s"] and abs(words[3].end - w[2]["e"]) < 1e-9 and words[2].end == words[3].start


def test_fillers_are_removed_and_next_word_capitalised():
    cues = make_cues(words_from("Hei. eh vi starter nå. ehm og så videre"), params())
    text = " ".join(c["text"] for c in cues)
    assert "eh" not in text.split() and "ehm" not in text.split()
    assert "Vi starter" in text.replace("\n", " ")


def test_collapse_repeats_only_when_switched_on():
    w = words_from("jeg jeg tror det")
    assert "jeg jeg" in make_cues(w, params())[0]["text"]
    assert make_cues(words_from("jeg jeg tror det"), params(collapse_repeats=True))[0]["text"].startswith("jeg tror")


def test_comma_glued_to_next_word_is_given_back():
    w = words_from("Hei trøndere velkommen")
    w[1]["w"] = ",trøndere"
    assert make_cues(w, params())[0]["text"].startswith("Hei, trøndere")


def test_wrap_text_balances_two_lines():
    text = "Det er et resultat av mange små og store endringer i hele organisasjonen,"
    lines = wrap_text(text, params()).split("\n")
    assert len(lines) == 2
    assert all(len(l) <= 42 for l in lines)
    assert abs(len(lines[0]) - len(lines[1])) < 15
    assert wrap_text("Kort tekst", params()) == "Kort tekst"
    assert wrap_text("   ", params()) == ""


def test_params_ignores_unknown_keys():
    p = params({"max_chars": 37, "nonsense": 1})
    assert p.max_chars == 37 and isinstance(p, segment.P)
