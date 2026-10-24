"""Learning from corrections, and comparing the main and the fast model."""
from tekst.compare import disagreements
from tekst.learn import Learner, compare


def cue(text, start=0.0):
    return {"start": start, "end": start + 2, "text": text}


# ---------------------------------------------------------------- learn.compare
def test_compare_finds_word_replacements_and_edit_rate():
    pairs, rate = compare([cue("Vi jobber i Telenord med bærekraft")], [cue("Vi jobber i Telenor med bærekraft")])
    assert pairs == {("Telenord", "Telenor")}
    assert rate == round(1 / 6, 4)


def test_compare_ignores_small_words_and_case():
    pairs, _ = compare([cue("og så gikk vi")], [cue("i så gikk vi")])
    assert pairs == set()
    pairs, rate = compare([cue("Hei")], [cue("hei")])
    assert pairs == set() and rate == 0.0


# ---------------------------------------------------------------- Learner
def test_rule_activates_after_two_videos(tmp_path):
    lr = Learner(tmp_path / "corrections.json")
    orig, fixed = [cue("Møte i Telenord i dag")], [cue("Møte i Telenor i dag")]
    lr.update_project("v1", orig, fixed)
    assert lr.active() == []                       # seen once: only a suggestion
    lr.update_project("v2", orig, fixed)
    assert [r["b"] for r in lr.active()] == ["Telenor"]
    assert lr.hint_words() == ["Telenor"]


def test_apply_keeps_capitals_and_reports_fixes(tmp_path):
    lr = Learner(tmp_path / "c.json")
    for v in ("v1", "v2"):
        lr.update_project(v, [cue("hos telenord nå")], [cue("hos telenor nå")])
    cues = [cue("Telenord vokser", 3.0), cue("Ingenting her", 6.0)]
    fixes = lr.apply(cues)
    assert cues[0]["text"] == "Telenor vokser"
    assert cues[1]["text"] == "Ingenting her"
    assert fixes == [{"t": 3.0, "a": "Telenord", "b": "Telenor"}]


def test_undoing_an_automatic_fix_counts_against_the_rule(tmp_path):
    lr = Learner(tmp_path / "c.json")
    for v in ("v1", "v2"):
        lr.update_project(v, [cue("i Telenord")], [cue("i Telenor")])
    lr.update_project("v3", [cue("i Telenor")], [cue("i Telenord")])  # the user changed it back
    assert lr.active() == []
    assert lr.rules()[0]["rejected"] == 1


def test_manual_state_and_forgetting(tmp_path):
    lr = Learner(tmp_path / "c.json")
    lr.update_project("v1", [cue("i Telenord")], [cue("i Telenor")])
    key = lr.rules()[0]["key"]
    lr.set_state(key, "on")
    assert lr.active()                              # switched on by hand: active after one video
    lr.set_state(key, "off")
    assert not lr.active()
    lr.forget_project("v1")
    assert lr.rules()[0]["videos"] == 0             # kept: the user chose a state for it
    lr.set_state(key, "delete")
    assert lr.rules() == []


# ---------------------------------------------------------------- compare.disagreements
def w(text, s):
    return {"w": " " + text, "s": s, "e": s + 0.3}


def test_disagreement_is_found_with_its_time():
    main = [w("vi", 1.0), w("har", 1.4), w("lært", 1.8), w("mye", 2.2)]
    alt = [w("vi", 1.0), w("har", 1.4), w("lest", 1.8), w("mye", 2.2)]
    assert disagreements(main, alt) == [{"s": 1.8, "e": 2.1, "a": "lært", "b": "lest"}]


def test_spacing_only_and_fillers_are_not_disagreements():
    main = [w("data", 1.0), w("sentrene", 1.3), w("går", 1.7)]
    alt = [w("datasentrene", 1.0), w("eh", 1.5), w("går", 1.7)]
    assert disagreements(main, alt) == []


def test_fast_model_non_words_are_skipped_when_main_is_a_real_word():
    main = [w("bærekraft", 1.0)]
    alt = [w("bærkraf", 1.0)]
    assert disagreements(main, alt, is_word=lambda t: t.strip() == "bærekraft") == []
    assert len(disagreements(main, alt)) == 1


def test_hints_compare_written_out_words():
    """Subtitles never show abbreviations, so neither may a hint: "f.eks." vs "for eksempel" is no disagreement,
    and a hint offers the written-out form (its "Bruk" button must not put "f.eks." back)."""
    main = [w("vi", 1.0), w("har", 1.4), w("f.eks.", 1.8), w("sett", 2.4)]
    alt = [w("vi", 1.0), w("har", 1.4), w("for", 1.8), w("eksempel", 2.0), w("sett", 2.4)]
    assert disagreements(main, alt, lang="no") == []
    main = [w("det", 1.0), w("er", 1.3), w("bra", 1.6)]
    alt = [w("det", 1.0), w("er", 1.3), w("ca.", 1.6)]
    assert [d["b"] for d in disagreements(main, alt, lang="no")] == ["cirka."]  # last word: it ended the sentence
