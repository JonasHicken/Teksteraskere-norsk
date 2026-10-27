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


def natural(text, per_word=0.32, pauses=True):
    """Model words for a sample, optionally with the short pauses people make after sentences and commas."""
    pa = {k: (0.45 if w.endswith(".") else 0.15) for k, w in enumerate(text.split()) if w[-1] in ".,"}
    return words_from(text, per_word=per_word, pause_after=pa if pauses else None)


# normal, fast and slow speech, with and without natural pauses
SPEECH = [(per, pauses) for per in (0.26, 0.32, 0.40) for pauses in (True, False)]


@pytest.mark.parametrize("text", SAMPLES)
@pytest.mark.parametrize("per_word, pauses", SPEECH)
def test_no_word_is_cut_off_from_its_sentence(text, per_word, pauses):
    """The end user's complaint: the last word of a sentence ended up alone in the next subtitle (or line)."""
    cues = make_cues(natural(text, per_word, pauses), params())
    for a, b in zip(cues, cues[1:]):
        assert not (not ENDS.search(a["text"]) and ENDS.search(b["text"].split()[0])), (a["text"], b["text"])
    for c in cues:
        lines = c["text"].split("\n")
        if len(lines) == 2:
            assert not (ENDS.search(lines[1].split()[0]) and not ENDS.search(lines[0])), c["text"]


@pytest.mark.parametrize("per_word, pauses", SPEECH)
def test_two_lines_are_about_the_same_length(per_word, pauses):
    """End user: lines over each other should be about the same length (unless that would split a phrase)."""
    diffs = []
    for text in SAMPLES + [LONG]:
        for c in make_cues(natural(text, per_word, pauses), params()):
            lines = c["text"].split("\n")
            if len(lines) == 2:
                diffs.append(abs(len(lines[0]) - len(lines[1])))
    assert diffs and sum(diffs) / len(diffs) <= 8, diffs
    # 13/37 "Vi har jobbet / med dette prosjektet i over to år nå,": the other splits are "dette / prosjektet"
    # (breaks a phrase) or 34/16 (longer line on top)
    assert max(diffs) <= 24, diffs


@pytest.mark.parametrize("per_word, pauses", SPEECH)
def test_the_longer_line_is_the_bottom_one(per_word, pauses):
    """End user: if one line is longer, it should be the bottom one. The only exception is when every such
    split would break a phrase ("den nye / strategien") or need a line over 42."""
    p = params()
    for text in SAMPLES + [LONG]:
        for c in make_cues(natural(text, per_word, pauses), p):
            lines = c["text"].split("\n")
            if len(lines) < 2 or len(lines[0]) - len(lines[1]) <= 6:
                continue  # bottom longer, or about the same length
            toks = c["text"].split()
            for k in range(1, len(toks)):
                l1, l2 = " ".join(toks[:k]), " ".join(toks[k:])
                if len(l1) < len(l2):
                    weak = segment.core(toks[k - 1]) in segment.NO_END_STRONG | segment.NO_END_MED
                    assert weak or len(l2) > p.max_chars, (c["text"], l1, l2)  # slack is for sentences, not shape


@pytest.mark.parametrize("text, lines", [
    ("Det er et resultat av mange små og store endringer i hele organisasjonen.",
     ["Det er et resultat av mange små", "og store endringer i hele organisasjonen."]),
    ("Nå skal vi vise dere hvordan det fungerer i praksis for kundene våre.",
     ["Nå skal vi vise dere hvordan", "det fungerer i praksis for kundene våre."]),
    ("Vi tror at det skyldes den nye strategien vi innførte tidlig på året.",  # not "den nye / strategien"
     ["Vi tror at det skyldes den nye strategien", "vi innførte tidlig på året."]),
])
def test_line_breaks_balance_but_keep_phrases_together(text, lines):
    assert wrap_text(text, params()).split("\n") == lines


@pytest.mark.parametrize("text", SAMPLES + [LONG])
@pytest.mark.parametrize("per_word, pauses", SPEECH)
def test_subtitles_split_at_natural_places(text, per_word, pauses):
    p = params()
    cues = make_cues(natural(text, per_word, pauses), p)
    assert " ".join(c["text"].replace("\n", " ") for c in cues) == text  # nothing lost, added or reordered
    for c in cues:
        assert all(len(l) <= p.max_chars + p.char_slack for l in c["text"].split("\n")), c["text"]
        last = c["text"].split()[-1]
        if c is not cues[-1]:
            assert segment.core(last) not in segment.NO_END_STRONG or re.search(r"[.!?,]$", last), c["text"]
            # no short scrap of a clause on its own ("I dag skal || vi snakke om ...")
            assert len(c["text"]) > 15 or re.search(r"[.!?,]$", last), c["text"]


def test_the_pause_after_a_sentence_counts_as_reading_time():
    """A subtitle may stay up into the pause after it, so a full sentence fits instead of losing its end."""
    cues = make_cues(natural(SAMPLES[3]), params())
    assert cues[0]["text"] == "Hei og velkommen til denne videoen\nom sikkerhet på arbeidsplassen.", cues[0]


def test_fast_speech_is_split_at_the_comma_to_keep_the_reading_speed():
    text = "Vi har jobbet med dette prosjektet i over to år nå, og vi er veldig stolte av resultatet vi har fått."
    p = params()
    cues = make_cues(natural(text, per_word=0.24), p)
    assert len(cues) >= 2 and cues[0]["text"].endswith("nå,"), [c["text"] for c in cues]
    # This speech is itself faster than 17 characters per second, so the reading speed can't be met exactly
    # without cutting a clause: it must stay close (in one subtitle it would be far over).
    for c in cues:
        assert len(c["text"].replace("\n", "")) / (c["end"] - c["start"]) <= p.max_cps * 1.1, c


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


def test_mid_sentence_capitals_from_the_model_are_lowered_but_names_keep_theirs():
    """End user: words capitalised for no reason ("på et Det begynner"). The model starts every chunk it hears
    with a capital; everyday words mid-sentence get a small letter, names keep theirs."""
    t = text_of("Og jeg tenker også at det er på et Det begynner å bli giftig. Har Du sett Stortinget og MDG nå?")
    assert t == "Og jeg tenker også at det er på et det begynner å bli giftig. Har du sett Stortinget og MDG nå?"
    assert text_of("Det er bra. Vi ses.") == "Det er bra. Vi ses."  # sentence starts keep the capital


def test_a_sentence_the_model_split_at_a_breath_is_joined_again():
    """End user: "Han liker fotball. Og han går på skole." should be one sentence."""
    assert text_of("Han liker fotball. Og han går på skole.") == "Han liker fotball, og han går på skole."
    assert text_of("Det er bra. Men vi er ikke ferdige.") == "Det er bra, men vi er ikke ferdige."
    assert text_of("Vi blir hjemme. Fordi det regner.") == "Vi blir hjemme fordi det regner."
    assert text_of("Kommer du? Og når?") == "Kommer du? Og når?"  # only after a full stop
    assert text_of("Det er bra. Vi ses.") == "Det er bra. Vi ses."
    w = words_from("Ferdig for i dag. Og nå til noe helt annet.", pause_after={3: 2.0})
    assert "dag. Og nå" in " ".join(c["text"].replace("\n", " ") for c in make_cues(w, params()))  # long pause
    assert text_of("Jeg tror. At det går bra.") == "Jeg tror at det går bra."
    assert text_of("Det regnet. Så vi ble hjemme.") == "Det regnet, så vi ble hjemme."
    assert text_of("Vi spiste. Så gikk vi hjem.") == "Vi spiste. Så gikk vi hjem."  # "så" = then: its own sentence
    assert text_of("Det tok tid. At vi kom fram var flaks.") == "Det tok tid. At vi kom fram var flaks."


def test_missing_comma_between_two_clauses_is_added():
    assert text_of("Han liker fotball og han går på skole.") == "Han liker fotball, og han går på skole."
    assert text_of("Det er dyrt men vi kjøper det.") == "Det er dyrt, men vi kjøper det."
    assert text_of("Vil du ha kaffe eller vil du ha te?") == "Vil du ha kaffe, eller vil du ha te?"
    # og/eller between words, not whole clauses: no comma
    for t in ("Jeg kjøpte epler og pærer.", "Han og jeg kom sent.", "Mamma og pappa og jeg dro.",
              "Vi har kaffe eller te.", "Det er rødt og det blå er fint.", "Men vi er ikke ferdige.",
              "Det er bra, men dyrt."):
        assert text_of(t) == t


def test_written_out_abbreviation_has_a_capital_only_at_a_sentence_start():
    assert text_of("Vi ser F.eks. at det går. F.eks. dette.") == "Vi ser for eksempel at det går. For eksempel dette."
    assert text_of("bra. f.eks. her") == "bra. For eksempel her"


def test_the_models_nocaptions_marker_never_reaches_a_subtitle():
    w = words_from("Du legger deg ikke oppi det")
    marker = [{"w": t, "s": 0.1, "e": 0.2, "p": 0.5} for t in ("|", ">", " <", "|nocaptions", "|", ">")]
    text = " ".join(c["text"].replace("\n", " ") for c in make_cues(marker + w, params()))
    assert text == "Du legger deg ikke oppi det"
