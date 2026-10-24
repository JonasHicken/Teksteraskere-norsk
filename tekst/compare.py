"""Find places where two transcriptions of the same audio disagree (main model vs. fast model)."""
import difflib
import re

from .segment import FILLER_RE, Word, expand_abbreviations


def _norm(w):
    return re.sub(r"\W+", "", w.lower())


def _tokens(words):
    out = []
    for w in words:
        n = _norm(w["w"])
        if n and not FILLER_RE.match(n):
            out.append((n, w))
    return out


def _written_out(words, lang):
    """The words as the subtitles show them: abbreviations written out (segment.expand_abbreviations)."""
    ws = expand_abbreviations([Word(w["w"].strip(), w["s"], w["e"], w.get("p", 1.0)) for w in words], lang)
    return [{"w": " " + w.text, "s": w.start, "e": w.end, "p": w.prob} for w in ws]


def disagreements(main_words, alt_words, is_word=None, lang=None):
    """Return [{"s","e","a","b"}]: a = main model's text, b = fast model's text for the same spot.

    is_word(text) -> bool (dictionary check). When given, spots where the fast model only
    produced non-words while the main model produced real words are skipped (main is almost surely right).
    lang ("no"/"nn"): compare the words as the subtitles write them, so "f.eks." vs "for eksempel" is no
    disagreement and a hint never offers an abbreviation.
    """
    if lang:
        main_words, alt_words = _written_out(main_words, lang), _written_out(alt_words, lang)
    A, B = _tokens(main_words), _tokens(alt_words)
    sm = difflib.SequenceMatcher(None, [t for t, _ in A], [t for t, _ in B], autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        a_words = [w for _, w in A[i1:i2]]
        b_words = [w for _, w in B[j1:j2]]
        a_txt = " ".join(w["w"].strip() for w in a_words)
        b_txt = " ".join(w["w"].strip() for w in b_words)
        if "".join(t for t, _ in A[i1:i2]) == "".join(t for t, _ in B[j1:j2]):
            continue  # only spacing differs ("data sentrene" vs "datasentrene")
        if is_word and a_words and b_words:
            a_ok = all(is_word(w["w"]) for w in a_words)
            b_ok = all(is_word(w["w"]) for w in b_words)
            if a_ok and not b_ok:
                continue
        span = a_words or b_words
        if not span:
            continue
        s = min(w["s"] for w in span)
        e = max(w["e"] for w in span)
        if not a_words:  # main model skipped something: anchor between neighbours
            s = A[i1 - 1][1]["e"] if i1 > 0 else s
            e = A[i1][1]["s"] if i1 < len(A) else e
        out.append({"s": round(s, 3), "e": round(max(e, s + 0.05), 3), "a": a_txt, "b": b_txt})
    return out
