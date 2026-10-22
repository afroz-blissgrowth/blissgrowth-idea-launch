"""Copy rule and spam-word checker for outbound copy (LinkedIn invite, follow-up, InMail; email hooks).

Port of the coldoutboundskills `spam-word-checker` skill (MIT, copyright 2026 GrowthEngineX, see NOTICE.md): the banned
single words, banned short phrases, promotional, phishing and irrelevant-category lists, the formatting bans and the
silence-based closeout rule are copied from that skill. Adaptations (marked ADAPT):
  - The COS lists target cold EMAIL deliverability. On LinkedIn a message from a person is not spam filtered the same way, so
    single words (get, open, new, now ...) are WARNINGS on LinkedIn channels and ERRORS on email. Phrases and
    promotional or phishing wording are errors everywhere.
  - "No greeting prefix before the first name" is an email rule and is not applied to LinkedIn ("Hi {FIRST_NAME}" is normal).
  - Blissgrowth rules added: no em dashes, no links in first messages, no filler ("quick chat", "just checking in"),
    never an internal idea name, no time commitment, no pay numbers, no funding amounts, "Blissgrowth" spelled right,
    advisor ask (a question, not a sales pitch), HeyReach limits (invite 300 chars, InMail 1900 chars, subject 200).

check(item, ctx) -> {"errors": [...], "warnings": [...]} (pure, no I/O). Every finding is {"rule", "detail"}.
Rules live in this file and in config.json `copy`; extend the lists there, not in scripts.
"""
from __future__ import annotations

import re

import config

EM = "\u2014"
EN = "\u2013"

# ---- COS lists (verbatim from spam-word-checker/SKILL.md) -------------------------------------------------------
BANNED_WORDS = ["get", "bank", "credit", "access", "open", "compare", "problem", "now", "billing", "deal", "finance",
                "financial", "claims", "insurance", "mortgage", "soon", "new", "performance", "freedom", "home", "sales",
                "medical", "urgent", "life", "marketing", "investment", "diagnostics", "friend", "cash", "invoice",
                "extra", "purchase"]
BANNED_PHRASES = ["off chance", "one time", "all good", "following up here", "last note from me here", "great fit",
                  "bumping this once", "just following up once", "circle back", "one more quick follow-up",
                  "keep this open", "compare notes", "compare notes live", "appreciate the reply"]
PROMO = ["$$$", "50% off", "100% guaranteed", "100% free", "100% off", "100% satisfied", "access now", "act fast",
         "act immediately", "act now", "action required", "affordable deal", "amazing", "amazing deal", "amazing offer",
         "apply here", "apply now", "avoid bankruptcy", "bargain", "best bargain", "best deal", "best offer", "best price",
         "best rates", "big profit", "bonus", "buy now", "buy today", "call now", "can't live without", "cash bonus",
         "cash out", "claim now", "claim your discount", "click", "click below", "click here", "click this link",
         "contact us immediately", "deal ending soon", "discount", "don't delete", "double your money",
         "double your wealth", "drastically reduced", "earn", "earn cash", "earn extra income", "earn money",
         "easy income", "exclusive deal", "expires today", "extra cash", "extra income", "fantastic", "fantastic offer",
         "fast cash", "final call", "for free", "free access", "free consultation", "free gift", "free membership",
         "free money", "free quote", "free trial", "full refund", "get it now", "get out of debt", "get started now",
         "giveaway", "great news", "guaranteed deposit", "guaranteed results", "hurry up", "important information",
         "immediately", "increase revenue", "increase sales", "incredible deal", "instant earnings", "instant income",
         "instant savings", "investment advice", "join millions", "limited time", "lowest price", "make money",
         "million dollars", "money-back guarantee", "must read", "no catch", "no cost", "no obligation",
         "no strings attached", "once in a lifetime", "only $", "only available here", "order now", "order today",
         "please read", "price protection", "profits", "promise", "pure profit", "quote", "risk-free",
         "satisfaction guaranteed", "save $", "save big money", "save up to", "sign up free", "special invitation",
         "special offer", "special promotion", "supplies are limited", "take action now", "the best", "this won't last",
         "thousands", "time limited", "today", "top urgent", "trial", "unbeatable offer", "unbelievable", "unlimited",
         "urgent", "what are you waiting for?", "while supplies last", "will not believe", "winner announced",
         "wonderful", "you are a winner", "you will not believe your eyes"]
PHISH = ["access your account", "account update", "activate now", "change password", "click to verify",
         "confirm your details", "confidential information", "data breach", "download now", "final notice",
         "important update", "immediate action required", "install now", "last warning", "log in now",
         "new login detected", "password reset", "payment details needed", "phishing alert", "security breach",
         "security update", "update account", "verify identity", "warning message"]
IRRELEVANT = ["100% natural", "adult content", "bet now", "blackjack", "casino bonus", "cure for", "diet pill",
              "doctor recommended", "fat burner", "fast weight loss", "free chips", "free spins", "gamble online",
              "guaranteed weight loss", "jackpot", "lottery winner", "medical breakthrough", "miracle cure",
              "natural remedy", "no prescription needed", "online betting", "online casino", "online pharmacy",
              "pain relief", "poker tournament", "prescription drugs", "reverse aging", "risk-free bet",
              "safe and effective", "scientifically proven", "secret formula", "slots jackpot", "spin to win",
              "vip offer", "weight loss", "winning numbers", "xxx"]
# Silence-based closeout patterns (banned in COS: the user must act for a sequence to stop)
SILENCE = [r"take silence as a no", r"read no reply as a pass", r"assume no response means no interest",
           r"if i don'?t hear back,? i('| wi)ll (leave it there|let this one go|leave you alone)",
           r"stay out of the way", r"no reply (as|means) a? ?(pass|no)"]

# ---- Blissgrowth rules ---------------------------------------------------------------------------------------------
FILLER = ["quick chat", "quick call", "quick catch up", "quick catch-up", "just checking in", "checking in",
          "touching base", "touch base", "following up", "follow up on my", "bumping", "bump this", "hope this finds you",
          "hope you're well", "hope you are well", "i wanted to reach out", "reaching out", "pick your brain",
          "quick question", "just wanted to", "circling back", "any thoughts?"]
SALES_WORDS = ["demo", "pricing", "book a", "schedule a", "our platform", "our solution", "roi", "case study",
               "free trial", "buy", "proposal", "sales call", "pitch", "purchase", "contract"]
PAY_WORDS = r"(\bper hour\b|\ban hour\b|/hr\b|\bhourly\b|\bpaid\b|\bpay\b|\bfees?\b|\bhonorari|\bcompensat|\bretainer\b|\brates?\b|\bequity\b|\bstipend\b|\bper call\b|\bper session\b|\bpaying\b|\bpays\b|\bfor your time\b|\bgift card|\bvoucher|\bthank[- ]you\b|\bincentive|\breward)"
PAY_NO_CURRENCY = r"\b\d[\d,\.]*\s?(?:k\s)?(?:/|per\s|an\s|a\s)(?:hour|hr|call|session|interview)\b"
FUND_WORDS = r"\b(raised|raising|funding|funded|round|seed|series [a-d]|investors?|invested|investment)\b"
CURRENCY = r"(?:[$£€]\s?\d[\d,\.]*\s?(?:k|m|bn|million|billion)?|\d[\d,\.]*\s?(?:usd|gbp|eur|dollars|pounds|euros))"
TIME_COMMIT = [r"\b\d+\s?[- ]?(?:min|mins|minute|minutes|hr|hrs|hour|hours)\b", r"\b(?:a|one|two|three|five|ten|fifteen|twenty|thirty)"
               r"\s+(?:few\s+)?(?:minute|minutes|hour|hours)\b", r"\bhalf an hour\b", r"\ban hour\b", r"\bfew minutes\b", r"\b\d+[- ]minute\b",
               r"\b(?:short|brief|quick)\s+(?:call|chat|conversation|meeting)\b"]
URL_RE = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(?:com|io|co|ai|net|org|uk|app)\b(?:/\S*)?|calendly|bit\.ly)", re.I)
VAR_RE = re.compile(r"\{([A-Za-z_]+)\}")

ALLOWED_VARS = {"FIRST_NAME", "LAST_NAME", "COMPANY", "LOCATION", "POSITION", "INDUSTRY", "MY_FIRST_NAME",
                "MY_LAST_NAME", "MY_COMPANY", "MY_LOCATION", "MY_POSITION"}
FALLBACK_VARS = {"FIRST_NAME", "LAST_NAME", "MY_FIRST_NAME", "MY_LAST_NAME"}

LIMITS = {"li_invite": 300, "inmail": 1900, "li_followup": 8000, "email": 8000}
FIRST_MESSAGE = {"li_invite": True, "inmail": True}


def _cfg():
    c = config.get("copy", {}) or {}
    return c


def _words_in(text, words):
    t = text.lower()
    return [w for w in words if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", t)]


def _phrase_hits(text, phrases):
    t = text.lower()
    return [p for p in phrases if p in t]


def internal_names(ctx):
    """Internal idea names that must never appear: config list, the run's idea name and slug, and any Bliss<Word>
    except Blissgrowth."""
    names = set(n.lower() for n in _cfg().get("internal_idea_names", []))
    for k in ("idea_name", "idea_slug"):
        v = (ctx or {}).get(k)
        if v:
            names.add(str(v).lower())
            names.add(re.sub(r"-test$", "", str(v).lower()))
    return set(n for n in names if len(n) >= 4)


def word_count(text):
    return len(re.findall(r"\S+", re.sub(r"\{[A-Za-z_]+\}", "x", text or "")))


def _text_fields(item):
    parts = []
    if item.get("subject"):
        parts.append(("subject", item["subject"]))
    parts.append(("body", item.get("body") or ""))
    if item.get("fallback"):
        parts.append(("fallback", item["fallback"] if isinstance(item["fallback"], str) else str(item["fallback"])))
    return parts


def check(item, ctx=None):
    """item: {channel, tier, step, variant, subject, body, fallback?}. ctx: {idea_name, idea_slug, channel_kind?}."""
    ctx = ctx or {}
    cfg = _cfg()
    errors, warnings = [], []

    def err(rule, detail):
        errors.append({"rule": rule, "detail": detail})

    def warn(rule, detail):
        warnings.append({"rule": rule, "detail": detail})

    channel = item.get("channel", "")
    step = int(item.get("step") or 1)
    body = item.get("body") or ""
    kind = "email" if channel.startswith("email") else "linkedin"
    blank_ok = channel == "li_invite" and (item.get("variant") or "").lower() in ("blank", "v0", "b")
    if not body.strip() and not blank_ok:
        err("empty", "empty body (only a blank LinkedIn invite may be empty, mark variant 'blank')")
        return {"errors": errors, "warnings": warnings}
    names = internal_names(ctx)
    for field, text in _text_fields(item):
        if not text:
            continue
        low = text.lower()
        if EM in text or EN in text:
            err("em_dash", "%s contains an em or en dash; use a comma, a period or brackets" % field)
        if " -- " in text:
            warn("double_hyphen", "%s uses ' -- ' as a dash" % field)
        # links
        if URL_RE.search(text):
            first = FIRST_MESSAGE.get(channel) or step == 1
            (err if first else warn)("link", "%s contains a link or domain (%s)" % (
                field, "none allowed in a first message" if first else "avoid; allowed in later steps only if asked for"))
        # filler
        for w in _phrase_hits(text, FILLER):
            err("filler", "%s uses filler '%s'" % (field, w))
        # internal names
        for n in names:
            if re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", low):
                err("internal_idea_name", "%s names the internal idea '%s'; describe it in plain words" % (field, n))
        for m in re.finditer(r"bliss(?!growth\b)[a-z]*[A-Z]\w*|Bliss(?!growth)[A-Z]\w+", text):
            err("internal_idea_name", "%s contains '%s', an internal idea name" % (field, m.group(0)))
        for m in re.finditer(r"bliss\s?growth", text, re.I):
            if m.group(0) != "Blissgrowth":
                err("spelling", "%s spells Blissgrowth as '%s'" % (field, m.group(0)))
        # time commitment
        for pat in TIME_COMMIT:
            m = re.search(pat, low)
            if m:
                err("time_commitment", "%s states a time commitment ('%s')" % (field, m.group(0)))
                break
        # pay numbers
        for m in re.finditer(CURRENCY, low):
            around = low[max(0, m.start() - 40): m.end() + 40]
            if re.search(PAY_WORDS, around):
                err("pay_number", "%s states pay ('%s')" % (field, around.strip()))
                break
        m = re.search(PAY_NO_CURRENCY, low)
        if m:
            err("pay_number", "%s states pay ('%s')" % (field, m.group(0)))
        for m in re.finditer(CURRENCY, low):
            around = low[max(0, m.start() - 40): m.end() + 40]
            if re.search(FUND_WORDS, around):
                err("funding_amount", "%s gives a funding amount or investor detail ('%s')" % (field, around.strip()))
                break
        # COS lists
        for p in _phrase_hits(text, BANNED_PHRASES):
            err("spam_phrase", "%s: banned phrase '%s'" % (field, p))
        for p in _phrase_hits(text, PROMO):
            if p in ("click", "earn", "today", "promise", "trial", "quote", "profits", "bonus", "immediately"):
                if not _words_in(text, [p]):
                    continue
            single = " " not in p and "$" not in p and "%" not in p
            (warn if (single and kind == "linkedin") else err)("spam_promo", "%s: promotional wording '%s'" % (field, p))  # ADAPT: single words only warn on LinkedIn
        for p in _phrase_hits(text, PHISH):
            err("spam_phishing", "%s: phishing-style wording '%s'" % (field, p))
        for p in _phrase_hits(text, IRRELEVANT):
            err("spam_category", "%s: blacklisted category '%s'" % (field, p))
        for pat in SILENCE:
            if re.search(pat, low):
                err("silence_closeout", "%s promises to stop on silence; the reader must act for us to stop" % field)
        sw = _words_in(text, BANNED_WORDS)
        if sw and not cfg.get("ignore_single_word_flags", False):
            (err if kind == "email" else warn)("spam_word", "%s uses flagged words: %s" % (field, ", ".join(sorted(set(sw)))))
        # sales tone
        sales = _words_in(text, SALES_WORDS)
        if sales:
            warn("sales_tone", "%s sounds like sales (%s); this is an advisor ask" % (field, ", ".join(sales)))
        # formatting
        if re.search(r"!{2,}", text):
            err("exclamations", "%s has multiple exclamation marks" % field)
        elif text.count("!") > 1:
            warn("exclamations", "%s has more than one exclamation mark" % field)
        caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", re.sub(r"\{[A-Z_]+\}", "", text)) if w not in cfg.get("caps_allowed", [])]
        if caps:
            warn("all_caps", "%s has ALL CAPS words: %s" % (field, ", ".join(sorted(set(caps)))))
    # placeholders
    for field, text in _text_fields(item):
        used = set(VAR_RE.findall(text or ""))
        bad = used - ALLOWED_VARS
        if bad:
            err("placeholder", "%s has unknown placeholders: %s" % (field, ", ".join("{%s}" % b for b in sorted(bad))))
        if field == "fallback":
            nofb = used - FALLBACK_VARS
            if nofb:
                err("fallback_vars", "fallback may only use {FIRST_NAME}, {LAST_NAME}, {MY_FIRST_NAME}, {MY_LAST_NAME}")
    used = set(VAR_RE.findall(body)) | set(VAR_RE.findall(item.get("subject") or ""))
    if (used - FALLBACK_VARS) and not item.get("fallback") and channel.startswith(("li_", "inmail")):
        err("fallback_needed", "uses %s so a fallback text without them is required" % ", ".join(
            "{%s}" % u for u in sorted(used - FALLBACK_VARS)))
    # limits and length
    limit = LIMITS.get(channel)
    if limit and len(body) > limit:
        err("too_long", "body is %d chars, the %s limit is %d" % (len(body), channel, limit))
    if channel == "inmail":
        subj = item.get("subject") or ""
        if not subj.strip():
            err("subject", "an InMail needs a subject")
        elif len(subj) > 200:
            err("subject", "subject is %d chars, limit 200" % len(subj))
        elif len(subj) > cfg.get("inmail_subject_target", 60):
            warn("subject", "subject is %d chars, aim for %d or fewer" % (len(subj), cfg.get("inmail_subject_target", 60)))
    wc = word_count(body)
    rng = (cfg.get("word_targets") or {}).get(channel)
    if rng and body.strip() and not (rng[0] <= wc <= rng[1]):
        warn("length", "%d words, target %d to %d for %s" % (wc, rng[0], rng[1], channel))
    # advisor ask
    if body.strip() and channel in ("li_followup", "inmail") and "?" not in body:
        warn("no_question", "no question: an advisor ask ends with a question the reader can answer in a few words")
    if channel == "li_invite" and body.strip() and len(body) > 300:
        err("too_long", "connection note is over 300 chars")
    return {"errors": errors, "warnings": warnings}


def check_all(items, ctx=None):
    """Run check on every item, add cross-item checks (duplicate bodies). Returns {id: result}."""
    res = {}
    seen = {}
    for it in items:
        r = check(it, ctx)
        key = re.sub(r"\s+", " ", (it.get("body") or "").strip().lower())
        if key:
            if key in seen and seen[key] != (it.get("channel"), it.get("tier"), it.get("step"), it.get("variant")):
                r["warnings"].append({"rule": "duplicate", "detail": "same body as another item"})
            seen[key] = (it.get("channel"), it.get("tier"), it.get("step"), it.get("variant"))
        res[item_id(it)] = r
    return res


def item_id(it):
    return "%s|%s|%s|%s" % (it.get("channel"), it.get("tier"), it.get("step"), it.get("variant"))
