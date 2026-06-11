"""
AI Autocorrect Pro — Backend v3.0
Senior NLP Engineer Edition

Architecture:
  Primary:  Claude API  (full NLP, called from Flask → Anthropic proxy)
  Fallback: Multi-stage rule pipeline (no external deps)
             Stage 1 — Spelling
             Stage 2 — Morphology  (tense, S-V agreement, verb form, plurals)
             Stage 3 — Articles & prepositions
             Stage 4 — Discourse   (connectors, clause commas)
             Stage 5 — Proper nouns & capitalization
             Stage 6 — Sentence-start capitalization
             Stage 7 — Whitespace normalisation
"""

from __future__ import annotations
from flask import Flask, render_template, request, jsonify
import re, json, requests, math
from typing import Any

app = Flask(__name__)
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# ═══════════════════════════════════════════════════════════════
#  CLAUDE API — PRIMARY CORRECTION ENGINE
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a senior NLP engineer and expert English grammar corrector, equivalent to Grammarly Premium.

You must fix ALL of the following in the given text:
1. SPELLING — every misspelling (inteligence→intelligence, studing→studying, passionated→passionate, developement→development)
2. TENSE — detect past-time markers (yesterday, last week, ago) and fix verb tense (go→went, meet→met, tell→told)
3. SUBJECT-VERB AGREEMENT — (he have→he has, he go→he goes, they is→they are, AI are→AI is)
4. VERB FORM — (dont likes→doesn't like, wants go→wants to go, can able→can)
5. IRREGULAR PLURALS — (childrens→children, homeworks→homework [uncountable], informations→information, advices→advice)
6. ARTICLES — insert/fix a/an/the (go to park→go to the park, future of technology→the future of technology)
7. PREPOSITIONS — (studying in university→studying at university, good in English→good at English)
8. CAPITALIZATION — every sentence start, pronoun I, proper nouns, university names, AI/ML terms
9. PUNCTUATION — apostrophes (dont→don't), salutation commas, clause commas before 'and/but', sentence periods
10. DISCOURSE — replace informal connectors (but [after complete sentence]→However,)
11. NATURAL REWRITING — rewrite awkward phrases into fluent English without changing meaning

CRITICAL RULES:
- "homeworks" → "a lot of homework" (homework is uncountable)
- "childrens" → "children" (irregular plural, no -s)
- "dont likes" → "doesn't like" (third-person: do→does, drop -s from verb)
- Past-time words (yesterday, last week, ago, earlier) force past tense on nearby verbs
- Singular third-person subjects (he/she/it/name) → verb gets -s (he go→he goes) UNLESS already past tense
- "AI/Artificial Intelligence" is singular → "is", not "are"
- Never change the speaker's meaning; only improve correctness"""


def build_prompt(text: str) -> str:
    return f"""Correct this English text completely. Apply every grammar rule.

INPUT TEXT:
{text}

Return ONLY a valid JSON object. No markdown. No explanation. Just JSON.

{{
  "corrected": "<fully corrected text, natural English>",
  "grammar_score": <score 0-100 for ORIGINAL text grammar>,
  "spelling_score": <score 0-100 for ORIGINAL text spelling>,
  "readability_score": <score 0-100 for ORIGINAL text readability>,
  "overall_score": <round(grammar*0.40 + spelling*0.35 + readability*0.25)>,
  "mistakes": <total integer count of all corrections>,
  "confidence": <your confidence in corrections 0-100>,
  "explanations": [
    {{
      "before": "<exact original phrase>",
      "after": "<corrected phrase>",
      "type": "<Spelling|Grammar|Tense|Punctuation|Capitalization|Article|Preposition|Plural>",
      "reason": "<specific grammatical explanation>"
    }}
  ],
  "stats": {{
    "words": <word count of corrected>,
    "sentences": <sentence count>,
    "characters": <char count>,
    "reading_time_sec": <ceil(words/3.33)>,
    "grammar_fixed": <int>,
    "spelling_fixed": <int>
  }}
}}"""


def correct_with_claude(text: str) -> dict | None:
    """Call Claude. Returns parsed result dict or None."""
    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2000,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": build_prompt(text)}]
            },
            timeout=40
        )
        if resp.status_code != 200:
            print(f"[Claude] HTTP {resp.status_code}")
            return None
        raw = resp.json()["content"][0]["text"].strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[Claude] {e}")
        return None


def build_response(original: str, r: dict) -> dict:
    corrected = r.get("corrected", original)
    words     = len(corrected.split())
    sents     = max(1, len(re.findall(r"[.!?]+", corrected)))
    stats     = r.get("stats") or {}
    stats.setdefault("words",            words)
    stats.setdefault("sentences",        sents)
    stats.setdefault("characters",       len(corrected))
    stats.setdefault("reading_time_sec", max(1, math.ceil(words / 3.33)))
    stats.setdefault("grammar_fixed",    0)
    stats.setdefault("spelling_fixed",   0)
    overall = int(r.get("overall_score") or r.get("score") or 85)
    return {
        "original":          original,
        "corrected":         corrected,
        "score":             overall,
        "grammar_score":     int(r.get("grammar_score")     or overall),
        "spelling_score":    int(r.get("spelling_score")    or overall),
        "readability_score": int(r.get("readability_score") or overall),
        "overall_score":     overall,
        "mistakes":          int(r.get("mistakes") or 0),
        "confidence":        int(r.get("confidence") or 90),
        "changes":           r.get("changes")      or [],
        "explanations":      r.get("explanations") or [],
        "stats":             stats,
    }


# ═══════════════════════════════════════════════════════════════
#  FALLBACK ENGINE — MULTI-STAGE NLP PIPELINE
# ═══════════════════════════════════════════════════════════════

# ── Morphological tables ───────────────────────────────────────

# Irregular verb: base → past
IRREGULAR_PAST: dict[str, str] = {
    "go": "went", "went": "went", "meet": "met", "tell": "told",
    "say": "said", "see": "saw", "come": "came", "take": "took",
    "make": "made", "give": "gave", "get": "got", "know": "knew",
    "think": "thought", "find": "found", "leave": "left", "feel": "felt",
    "put": "put", "keep": "kept", "let": "let", "begin": "began",
    "show": "showed", "hear": "heard", "play": "played", "run": "ran",
    "write": "wrote", "buy": "bought", "bring": "brought", "read": "read",
    "spend": "spent", "grow": "grew", "lose": "lost", "hold": "held",
    "stand": "stood", "send": "sent", "build": "built", "fall": "fell",
    "speak": "spoke", "eat": "ate", "drink": "drank", "sleep": "slept",
    "sit": "sat", "set": "set", "cut": "cut", "win": "won",
    "break": "broke", "become": "became", "drive": "drove", "rise": "rose",
    "throw": "threw", "catch": "caught", "teach": "taught", "sell": "sold",
    "pay": "paid", "lead": "led", "understand": "understood", "choose": "chose",
    "ride": "rode", "draw": "drew", "wear": "wore", "fly": "flew",
    "swim": "swam", "sing": "sang", "ring": "rang", "hang": "hung",
    "strike": "struck", "swear": "swore", "wake": "woke", "bite": "bit",
    "hide": "hid", "steal": "stole", "shake": "shook", "forget": "forgot",
    "forgive": "forgave", "undertake": "undertook", "mistake": "mistook",
    # Regular also included for completeness
    "study": "studied", "complete": "completed", "start": "started",
    "finish": "finished", "help": "helped", "work": "worked",
    "talk": "talked", "walk": "walked", "call": "called", "ask": "asked",
    "want": "wanted", "need": "needed", "use": "used", "try": "tried",
    "like": "liked", "love": "loved", "live": "lived", "die": "died",
    "stop": "stopped", "drop": "dropped", "plan": "planned", "refer": "referred",
}

# Verb base → 3rd-person singular present (-s form)
THIRD_PERSON_S: dict[str, str] = {
    "go": "goes", "do": "does", "have": "has", "be": "is",
    "say": "says", "try": "tries", "study": "studies", "carry": "carries",
    "fly": "flies", "deny": "denies", "rely": "relies", "cry": "cries",
    "buy": "buys", "pay": "pays", "play": "plays", "stay": "stays",
    "enjoy": "enjoys", "destroy": "destroys",
}

def to_3sg(verb: str) -> str:
    """Return 3rd-person singular present of verb."""
    v = verb.lower()
    if v in THIRD_PERSON_S:
        return THIRD_PERSON_S[v]
    if v.endswith(('s', 'sh', 'ch', 'x', 'z', 'o')):
        return v + "es"
    if v.endswith('y') and len(v) > 1 and v[-2] not in 'aeiou':
        return v[:-1] + "ies"
    return v + "s"

def to_past(verb: str) -> str:
    """Return simple past of verb."""
    v = verb.lower()
    if v in IRREGULAR_PAST:
        return IRREGULAR_PAST[v]
    # Regular
    if v.endswith('e'):
        return v + "d"
    if v.endswith('y') and len(v) > 1 and v[-2] not in 'aeiou':
        return v[:-1] + "ied"
    # CVC doubling (1-syllable, ends consonant-vowel-consonant)
    if (len(v) >= 3 and v[-1] not in 'aeiou' and v[-2] in 'aeiou'
            and v[-3] not in 'aeiou' and v[-1] not in 'wxyz'):
        return v + v[-1] + "ed"
    return v + "ed"

# Uncountable nouns (no plural form)
UNCOUNTABLE: set[str] = {
    "homework", "information", "advice", "knowledge", "equipment",
    "furniture", "luggage", "traffic", "weather", "research",
    "news", "money", "water", "food", "music", "love", "happiness",
    "evidence", "progress", "software", "hardware", "data",
    "feedback", "staff", "work", "accommodation", "electricity",
}

# Irregular plurals: wrong form → correct form
IRREGULAR_PLURALS: dict[str, str] = {
    "childrens":   "children",
    "mens":        "men",
    "womens":      "women",
    "mouses":      "mice",
    "gooses":      "geese",
    "foots":       "feet",
    "tooths":      "teeth",
    "oxes":        "oxen",
    "peoples":     "people",    # context-dependent but usually wrong
    "sheeps":      "sheep",
    "deers":       "deer",
    "fishs":       "fish",
    "aircrafts":   "aircraft",
    "polices":     "police",
    "knifes":      "knives",
    "leafs":       "leaves",
    "wolfs":       "wolves",
    "halfs":       "halves",
    "lifes":       "lives",
    "wifes":       "wives",
    "loafs":       "loaves",
    "thefs":       "thieves",
    "crisises":    "crises",
    "analysises":  "analyses",
    "basises":     "bases",
    "criterions":  "criteria",
    "phenomenons": "phenomena",
}

# Uncountable: plural form → fix
UNCOUNTABLE_PLURALS: dict[str, tuple[str, str]] = {
    # wrong_form: (replacement, article_prefix)
    "homeworks":    ("homework",    "a lot of"),
    "informations": ("information", ""),
    "advices":      ("advice",      ""),
    "knowledges":   ("knowledge",   ""),
    "equipments":   ("equipment",   ""),
    "furnitures":   ("furniture",   ""),
    "luggages":     ("luggage",     ""),
    "researchs":    ("research",    ""),
    "softwares":    ("software",    ""),
    "hardwares":    ("hardware",    ""),
    "feedbacks":    ("feedback",    ""),
    "evidences":    ("evidence",    ""),
}

# Past-time adverbs that force past tense in the same clause
PAST_MARKERS: set[str] = {
    "yesterday", "ago", "last", "earlier", "previously",
    "formerly", "once", "back", "then", "lately", "recently",
    "afterward", "afterwards", "before",
}

# Verbs that should NOT be forced to past (auxiliaries, modals)
MODAL_VERBS: set[str] = {
    "will", "would", "can", "could", "shall", "should",
    "may", "might", "must", "need", "dare", "ought",
    "am", "is", "are", "was", "were", "been", "be",
    "have", "has", "had", "do", "does", "did",
}

# Spelling dictionary
SPELLING_DICT: dict[str, str] = {
    "studing":        "studying",
    "inteligence":    "intelligence",
    "intelligance":   "intelligence",
    "passionated":    "passionate",
    "developement":   "development",
    "learnig":        "learning",
    "mashine":        "machine",
    "recieve":        "receive",
    "belive":         "believe",
    "occured":        "occurred",
    "seperate":       "separate",
    "neccesary":      "necessary",
    "experiance":     "experience",
    "knowlege":       "knowledge",
    "acheive":        "achieve",
    "immediatly":     "immediately",
    "programing":     "programming",
    "algortihm":      "algorithm",
    "algorithem":     "algorithm",
    "implimentation": "implementation",
    "perseverence":   "perseverance",
    "intergration":   "integration",
    "frendly":        "friendly",
    "responsibilty":  "responsibility",
    "definately":     "definitely",
    "grammer":        "grammar",
    "occassion":      "occasion",
    "commited":       "committed",
    "sucessful":      "successful",
    "enviroment":     "environment",
    "goverment":      "government",
    "libary":         "library",
    "febuary":        "february",
    "calender":       "calendar",
    "neice":          "niece",
    "wierd":          "weird",
    "untill":         "until",
    "allmost":        "almost",
    "thier":          "their",
    "reccomend":      "recommend",
    "embarass":       "embarrass",
    "existance":      "existence",
    "persistance":    "persistence",
    "pronounciation": "pronunciation",
    "priviledge":     "privilege",
    "independant":    "independent",
    "plagarism":      "plagiarism",
    "accomodate":     "accommodate",
    "beleive":        "believe",
    "mispell":        "misspell",
    "questionaire":   "questionnaire",
    "suprise":        "surprise",
    "tendancy":       "tendency",
    "abscence":       "absence",
    "accidently":     "accidentally",
    "arguement":      "argument",
    "comparision":    "comparison",
    "concious":       "conscious",
    "curiousity":     "curiosity",
}

# Proper nouns: lowercase pattern → correct form
PROPER_NOUNS: dict[str, str] = {
    "soa university":             "SOA University",
    "iit":                        "IIT",
    "nit":                        "NIT",
    "mit":                        "MIT",
    "harvard university":         "Harvard University",
    "oxford university":          "Oxford University",
    "artificial intelligence":    "Artificial Intelligence",
    "machine learning":           "Machine Learning",
    "deep learning":              "Deep Learning",
    "data science":               "Data Science",
    "computer science":           "Computer Science",
    "natural language processing":"Natural Language Processing",
    "internet of things":         "Internet of Things",
    "cloud computing":            "Cloud Computing",
    "web development":            "Web Development",
    "software engineering":       "Software Engineering",
    "cyber security":             "Cyber Security",
}

# Institutions after which "in" → "at"
INSTITUTION_KEYWORDS = re.compile(
    r"\b(university|college|institute|school|academy|iit|nit|mit)\b",
    re.IGNORECASE
)


# ── Pipeline utilities ─────────────────────────────────────────

class Correction:
    """Tracks a single correction with explanation."""
    __slots__ = ("before", "after", "ctype", "reason")

    def __init__(self, before: str, after: str, ctype: str, reason: str):
        self.before = before
        self.after  = after
        self.ctype  = ctype
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "before": self.before,
            "after":  self.after,
            "type":   self.ctype,
            "reason": self.reason,
        }


class Pipeline:
    """Mutable text + accumulated corrections."""

    def __init__(self, text: str):
        self.text         = text
        self.corrections: list[Correction] = []
        self.sp_fixed     = 0
        self.gr_fixed     = 0

    # ── low-level helpers ──────────────────────────────────────

    def sub(self,
            pattern: str,
            replacement: str,
            ctype: str,
            reason: str,
            flags: int = re.IGNORECASE,
            preserve_case: bool = False) -> None:
        """
        Apply regex substitution and record corrections.
        preserve_case: if True, match first char's case → replacement first char.
        """
        matches = list(re.finditer(pattern, self.text, flags))
        if not matches:
            return

        def replacer(m: re.Match) -> str:
            orig = m.group(0)
            new  = re.sub(pattern, replacement, orig, flags=flags)
            if preserve_case and orig and new:
                if orig[0].isupper() and new[0].islower():
                    new = new[0].upper() + new[1:]
                elif orig[0].islower() and new[0].isupper():
                    new = new[0].lower() + new[1:]
            return new

        new_text = re.sub(pattern, replacer, self.text, flags=flags)
        if new_text == self.text:
            return

        # Record explanation from first match
        m0 = matches[0]
        before = m0.group(0)
        after  = re.sub(pattern, replacement, before, flags=flags)
        if before.strip().lower() != after.strip().lower():
            self.corrections.append(Correction(before, after, ctype, reason))
            if ctype == "Spelling":
                self.sp_fixed += 1
            else:
                self.gr_fixed += 1
        self.text = new_text

    def replace_word(self,
                     wrong: str,
                     right: str,
                     ctype: str,
                     reason: str,
                     preserve_case: bool = True) -> None:
        """Whole-word substitution (IGNORECASE, case-preserved)."""
        pattern     = rf"\b{re.escape(wrong)}\b"
        replacement = right

        def replacer(m: re.Match) -> str:
            orig = m.group(0)
            if preserve_case and orig[0].isupper() and right[0].islower():
                return right[0].upper() + right[1:]
            return right

        matches = list(re.finditer(pattern, self.text, re.IGNORECASE))
        if not matches:
            return
        new_text = re.sub(pattern, replacer, self.text, flags=re.IGNORECASE)
        if new_text == self.text:
            return
        self.corrections.append(Correction(wrong, right, ctype, reason))
        if ctype == "Spelling":
            self.sp_fixed += 1
        else:
            self.gr_fixed += 1
        self.text = new_text


# ═══════════════════════════════════════════════════════════════
#  STAGE 1 — SPELLING
# ═══════════════════════════════════════════════════════════════

def stage_spelling(p: Pipeline) -> None:
    for wrong, right in SPELLING_DICT.items():
        p.replace_word(wrong, right, "Spelling", f"'{wrong}' is misspelled; correct spelling is '{right}'")


# ═══════════════════════════════════════════════════════════════
#  STAGE 2 — MORPHOLOGY
#  2a: uncountable/irregular plurals
#  2b: apostrophe contractions
#  2c: don't + verb-s → doesn't + verb-base
#  2d: past-tense forcing (past-time adverbs)
#  2e: subject-verb agreement (present tense)
# ═══════════════════════════════════════════════════════════════

def stage_morphology(p: Pipeline) -> None:

    # ── 2a: Uncountable noun plurals ──────────────────────────
    for wrong, (right, prefix) in UNCOUNTABLE_PLURALS.items():
        pattern = rf"\b{re.escape(wrong)}\b"
        if re.search(pattern, p.text, re.IGNORECASE):
            # Check what precedes: "many homeworks" → "a lot of homework"
            full_pattern = rf"\b(many|several|some|a few|lots of|a lot of)\s+{re.escape(wrong)}\b"
            m = re.search(full_pattern, p.text, re.IGNORECASE)
            if m:
                replacement = f"{prefix} {right}".strip() if prefix else right
                p.corrections.append(Correction(m.group(0), replacement, "Grammar",
                    f"'{wrong}' is uncountable; cannot use '{m.group(1)} {wrong}'"))
                p.text = p.text[:m.start()] + replacement + p.text[m.end():]
                p.gr_fixed += 1
            else:
                # Just fix the word itself
                p.replace_word(wrong, right, "Grammar",
                    f"'{wrong}' is an uncountable noun; no plural form exists")

    # ── 2a: Irregular plurals ─────────────────────────────────
    for wrong, right in IRREGULAR_PLURALS.items():
        p.replace_word(wrong, right, "Grammar",
            f"'{wrong}' is incorrect; the correct plural/form is '{right}'")

    # ── 2b: Missing apostrophes in contractions ───────────────
    CONTRACTIONS = [
        (r"(?<![a-zA-Z'])dont(?![a-zA-Z])",    "don't",    "Punctuation", "Missing apostrophe in contraction 'don't'"),
        (r"(?<![a-zA-Z'])doesnt(?![a-zA-Z])",  "doesn't",  "Punctuation", "Missing apostrophe in 'doesn't'"),
        (r"(?<![a-zA-Z'])didnt(?![a-zA-Z])",   "didn't",   "Punctuation", "Missing apostrophe in 'didn't'"),
        (r"(?<![a-zA-Z'])wont(?![a-zA-Z])",    "won't",    "Punctuation", "Missing apostrophe in 'won't'"),
        (r"(?<![a-zA-Z'])cant(?![a-zA-Z])",    "can't",    "Punctuation", "Missing apostrophe in 'can't'"),
        (r"(?<![a-zA-Z'])isnt(?![a-zA-Z])",    "isn't",    "Punctuation", "Missing apostrophe in 'isn't'"),
        (r"(?<![a-zA-Z'])arent(?![a-zA-Z])",   "aren't",   "Punctuation", "Missing apostrophe in 'aren't'"),
        (r"(?<![a-zA-Z'])wasnt(?![a-zA-Z])",   "wasn't",   "Punctuation", "Missing apostrophe in 'wasn't'"),
        (r"(?<![a-zA-Z'])hasnt(?![a-zA-Z])",   "hasn't",   "Punctuation", "Missing apostrophe in 'hasn't'"),
        (r"(?<![a-zA-Z'])havent(?![a-zA-Z])",  "haven't",  "Punctuation", "Missing apostrophe in 'haven't'"),
        (r"(?<![a-zA-Z'])hadnt(?![a-zA-Z])",   "hadn't",   "Punctuation", "Missing apostrophe in 'hadn't'"),
        (r"(?<![a-zA-Z'])wouldnt(?![a-zA-Z])", "wouldn't", "Punctuation", "Missing apostrophe in 'wouldn't'"),
        (r"(?<![a-zA-Z'])couldnt(?![a-zA-Z])", "couldn't", "Punctuation", "Missing apostrophe in 'couldn't'"),
        (r"(?<![a-zA-Z'])shouldnt(?![a-zA-Z])","shouldn't","Punctuation", "Missing apostrophe in 'shouldn't'"),
        (r"(?<![a-zA-Z'])ive(?![a-zA-Z'])",    "I've",     "Punctuation", "Missing apostrophe in 'I've'"),
        (r"(?<![a-zA-Z'])im(?![a-zA-Z'])",     "I'm",      "Punctuation", "Missing apostrophe in 'I'm'"),
        (r"(?<![a-zA-Z'])its(?![a-zA-Z's])\s+(?=\w)", "it's ", "Punctuation", "Possessive 'its' vs contraction 'it's'"),
    ]
    for pat, rep, ctype, reason in CONTRACTIONS:
        p.sub(pat, rep, ctype, reason, flags=re.IGNORECASE)

    # ── 2c: "don't/doesn't likes" → "doesn't like" ───────────
    # Pattern: (don't|doesn't) + verb-with-s
    def fix_double_negation(m: re.Match) -> str:
        """Convert 'don't likes' → \"doesn't like\" etc."""
        aux   = m.group(1)    # don't / doesn't / does not
        space = m.group(2)
        verb  = m.group(3)    # likes / goes / plays
        # Strip the -s/-es to get base form
        base = strip_3sg(verb)
        # Determine correct auxiliary based on context (look backwards)
        # We'll default to doesn't (3sg) since these patterns are friend/he/she
        return "doesn't" + space + base

    # "don't likes" or "doesn't likes"
    p.text = re.sub(
        r"\b(don't|doesn't|do not|does not)\s+(\b)([a-z]+(?:s|es))\b",
        lambda m: (
            "doesn't " + strip_3sg(m.group(3))
            if m.group(3).lower() not in MODAL_VERBS
            else m.group(0)
        ),
        p.text, flags=re.IGNORECASE
    )

    # Also fix plain "dont likes" (after apostrophe pass, "dont" → "don't")
    # Now handle subject + don't + verb-s:
    # "my friend doesn't likes" → "my friend doesn't like"
    def fix_doesnt_verb_s(m: re.Match) -> str:
        neg  = m.group(1)   # "doesn't" or "don't"
        sp   = m.group(2)
        verb = m.group(3)   # "likes"
        subj_ctx = p.text[:m.start()].strip().lower()
        # Decide auxiliary: if subject is clearly 3sg, use "doesn't"
        base = strip_3sg(verb)
        aux  = "doesn't" if is_3sg_context(subj_ctx) else "don't"
        if neg.lower() in ("don't", "dont") and is_3sg_context(subj_ctx):
            p.corrections.append(Correction(
                m.group(0), aux + sp + base,
                "Grammar",
                f"Third-person singular subject requires 'doesn't', not 'don't'; verb stays in base form"
            ))
            p.gr_fixed += 1
            return aux + sp + base
        if verb.lower() != base.lower():
            p.corrections.append(Correction(
                m.group(0), neg + sp + base,
                "Grammar",
                f"After '{neg}' the verb must be in base form, not '{verb}'"
            ))
            p.gr_fixed += 1
            return neg + sp + base
        return m.group(0)

    p.text = re.sub(
        r"\b(doesn't|don't)\s+()([a-z]+(?:s|es))\b",
        fix_doesnt_verb_s,
        p.text, flags=re.IGNORECASE
    )

    # ── 2d: Past-tense forcing ────────────────────────────────
    # Detect sentences containing past-time markers; fix verbs to past.
    _force_past_tense(p)

    # ── 2e: Subject-verb agreement (present tense) ────────────
    _fix_sv_agreement(p)


def strip_3sg(verb: str) -> str:
    """Remove -s/-es from 3sg present to get base form.
    likes->like, goes->go, studies->study, watches->watch
    """
    v = verb.lower()
    if v.endswith("ies") and len(v) > 3:   # studies->study
        return v[:-3] + "y"
    if v.endswith("oes"):                   # goes->go, does->do
        return v[:-2]
    if v.endswith(("sses","shes","ches","xes","zes")):  # watches->watch
        return v[:-2]
    if v.endswith("s") and not v.endswith("ss"):        # likes->like, plays->play
        return v[:-1]
    return v


def is_3sg_context(preceding_text: str) -> bool:
    """Heuristic: does the nearest subject look 3rd-person singular?"""
    # Look for he/she/it/name right before the verb
    m = re.search(
        r"\b(he|she|it|my friend|his friend|her friend|the (?:student|teacher|professor|man|woman|boy|girl|child|person|doctor|engineer))\s*$",
        preceding_text, re.IGNORECASE
    )
    return bool(m)


def _force_past_tense(p: Pipeline) -> None:
    """
    Split text into sentences; for each sentence containing a past-time
    marker, convert main verbs to past tense.
    """
    # Split into sentences (keep delimiters)
    sentence_pat = re.compile(r"([^.!?]+[.!?]*)")
    sentences = sentence_pat.findall(p.text)
    if not sentences:
        sentences = [p.text]

    result_parts: list[str] = []

    for sent in sentences:
        words_lower = sent.lower().split()
        has_past_marker = any(w in PAST_MARKERS for w in words_lower)

        if not has_past_marker:
            result_parts.append(sent)
            continue

        # Apply past tense to bare verbs that are NOT already past/modal/aux
        def replace_verb(m: re.Match) -> str:
            word = m.group(0)
            wl   = word.lower()
            if wl in MODAL_VERBS:
                return word
            # Skip if already past (in IRREGULAR_PAST values or ends -ed)
            if wl in IRREGULAR_PAST.values() or wl.endswith("ed"):
                return word
            if wl in IRREGULAR_PAST:
                past = IRREGULAR_PAST[wl]
                if past != wl:
                    p.corrections.append(Correction(
                        word, past,
                        "Tense",
                        f"Past-time context requires past tense: '{wl}' → '{past}'"
                    ))
                    p.gr_fixed += 1
                    # Preserve capitalisation
                    return past.capitalize() if word[0].isupper() else past
            # Check if it's a 3sg form and context has past marker
            base = strip_3sg(wl)
            if base in IRREGULAR_PAST:
                past = IRREGULAR_PAST[base]
                if past != wl:
                    p.corrections.append(Correction(
                        word, past,
                        "Tense",
                        f"Past-time context: '{word}' should be past tense '{past}'"
                    ))
                    p.gr_fixed += 1
                    return past.capitalize() if word[0].isupper() else past
            return word

        # Apply to words in the sentence that look like bare present verbs
        # We target: pronoun/noun + bare_verb patterns
        # Use a targeted approach: find subject + verb patterns
        sent_new = re.sub(
            r"(?<!\w)(go|meet|tell|say|see|come|take|make|give|get|know|think|find|"
            r"leave|feel|show|hear|run|write|buy|bring|read|spend|grow|lose|hold|"
            r"stand|send|fall|speak|eat|drink|sit|win|break|become|drive|rise|"
            r"throw|catch|teach|sell|pay|lead|understand|choose|ride|draw|wear|"
            r"fly|swim|sing|ring|strike|wake|bite|steal|shake|forget|"
            r"goes|meets|tells|says|sees|comes|takes|makes|gives|gets|knows|thinks|"
            r"finds|leaves|feels|shows|hears|runs|writes|buys|brings|reads|spends|"
            r"grows|loses|holds|stands|sends|falls|speaks|eats|drinks|sits|wins|"
            r"breaks|becomes|drives|rises|throws|catches|teaches|sells|pays|leads|"
            r"understands|chooses|rides|draws|wears|flies|swims|sings|rings|strikes|"
            r"wakes|bites|steals|shakes|forgets)(?!\w)",
            replace_verb,
            sent,
            flags=re.IGNORECASE
        )
        result_parts.append(sent_new)

    p.text = "".join(result_parts)


def _fix_sv_agreement(p: Pipeline) -> None:
    """Fix subject-verb agreement for present tense."""

    # he/she/it/singular-noun + base verb → 3sg form
    SV_PATTERNS = [
        # he have → he has
        (r"\b(he|she|it)\s+(have)\b",   lambda m: m.group(1) + " has",
         "Subject-verb agreement", "Third-person singular 'he/she/it' requires 'has', not 'have'"),
        # he do → he does
        (r"\b(he|she|it)\s+(do)\b",     lambda m: m.group(1) + " does",
         "Subject-verb agreement", "Third-person singular requires 'does'"),
        # he go → he goes (only if NOT already caught by past-tense stage)
        (r"\b(he|she|it)\s+(go)\b",     lambda m: m.group(1) + " goes",
         "Subject-verb agreement", "Third-person singular requires 'goes'"),
        # he tell -> he told, he say -> he said, I/he meet -> met (past narrative)
        (r"\b(he|she|it)\s+(tell)\b",   lambda m: m.group(1) + " told",
         "Tense", "Past narrative context: tell -> told"),
        (r"\b(he|she|it)\s+(say)\b",    lambda m: m.group(1) + " said",
         "Tense", "Past narrative context: say -> said"),
        (r"\b(he|she|it|I)\s+(meet)\b", lambda m: m.group(1) + " met",
         "Tense", "Past narrative context: meet -> met"),
        # they is → they are
        (r"\b(they|we|you)\s+(is)\b",   lambda m: m.group(1) + " are",
         "Subject-verb agreement", "Plural subject requires 'are', not 'is'"),
        (r"\b(they|we|you)\s+(was)\b",  lambda m: m.group(1) + " were",
         "Subject-verb agreement", "Plural subject requires 'were', not 'was'"),
        # AI is / Artificial Intelligence is
        (r"\b(Artificial Intelligence|AI|Machine Learning|Deep Learning)\s+(are)\b",
         lambda m: m.group(1) + " is",
         "Subject-verb agreement", "Proper noun subject is singular; requires 'is'"),
        # singular noun + are → is
        (r"\b(intelligence|technology|knowledge|information|weather|news|homework|software|hardware|data)\s+(are)\b",
         lambda m: m.group(1) + " is",
         "Subject-verb agreement", f"'{'{m.group(1)}'}' is singular/uncountable; use 'is'"),
    ]

    for pat, repl_fn, ctype, reason in SV_PATTERNS:
        matches = list(re.finditer(pat, p.text, re.IGNORECASE))
        for m in matches:
            new = repl_fn(m)
            if new.lower() != m.group(0).lower():
                p.corrections.append(Correction(m.group(0), new, ctype, reason))
                p.gr_fixed += 1
        p.text = re.sub(pat, lambda m, fn=repl_fn: fn(m), p.text, flags=re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════
#  STAGE 3 — ARTICLES & PREPOSITIONS
# ═══════════════════════════════════════════════════════════════

def stage_articles_prepositions(p: Pipeline) -> None:

    # ── Missing "the" before common singular nouns ─────────────
    THE_PATTERNS = [
        # "future of X" → "the future of X"
        (r"\b((?:is|are|was|were|will be|be)\s+)(future)\b",
         r"\1the future",
         "Article", "Definite article 'the' required before 'future' in this context"),
        # "go to park" → "go to the park"
        (r"\b(go(?:es|ing|went|ne)?|went|come|came|coming|run|ran|walk(?:ed|ing)?|drive|drove)\s+to\s+(park|store|market|beach|hospital|office|school|gym|library|cinema|theatre|airport|station)\b",
         r"\1 to the \2",
         "Article", "Definite article 'the' required after 'to' with a specific place"),
        # "played with X" → handled by childrens→children already
    ]
    for pat, rep, ctype, reason in THE_PATTERNS:
        p.sub(pat, rep, ctype, reason)

    # ── Preposition: "in [university/institution]" → "at" ─────
    # Match "studying/enrolled/study in [Capitalised word]*university|college|..."
    def fix_institution_prep(m: re.Match) -> str:
        verb = m.group(1)
        noun = m.group(2)
        p.corrections.append(Correction(
            f"{verb} in {noun}",
            f"{verb} at {noun}",
            "Preposition",
            "Use 'at' with institutions (universities, colleges, schools), not 'in'"
        ))
        p.gr_fixed += 1
        return f"{verb} at {noun}"

    p.text = re.sub(
        r"\b(studying|study|studies|studied|enrolled?s?|learning|work(?:ing|ed|s)?|teach(?:ing|es|ed)?)\s+in\s+([A-Z][A-Za-z\s]*(?:University|College|Institute|School|Academy|IIT|NIT|MIT))",
        fix_institution_prep,
        p.text
    )

    # Also catch lowercase version after proper noun pass hasn't run yet
    p.sub(
        r"\b(studying|study|studies|studied)\s+in\s+(soa|iit|nit|mit|harvard|oxford)\b",
        r"\1 at \2",
        "Preposition",
        "Use 'at' with institutions"
    )

    # ── "good in English" → "good at English" ─────────────────
    p.sub(
        r"\bgood\s+in\s+(English|math|science|programming|coding|sports|music)\b",
        r"good at \1",
        "Preposition",
        "'good at' is correct when describing skill, not 'good in'"
    )

    # ── Article for internship ────────────────────────────────
    p.sub(r"\bfor\s+(?!the\b)(internship|job|position|role)\b",
          r"for the \1", "Article",
          "Use definite article 'the' with specific internship/job references")


# ═══════════════════════════════════════════════════════════════
#  STAGE 4 — DISCOURSE & PUNCTUATION
# ═══════════════════════════════════════════════════════════════

def stage_discourse(p: Pipeline) -> None:

    # ── "but [past-time adverb]" → "However, [past-time]" ─────
    # "...homework but yesterday he..." → "...homework. However, yesterday he..."
    def fix_contrastive_but(m: re.Match) -> str:
        before_period = m.group(1)   # e.g. "homework"
        adverb        = m.group(2)   # e.g. "yesterday"
        replacement   = f"{before_period}. However, {adverb} "
        p.corrections.append(Correction(
            m.group(0), replacement.strip(),
            "Grammar",
            "'But' connecting two complete clauses with contrasting time should become 'However,' with a period"
        ))
        p.gr_fixed += 1
        return replacement

    p.text = re.sub(
        r"(\w+)\s+but\s+(yesterday|last\s+\w+|earlier|previously|afterward|then)\s+",
        fix_contrastive_but,
        p.text, flags=re.IGNORECASE
    )

    # ── Comma after past-time opener ──────────────────────────
    # "Yesterday he went" → "Yesterday, he went"
    p.sub(
        r"^(Yesterday|Last\s+\w+|Earlier|Previously|Afterward|Afterwards|However|Moreover|Furthermore|Nevertheless|Therefore|Meanwhile|Instead)\s+(?!,)([A-Z])",
        r"\1, \2",
        "Punctuation",
        "Introductory time/transition adverb should be followed by a comma"
    )
    p.sub(
        r"([.!?]\s+)(Yesterday|Last\s+\w+|Earlier|Previously|Afterward|Afterwards|However|Moreover|Furthermore|Nevertheless|Therefore|Meanwhile|Instead)\s+(?!,)([a-zA-Z])",
        r"\1\2, \3",
        "Punctuation",
        "Introductory time adverb at sentence start should be followed by a comma"
    )

    # ── Comma before coordinating conjunction + new subject ───
    # "...university, and yesterday..." — only when different subjects
    p.sub(
        r"\b(SOA University|university|college|school)\s+(and)\s+(yesterday|I|he|she|they|we)\b",
        r"\1, \2 \3",
        "Punctuation",
        "Comma before coordinating conjunction joining two independent clauses"
    )

    # ── Comma: "X, and I" pattern ────────────────────────────
    prev = p.text
    p.text = re.sub(r"(?<![,])(\s+and\s+I\b)", r", and I", p.text)
    if p.text != prev:
        p.corrections.append(Correction(
            "and I", ", and I", "Punctuation",
            "Comma required before coordinating conjunction 'and' when joining independent clauses"
        ))
        p.gr_fixed += 1

    # ── Salutation comma ──────────────────────────────────────
    def fix_salutation(m: re.Match) -> str:
        greeting  = m.group(1)
        title     = m.group(2).capitalize()
        rest      = m.group(3)
        result    = f"{greeting} {title},{rest}"
        p.corrections.append(Correction(
            m.group(0).strip(), result.strip(),
            "Punctuation",
            "Comma required after salutation"
        ))
        p.gr_fixed += 1
        return result

    p.text = re.sub(
        r"^(Hello|Hi|Dear|Hey|Greetings)\s+(Sir|Ma'?am|Mr|Mrs|Ms|Dr|Prof|sir|ma'?am|mr|mrs|ms|dr|prof)\.?(\s+)(?!,)",
        fix_salutation,
        p.text,
        flags=re.IGNORECASE
    )


# ═══════════════════════════════════════════════════════════════
#  STAGE 5 — PROPER NOUNS & CAPITALIZATION
# ═══════════════════════════════════════════════════════════════

def stage_proper_nouns(p: Pipeline) -> None:

    # ── Named proper nouns ────────────────────────────────────
    for pattern_str, correct_form in PROPER_NOUNS.items():
        m = re.search(rf"\b{re.escape(pattern_str)}\b", p.text, re.IGNORECASE)
        if m and m.group(0) != correct_form:
            p.corrections.append(Correction(
                m.group(0), correct_form,
                "Capitalization",
                f"'{pattern_str}' is a proper noun and must be capitalised as '{correct_form}'"
            ))
            p.gr_fixed += 1
        p.text = re.sub(
            rf"\b{re.escape(pattern_str)}\b", correct_form, p.text, flags=re.IGNORECASE
        )

    # ── Person names after "my name is / I am" ───────────────
    NOT_NAMES = {
        "a","an","the","and","or","but","in","at","to","for","of","on",
        "studying","working","learning","going","doing","trying","planning",
        "happy","sad","good","great","fine","well","here","there","also",
        "passionate","interested","excited","ready","able","available",
        "very","really","quite","just","already","still","now","today",
    }

    def cap_name(m: re.Match) -> str:
        prefix = m.group(1)
        name   = m.group(2)
        if name.lower() in NOT_NAMES or name[0].isupper():
            return m.group(0)
        cap = name.capitalize()
        p.corrections.append(Correction(name, cap, "Capitalization",
            f"Person name '{name}' must be capitalised"))
        p.gr_fixed += 1
        return prefix + cap

    p.text = re.sub(
        r"(my name is\s+)([a-zA-Z][a-zA-Z]*)",
        cap_name,
        p.text,
        flags=re.IGNORECASE
    )

    # ── Standalone pronoun I ──────────────────────────────────
    prev = p.text
    p.text = re.sub(r"(?<![a-zA-Z'])i(?![a-zA-Z'])", "I", p.text)
    if p.text != prev:
        p.corrections.append(Correction("i", "I", "Capitalization",
            "The first-person pronoun 'I' must always be capitalised"))
        p.gr_fixed += 1


# ═══════════════════════════════════════════════════════════════
#  STAGE 6 — SENTENCE-START CAPITALIZATION
# ═══════════════════════════════════════════════════════════════

def stage_sentence_caps(p: Pipeline) -> None:
    # Beginning of text
    p.text = re.sub(r"^([a-z])", lambda m: m.group(1).upper(), p.text)
    # After sentence-ending punctuation
    prev = p.text
    p.text = re.sub(
        r"([.!?]\s+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        p.text
    )
    if p.text != prev:
        p.corrections.append(Correction(
            "lowercase after period", "Uppercase",
            "Capitalization",
            "First letter of every sentence must be capitalised"
        ))


# ═══════════════════════════════════════════════════════════════
#  STAGE 7 — WHITESPACE & FINAL CLEANUP
# ═══════════════════════════════════════════════════════════════

def stage_cleanup(p: Pipeline) -> None:
    p.text = re.sub(r"  +", " ", p.text)
    p.text = re.sub(r" ([,.])", r"\1", p.text)   # no space before punctuation
    p.text = p.text.strip()


# ═══════════════════════════════════════════════════════════════
#  SCORE CALCULATION
# ═══════════════════════════════════════════════════════════════

def calculate_scores(original: str, p: Pipeline) -> tuple[int, int, int, int]:
    """Returns (grammar_score, spelling_score, readability_score, overall)."""
    words = len(original.split())

    sp_penalty = min(50, p.sp_fixed * 8)
    gr_penalty = min(50, p.gr_fixed * 6)

    sp_score   = max(50, 100 - sp_penalty)
    gr_score   = max(50, 100 - gr_penalty)

    # Readability: based on avg sentence length and word length
    sents      = max(1, len(re.findall(r"[.!?]+", p.text)))
    avg_sl     = words / sents
    rd_score   = max(60, 100 - max(0, avg_sl - 20) * 2)   # penalise very long sentences

    overall    = round(gr_score * 0.40 + sp_score * 0.35 + rd_score * 0.25)
    return int(gr_score), int(sp_score), int(rd_score), int(overall)


# ═══════════════════════════════════════════════════════════════
#  FALLBACK ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def fallback_correction(text: str) -> dict:
    p = Pipeline(text)

    stage_spelling(p)
    stage_morphology(p)
    stage_articles_prepositions(p)
    stage_discourse(p)
    stage_proper_nouns(p)
    stage_sentence_caps(p)
    stage_cleanup(p)

    gr_score, sp_score, rd_score, overall = calculate_scores(text, p)

    words     = len(p.text.split())
    sents     = max(1, len(re.findall(r"[.!?]+", p.text)))
    chars     = len(p.text)
    read_sec  = max(1, math.ceil(words / 3.33))
    total     = p.sp_fixed + p.gr_fixed

    # De-duplicate explanations
    seen: set[str] = set()
    unique_expl: list[dict] = []
    for c in p.corrections:
        key = c.before.lower() + "|" + c.after.lower()
        if key not in seen:
            seen.add(key)
            unique_expl.append(c.to_dict())

    return {
        "original":          text,
        "corrected":         p.text,
        "score":             overall,
        "grammar_score":     gr_score,
        "spelling_score":    sp_score,
        "readability_score": int(rd_score),
        "overall_score":     overall,
        "mistakes":          total,
        "confidence":        min(95, 70 + total * 2),
        "changes":           list({c.ctype for c in p.corrections}),
        "explanations":      unique_expl,
        "stats": {
            "words":            words,
            "sentences":        sents,
            "characters":       chars,
            "reading_time_sec": read_sec,
            "grammar_fixed":    p.gr_fixed,
            "spelling_fixed":   p.sp_fixed,
        }
    }


# ═══════════════════════════════════════════════════════════════
#  MAIN ROUTER
# ═══════════════════════════════════════════════════════════════

def correct_text(text: str) -> dict:
    result = correct_with_claude(text)
    if result:
        return build_response(text, result)
    return fallback_correction(text)


def validate(text: str) -> str | None:
    if not text:              return "Empty text"
    if len(text.strip()) < 3: return "Text too short"
    if len(text) > 5000:      return "Text too long (max 5000 chars)"
    return None


# ═══════════════════════════════════════════════════════════════
#  FLASK ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/correct", methods=["POST"])
def correct():
    body = request.get_json(silent=True)
    if not body or "text" not in body:
        return jsonify({"error": "No text provided"}), 400
    text = body["text"].strip()
    err  = validate(text)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(correct_text(text))


@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "3.0"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
