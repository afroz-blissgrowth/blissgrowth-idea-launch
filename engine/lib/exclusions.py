"""Employment exclusions: do not contact people who are not in a current job.

Call finding (CHANGES-PROPOSAL-2026-10-21): "Exclude garden leave, retired, career break, ended-role (experience array end
date), Open to Work." A person who matches gets `exclusion_reason` in people.csv and the "4 People" tab, and NO channel
(channels is empty, so they never reach a Ready tab). Rows are never deleted. Applied after enrichment and after the
activity check, because that is when the data exists.

Three sources, each switchable in config.json `exclusions`:
  1. Keywords on the headline and titles (config `exclusions.groups`: garden_leave, retired, career_break, open_to_work,
     between_roles, seeking, looking_for, former). Plain phrases match on word boundaries, case-insensitive; `re:<regex>`
     is a regular expression. The headline comes from Apollo (person.headline) and from the LinkedIn activity checker.
  2. Apollo person data (people/bulk_match employment_history, kept in enrich/enrich.jsonl):
       apollo_no_current_position  the history has entries, none is `current` and every one has an end date
       apollo_role_ended           the entry at the target company has an end_date and is not current
  3. The LinkedIn activity checker output (activity/cache.jsonl, columns headline, current_title, current_company,
     jobs_count, current_jobs_count, latest_job_start of the checker):
       linkedin_no_current_position  current_jobs_count is 0 although the profile lists jobs (jobs_count > 0)
Missing data never excludes anyone. The reason text starts with the category, `category: detail`, several are joined by '; '.

Known limits (also in the README): Apollo employment data can be stale (a person who changed jobs may still show an old
current entry, or none), a profile can say "open to work" in a banner photo that no text shows, and a keyword list is
only as good as its phrases. The bare words seeking, looking for, former and ex- are NOT in the default lists because they
match working people ("ex-Google founder", "looking for talented engineers"); the defaults use narrower phrases and
`former` / `ex-` only at the START of the title or the checker's current_title (not the headline: "Ex-Google | CEO at
Acme" is a working person). Edit config.json to widen them.
"""
from __future__ import annotations

import re

import config

PILOT_REJECTED = "pilot_rejected"


# ---- keyword matching (pure) ---------------------------------------------------------------------
def compile_phrase(p):
    """'open to work' -> word-boundary regex; 're:^former\\b' -> that regex. Case-insensitive."""
    if p.startswith("re:"):
        return re.compile(p[3:], re.I)
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(p.strip()) + r"(?![A-Za-z0-9])", re.I)


def compile_groups(groups=None):
    """[(group, fields, [(phrase, regex)])] from config `exclusions.groups`."""
    groups = groups if groups is not None else (config.get("exclusions.groups") or {})
    out = []
    for name, g in groups.items():
        pats = []
        for p in g.get("keywords") or []:
            if str(p).strip():
                pats.append((p, compile_phrase(str(p))))
        out.append((name, list(g.get("fields") or ["headline", "title", "current_title"]), pats))
    return out


def keyword_reasons(fields, groups=None):
    """fields: {field_name: text}. Returns [(category, detail)] one per matching group (first matching phrase)."""
    out = []
    for name, where, pats in compile_groups(groups):
        hit = None
        for f in where:
            text = (fields.get(f) or "").strip()
            if not text:
                continue
            for phrase, rx in pats:
                m = rx.search(text)
                if m:
                    hit = "%s says '%s'" % (f, m.group(0)[:60])
                    break
            if hit:
                break
        if hit:
            out.append((name, hit))
    return out


# ---- structured sources (pure) -------------------------------------------------------------------
def _norm_name(s):
    s = re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())
    s = re.sub(r"\b(gmbh|ltd|limited|inc|llc|plc|ag|sa|bv|nv|group|holding|holdings|co|corp|corporation|the)\b", " ", s)
    return " ".join(s.split())


def same_company(a, b):
    """Loose company name match: equal after dropping legal suffixes, or one contains the other (min 4 chars)."""
    x, y = _norm_name(a), _norm_name(b)
    if not x or not y:
        return False
    return x == y or (len(x) >= 4 and x in y) or (len(y) >= 4 and y in x)


def apollo_reasons(history, company, cfg=None):
    """[(category, detail)] from the compact employment history [{org, title, current, start, end}]."""
    cfg = cfg or config.get("exclusions") or {}
    out = []
    history = [h for h in (history or []) if isinstance(h, dict)]
    if not history:
        return out
    # An entry with no end date and no `current` flag is incomplete data, not an ended job (missing data never excludes),
    # so "no current position" needs every listed job to have an end date.
    if cfg.get("apollo_no_current_position", True) and not any(h.get("current") for h in history) \
            and all(h.get("end") for h in history):
        out.append(("apollo_no_current_position", "Apollo employment history lists %d jobs and none is current" % len(history)))
    if cfg.get("apollo_target_role_ended", True) and company:
        at = [h for h in history if same_company(h.get("org"), company)]
        if at and not any(h.get("current") for h in at):
            ended = [h for h in at if h.get("end")]
            if ended:
                out.append(("apollo_role_ended", "role at %s ended %s" % (ended[0].get("org") or company, str(ended[0]["end"])[:10])))
    return out


def _int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def linkedin_reasons(act, cfg=None):
    cfg = cfg or config.get("exclusions") or {}
    if not act or not cfg.get("linkedin_no_current_position", True):
        return []
    cur, total = _int(act.get("current_jobs_count")), _int(act.get("jobs_count"))
    if cur == 0 and total is not None and total > 0:
        return [("linkedin_no_current_position", "LinkedIn lists %d jobs and none is current (latest job start %s)"
                 % (total, act.get("latest_job_start") or "unknown"))]
    return []


def evaluate(person, enrich=None, activity=None, cfg=None):
    """Exclusion for one person. person: dict with title and company. enrich: the enrich/enrich.jsonl record (headline,
    employment_history). activity: the activity cache record. Returns {"reason": str, "categories": [str]} (reason '' = keep)."""
    cfg = cfg if cfg is not None else (config.get("exclusions") or {})
    if not cfg.get("enabled", True):
        return {"reason": "", "categories": []}
    enrich, activity = enrich or {}, activity or {}
    found = []
    fields = {"title": person.get("title", ""), "headline": "", "current_title": ""}
    heads = []
    if cfg.get("use_apollo_employment", True) and enrich.get("headline"):
        heads.append(enrich["headline"])
    if cfg.get("use_linkedin_checker", True):
        if activity.get("headline"):
            heads.append(activity["headline"])
        fields["current_title"] = activity.get("current_title", "") or ""
    # each headline is checked on its own so a phrase cannot span two of them
    seen = set()
    for h in heads or [""]:
        fields["headline"] = h
        for cat, det in keyword_reasons(fields):
            if cat not in seen:
                seen.add(cat)
                found.append((cat, det))
    if cfg.get("use_apollo_employment", True):
        found += [f for f in apollo_reasons(enrich.get("employment_history"), person.get("company", ""), cfg) if f[0] not in seen]
    if cfg.get("use_linkedin_checker", True):
        found += linkedin_reasons(activity, cfg)
    return {"reason": "; ".join("%s: %s" % f for f in found)[:300], "categories": [f[0] for f in found]}


def category_counts(rows):
    """{category: n} over rows' exclusion_reason ('cat: detail; cat: detail'), plus 'total' (people excluded)."""
    c, total = {}, 0
    for r in rows:
        reason = r.get("exclusion_reason") or ""
        if not reason:
            continue
        total += 1
        for part in reason.split("; "):
            cat = part.split(":", 1)[0].strip()
            if cat:
                c[cat] = c.get(cat, 0) + 1
    c["total"] = total
    return c
