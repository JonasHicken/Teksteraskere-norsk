"""Subtitle segmentation: word timings -> Netflix-style cues (Norwegian).

Rules (defaults, adjustable in Settings): max 2 lines of 42 characters, 1-7 s on
screen, max 17 characters per second, at least 0.08 s (2 frames) between cues.
42 is a soft limit: a line may go up to `char_slack` characters over (at a cost per character)
when that keeps a sentence together instead of pushing its last word into the next subtitle.
Abbreviations are always written out ("f.eks." -> "for eksempel"): subtitles show what was said.
"""
import re
from dataclasses import dataclass, fields

@dataclass
class P:  # all tunables in one place
    max_chars: int = 42
    char_slack: int = 4        # lines may run this many characters over max_chars to keep a sentence together
    min_dur: float = 1.0
    max_dur: float = 7.0
    max_cps: float = 17.0
    gap: float = 0.08          # min silence between consecutive cues
    tail: float = 0.30         # how long a cue lingers after the last word
    lead: float = 0.0          # shift cue start earlier (seconds)
    hard_pause: float = 1.2    # never join words across a pause this long
    low_prob: float = 0.0      # >0 flags words below this confidence (off: it was mostly noise)
    gap_warn: float = 3.0      # flag a cue that follows this many seconds of "silence"
    dict_path: str = ""        # folder with nb_NO.aff/.dic (default: ./dict next to this script)
    glossary: str = ""         # names/terms the spell checker should treat as correct
    collapse_repeats: bool = False
    lang: str = "no"           # "no" (bokmål) or "nn" (nynorsk): how abbreviations are written out


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float = 1.0


# ---------------------------------------------------------------- cleaning ---
# "eh", "ehm", "øh", "mm", "mhm", "hmm" ... (real words like "ah" or "æ" are NOT removed)
FILLER_RE = re.compile(
    r"^(?:e{2,}h*m*|eh+m*|ehm+|em+|øh+m*|ø{2,}h*|æh+m*|æ{2,}h*|m{2,}h*|mh+m*|hm+|uh+m*|um+)$",
    re.I,
)
SENT_END = re.compile(r"[.!?…][\"»”)]*$")


def core(w):
    t = w.text if isinstance(w, Word) else w
    return re.sub(r"\W+", "", t.lower())


# Pieces of the model's own markers, written as text: NB-Whisper puts "<|nocaptions|>" where its training
# subtitles had no text (it came out as "| > < |nocaptions | >" in a subtitle, 2026-10-24).
MARKER_RE = re.compile(r"[<>|]|nocaptions|nospeech", re.I)


def is_marker(text):
    return bool(MARKER_RE.search(text))


def clean_words(words, p):
    out, cap_next = [], False
    for w in words:
        raw = w.text
        w.text = raw.strip()
        if not w.text or is_marker(w.text):
            continue
        # Whisper sometimes glues a comma/period to the NEXT word (",trøndere,") - give it back
        m = re.match(r"^([,.;:!?…]+)(\S.*)$", w.text)
        if m and out and not raw[:1].isspace():
            out[-1].text += m.group(1)
            w.text = m.group(2)
        c = core(w)
        if FILLER_RE.match(c):
            if not out or SENT_END.search(out[-1].text):
                cap_next = True  # filler opened a sentence -> next word gets the capital
            continue
        if p.collapse_repeats and out and c == core(out[-1]) and len(c) <= 4:
            out[-1].end = max(out[-1].end, w.end)  # "jeg jeg" -> "jeg"
            continue
        if cap_next:
            w.text = w.text[0].upper() + w.text[1:]
            cap_next = False
        if out:  # keep timestamps monotonic (Whisper words can overlap slightly)
            w.start = max(w.start, out[-1].start)
        w.end = max(w.end, w.start)
        out.append(w)
    return out


# ----------------------------------------------------------- abbreviations ---
# Subtitles say what the person said: abbreviations are written out in full. Keys: lower case, dots kept.
ABBREV = {
    "f.eks.": "for eksempel", "f.eks": "for eksempel", "feks.": "for eksempel", "feks": "for eksempel",
    "bl.a.": "blant annet", "bl.a": "blant annet", "osv.": "og så videre", "osv": "og så videre",
    "dvs.": "det vil si", "dvs": "det vil si", "ca.": "cirka", "ca": "cirka",
    "mht.": "med hensyn til", "mht": "med hensyn til", "pga.": "på grunn av", "pga": "på grunn av",
    "p.g.a.": "på grunn av", "iht.": "i henhold til", "iht": "i henhold til",
    "ift.": "i forhold til", "ift": "i forhold til", "i.f.t.": "i forhold til", "ifht.": "i forhold til",
    "ifm.": "i forbindelse med", "ifm": "i forbindelse med", "mtp.": "med tanke på", "mtp": "med tanke på",
    "m.m.": "med mer", "o.l.": "og lignende", "m.a.o.": "med andre ord",
    "evt.": "eventuelt", "evt": "eventuelt", "ev.": "eventuelt",
    "etc.": "et cetera", "etc": "et cetera", "inkl.": "inkludert", "inkl": "inkludert",
    "ekskl.": "eksklusive", "hhv.": "henholdsvis", "jf.": "jamfør", "vs.": "versus",
    "ang.": "angående", "vedr.": "vedrørende", "f.o.m.": "fra og med", "t.o.m.": "til og med",
    "nr.": "nummer", "kl.": "klokken", "tlf.": "telefon", "kr.": "kroner", "kr": "kroner",
    "mill.": "millioner", "mrd.": "milliarder",
}
ABBREV_NN = {  # nynorsk spells some of them differently
    "t.d.": "til dømes", "t.d": "til dømes", "m.a.": "mellom anna", "osb.": "og så bortetter",
    "dvs.": "det vil seie", "dvs": "det vil seie", "o.l.": "og liknande", "kl.": "klokka",
    "bl.a.": "mellom anna", "bl.a": "mellom anna",
}
WRAP_RE = re.compile(r'^(["«“(]*)(.*?)([,;:!?…"»”)]*)$')


def expand_abbreviations(words, lang="no"):
    """Write abbreviations out in full ("F.eks." -> "For eksempel"). The full form gets the abbreviation's
    time span, shared between its words by length. The abbreviation's own dot only stays when it ended the
    sentence (last word, or the next word starts with a capital)."""
    table = {**ABBREV, **ABBREV_NN} if lang == "nn" else ABBREV
    out, k = [], 0
    while k < len(words):
        span = 1
        if k + 1 < len(words):  # "f." + "eks." written as two words
            two = WRAP_RE.match(words[k].text.strip() + words[k + 1].text.strip())
            if two and two.group(2).lower() in table:
                span = 2
        m = WRAP_RE.match("".join(x.text.strip() for x in words[k:k + span]))
        full = table.get(m.group(2).lower()) if m else None
        if not full:
            out.append(words[k])
            k += 1
            continue
        group = words[k:k + span]
        nxt = words[k + span] if k + span < len(words) else None
        ended = nxt is None or nxt.text.strip()[:1].isupper()
        dot = "." if m.group(2).endswith(".") and not m.group(3) and ended else ""
        if not out or SENT_END.search(out[-1].text):  # capital only at the start of a sentence
            full = full[0].upper() + full[1:]
        parts = full.split()
        parts[0] = m.group(1) + parts[0]
        parts[-1] += dot + m.group(3)
        t0, t1 = group[0].start, group[-1].end
        total = sum(len(x) for x in parts)
        at = t0
        for x in parts:
            end = at + (t1 - t0) * len(x) / total
            out.append(Word(x, at, end, min(g.prob for g in group)))
            at = end
        k += span
    return out


# ---------------------------------------------------------------- capitals ---
# Everyday words that are never names. The model starts every chunk of speech it hears with a capital, also
# when the sentence goes on ("på et Det begynner", "har Du", new speaker), so mid-sentence these get a small
# letter. Names keep theirs (Stortinget, MDG, Arbeiderpartiet are not in the list).
LOWER_MID = set("""jeg du han hun vi dere de det den denne dette disse dem meg deg seg oss man en et ei
    og men eller at som så da når hvis fordi mens om enn i på til med for av fra over under etter før mot hos ved
    er var har hadde blir ble kan kunne skal skulle vil ville må måtte får fikk gjør gjorde
    ikke også bare nå her der hva hvem hvor hvordan hvorfor hvilken hvilke ja nei altså liksom jo vel nok
    egentlig faktisk eg ho me dei ikkje berre kva korleis kvifor kven""".split())


# The model ends a sentence at every breath, so one sentence comes out as two: "Han liker fotball. Og han går
# på skole." When the next "sentence" starts with a word that only continues the one before, they are joined
# again: with a comma before og/men/eller/så (two main clauses), without one before fordi/at (a subordinate
# clause). "Så" only when a subject follows ("Så vi ble hjemme"): "Så gikk vi hjem" is a sentence of its own.
# "At" only after a verb like "tror" ("Jeg tror. At det går bra"): "At vi kom fram var flaks" can start one.
# Only after a plain full stop (not ? or !) and a short pause; a long pause is a real break or a new speaker.
JOIN_COMMA = set("og men eller så".split())
JOIN_PLAIN = set("fordi at".split())
SUBJECT = set("jeg du han hun vi dere de man det eg ho me dei".split())
SAY_VERBS = set("""tror trodde vet visste sier sa mener mente håper håpet tenker tenkte synes syntes føler
    følte betyr viser klart trur veit seier meiner tykkjer""".split())


def join_sentences(words, p):
    for k, (prev, w) in enumerate(zip(words, words[1:])):
        c = core(w)
        nxt = core(words[k + 2]) if k + 2 < len(words) else ""
        if (c in JOIN_COMMA or c in JOIN_PLAIN) and w.text[:1].isupper() and not w.text[1:2].isupper() \
                and re.search(r"\w\.$", prev.text) and w.start - prev.end < p.hard_pause \
                and (c != "så" or nxt in SUBJECT) and (c != "at" or core(prev) in SAY_VERBS):
            prev.text = prev.text[:-1] + ("," if c in JOIN_COMMA else "")
            w.text = w.text[0].lower() + w.text[1:]
    return words


# Norwegian puts a comma before men, and before og/eller when they join two whole clauses. The model often
# leaves it out ("Han liker fotball og han går på skole"). "men" always gets one; og/eller only when a subject
# and a verb follow (or a verb and a subject: "eller vil du ha te?") and the part before has a verb of its own,
# so "epler og pærer" and "han og jeg kom" do not.
FINITE = set("""er var har hadde blir ble kan kunne skal skulle vil ville må måtte får fikk gjør gjorde går gikk
    kom sier sa tar tok ser så liker likte tror trodde vet visste synes syntes heter het bor bodde fant ga gav
    vart gjer seier tek trur veit likar""".split())


def has_verb(c):
    return c in FINITE or (len(c) >= 4 and c.endswith("er"))


def add_commas(words):
    start = 0  # first word of the current clause
    for k in range(1, len(words)):
        prev, c = words[k - 1], core(words[k])
        if re.search(r"[.!?…,;:–—-][\"»”)]*$", prev.text):
            start = k
            continue
        if c == "men" and k > start:
            prev.text += ","
            start = k
        elif c in ("og", "eller") and k - start >= 2 and k + 2 < len(words) \
                and ((core(words[k + 1]) in SUBJECT and has_verb(core(words[k + 2])))
                     or (core(words[k + 1]) in FINITE and core(words[k + 2]) in SUBJECT)) \
                and any(has_verb(core(x)) for x in words[start:k]):
            prev.text += ","
            start = k
    return words


def fix_capitals(words):
    for prev, w in zip(words, words[1:]):
        if w.text[:1].isupper() and not SENT_END.search(prev.text) and core(w) in LOWER_MID \
                and not w.text[1:2].isupper():  # "VI" in capitals is shouting/an acronym: leave it
            w.text = w.text[0].lower() + w.text[1:]
    return words


# ------------------------------------------------------- break preferences ---
# Words a cue/line should NOT end on (they belong with what follows).
NO_END_STRONG = set("""en ei et den det de i på av til fra med for om ved over under etter før mot hos
    å og eller men at som hvis når hvor fordi mens min mitt mine din ditt dine sin sitt sine vår vårt våre
    deres hans hennes dens dets denne dette disse noen noe alle""".split())
NO_END_MED = set("""jeg du vi dere han hun man ikke også så bare helt veldig litt
    ny nye nytt stor store stort liten lite små mange flere hele hver hvert første andre neste siste samme
    egen egne god gode godt viktig viktige to tre fire fem seks sju syv åtte ni ti hundre tusen""".split())
# Good words to START a new cue/line with (new clause).
GOOD_START = set("og men eller at som fordi hvis når mens så".split())
UNITS = set("prosent kroner kr millioner millioner milliarder tusen år måneder uker dager timer minutter".split())
BALANCE = 0.6         # cost per character of difference between the two lines of a cue
BALANCE_FREE = 4      # differences up to this many characters are free
MID_CLAUSE = 3        # extra cost of starting a new subtitle inside a clause (no punctuation, no pause)
SHORT_CUE = 15        # a subtitle this short that stops mid-clause costs extra
TOP_LONGER = 5.0      # extra cost when the top line is the longer one (the longer line goes at the bottom)
TOP_LONGER_PER = 0.6  # ... plus this per character it is longer


def balance_cost(a, b):
    """Two lines over each other should be about the same length."""
    return max(0, abs(a - b) - BALANCE_FREE) * BALANCE


def top_longer_cost(a, b):
    """When the two lines clearly differ, the longer one should be the bottom line (within BALANCE_FREE they
    count as the same length)."""
    return TOP_LONGER + (a - b - BALANCE_FREE) * TOP_LONGER_PER if a - b > BALANCE_FREE else 0.0


def break_cost(a, b):
    """Cost of ending a cue/line after word a and starting the next with b (lower = better)."""
    ca, cb = core(a), core(b)
    cost = 0.0
    if SENT_END.search(a.text):
        cost -= 8
    elif re.search(r"[,;:–—-]$", a.text):
        cost -= 4
    pause = b.start - a.end
    if pause >= 0.6:
        cost -= 6
    elif pause >= 0.3:
        cost -= 3
    if ca in NO_END_STRONG:
        cost += 10
    elif ca in NO_END_MED:
        cost += 5
    if cb in GOOD_START:
        cost -= 3
    if a.text[:1].isupper() and b.text[:1].isupper() and not re.search(r"[.!?,:;]$", a.text):
        cost += 8  # don't split names ("Våg | Bakeri")
    if ca.isdigit() and not SENT_END.search(a.text):
        cost += 8 if cb in UNITS else 4  # keep numbers with what they count
    return cost


# -------------------------------------------------------------- cue search ---
def over(lines, p):
    """Characters over max_chars, summed over the lines (each line may go up to char_slack over)."""
    return sum(max(0, len(l) - p.max_chars) for l in lines)


def split_lines(sub, p):
    text = " ".join(w.text for w in sub)
    if len(text) <= p.max_chars:
        return [text], 0.0
    limit = p.max_chars + p.char_slack
    best = None
    for k in range(1, len(sub)):
        l1 = " ".join(w.text for w in sub[:k])
        l2 = " ".join(w.text for w in sub[k:])
        if len(l1) > limit or len(l2) > limit:
            continue
        c = (break_cost(sub[k - 1], sub[k]) + balance_cost(len(l1), len(l2)) + top_longer_cost(len(l1), len(l2))
             + over([l1, l2], p) * 5)
        if SENT_END.search(sub[k].text) and not SENT_END.search(sub[k - 1].text):
            c += 10  # a sentence's last word alone at the start of line 2 ("... regionene / våre. Spesielt ...")
        if k >= 2 and SENT_END.search(sub[k - 2].text):
            c += 6   # a new sentence's first word alone at the end of line 1
        # Priorities for the two lines: keep phrases together, then the longer line at the bottom, then even
        # lengths. A line ending on "dette", "med", "og" or on "den nye" (before its noun) costs more than both.
        if not re.search(r"[.!?,;:]$", sub[k - 1].text):
            if core(sub[k - 1]) in NO_END_STRONG:
                c += 30
            elif core(sub[k - 1]) in NO_END_MED:
                c += 25
        if best is None or c < best[1]:
            best = ([l1, l2], c)
    return best  # None if it cannot fit in two lines


def orphan_cost(words, i, j):
    """Cost of cue words[i:j] cutting a sentence so that a word or two are left on their own."""
    sub, cost = words[i:j], 0.0
    # The last word or two of a sentence pushed into this cue, cut off from the rest of their sentence
    # ("... vi skal | gjøre. Neste ..."): worth a few characters over the limit to avoid.
    if i > 0 and not SENT_END.search(words[i - 1].text):
        k = next((n for n, w in enumerate(sub) if SENT_END.search(w.text)), None)
        if k == 0:
            cost += 10
        elif k == 1:
            cost += 4
    # ... and the first word of a new sentence left alone at the end of this cue.
    if j < len(words) and len(sub) >= 2 and SENT_END.search(sub[-2].text):
        cost += 6
    return cost


def cue_cost(words, i, j, p):
    sub = words[i:j]
    if len(sub) == 1:  # always allowed, whatever its length/duration
        return 6.0 + 12 + orphan_cost(words, i, j), [sub[0].text]
    span = sub[-1].end - sub[0].start
    if span > p.max_dur:
        return None
    if any(b.start - a.end > p.hard_pause for a, b in zip(sub, sub[1:])):
        return None
    sp = split_lines(sub, p)
    if sp is None:
        return None
    lines, lc = sp
    chars = sum(len(l) for l in lines)
    # Reading speed over the time the subtitle can really stay up: time_cues() keeps it on screen into the
    # silence after the last word (until just before the next subtitle) when the text needs it.
    room = (words[j].start - p.gap if j < len(words) else sub[-1].end + p.max_dur) - (sub[0].start - p.lead)
    shown = max(span + p.tail, min(room, chars / p.max_cps, p.max_dur))
    cps = chars / max(shown, p.min_dur)
    cost = 12 + 0.5 * lc + (3 if len(lines) == 2 else 0)
    if cps > p.max_cps:
        cost += (cps - p.max_cps) * 6
    if chars < 8:
        cost += 6  # avoid orphan cues
    if span > 5.0:
        cost += (span - 5.0) * 3  # prefer splitting at a natural pause over a very long cue
    cost += over(lines, p) * 2.5  # a little over max_chars is fine, but only when it buys something
    cost += orphan_cost(words, i, j)
    if j < len(words):
        cost += break_cost(words[j - 1], words[j])
        a, b = words[j - 1], words[j]
        if not re.search(r"[.!?…,;:–—-][\"»”)]*$", a.text) and b.start - a.end < 0.3:
            cost += MID_CLAUSE  # a new subtitle mid-clause, with no comma or pause: only when it must
            if chars <= SHORT_CUE:
                cost += 6  # ... and a short scrap of a clause on its own ("I dag skal || vi snakke om ...")
    return cost, lines


def build_cues(words, p):
    n = len(words)
    INF = 1e18
    pre = [0]
    for w in words:
        pre.append(pre[-1] + len(w.text))
    best, prev = [INF] * (n + 1), [-1] * (n + 1)
    lines_at = [None] * (n + 1)
    best[0] = 0.0
    for i in range(n):
        if best[i] >= INF:
            continue
        for j in range(i + 1, n + 1):
            if pre[j] - pre[i] + (j - i - 1) > 2 * (p.max_chars + p.char_slack) and j - i > 1:
                break
            r = cue_cost(words, i, j, p)
            if r is None:
                continue
            c, lines = r
            if best[i] + c < best[j]:
                best[j], prev[j], lines_at[j] = best[i] + c, i, lines
    cues, j = [], n
    while j > 0:
        i = prev[j]
        cues.append({"i": i, "j": j, "lines": lines_at[j]})
        j = i
    cues.reverse()
    return cues



def time_cues(cues, words, p):
    for c in cues:
        ws = words[c["i"]:c["j"]]
        c["start"] = max(0.0, ws[0].start - p.lead)
        c["end"] = ws[-1].end + p.tail
        c["chars"] = sum(len(l) for l in c["lines"])
    for k, c in enumerate(cues):
        nxt = cues[k + 1]["start"] - p.gap if k + 1 < len(cues) else float("inf")
        limit = min(nxt, c["start"] + p.max_dur)
        end = min(c["end"], limit)
        if end - c["start"] < p.min_dur:
            end = min(c["start"] + p.min_dur, limit)
        need = c["chars"] / p.max_cps  # extend into silence if reading speed is too high
        if end - c["start"] < need:
            end = min(c["start"] + need, limit)
        c["end"] = max(end, c["start"] + 0.2)
    return cues


# --------------------------------------------------------------------- API ---
def params(rules=None, **extra):
    """Build P from a settings dict, ignoring unknown keys."""
    names = {f.name for f in fields(P)}
    kw = {k: v for k, v in {**(rules or {}), **extra}.items() if k in names}
    return P(**kw)


def make_cues(raw_words, p):
    """raw_words: [{"w","s","e","p"}] -> [{"start","end","text"}] (text lines joined by \\n)."""
    words = clean_words([Word(w["w"], w["s"], w["e"], w.get("p", 1.0)) for w in raw_words], p)
    words = add_commas(fix_capitals(join_sentences(expand_abbreviations(words, p.lang), p)))
    if not words:
        return []
    cues = time_cues(build_cues(words, p), words, p)
    return [{"start": round(c["start"], 3), "end": round(c["end"], 3), "text": "\n".join(c["lines"])}
            for c in cues]


def wrap_text(text, p):
    """Re-break one cue's text into at most two balanced lines (same rules as the segmenter)."""
    toks = text.split()
    if not toks:
        return ""
    ws = [Word(t, 0.0, 0.0) for t in toks]
    sp = split_lines(ws, p)
    return "\n".join(sp[0]) if sp else " ".join(toks)


def ts(t):
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def to_srt(cues):
    out = []
    n = 0
    for c in sorted(cues, key=lambda c: c["start"]):
        text = "\n".join(l.strip() for l in c["text"].splitlines() if l.strip())
        if not text:
            continue
        n += 1
        out.append(f"{n}\n{ts(c['start'])} --> {ts(c['end'])}\n{text}\n")
    return "\n".join(out)
