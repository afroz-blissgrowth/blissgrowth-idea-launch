"""Brief schema: load, validate, and turn into Apollo filter sets.

brief.json is written by /iv-brief after the back-and-forth with the user. Apollo filter
keys inside it use Apollo's own parameter names (without the [] suffix), so nothing is
translated silently. See README for the full schema.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from util import norm_domain

# Apollo organization search params we accept (docs.apollo.io/reference/organization-search).
LIST_KEYS = {
    "q_organization_domains_list", "not_organization_websites_list",
    "organization_num_employees_ranges", "organization_locations", "organization_not_locations",
    "organization_industry_tag_ids", "organization_not_industry_tag_ids", "organization_industries",
    "organization_naics_codes", "not_organization_naics_codes",
    "organization_sic_codes", "not_organization_sic_codes",
    "currently_using_any_of_technology_uids", "q_organization_keyword_tags",
    "q_not_organization_keyword_tags", "organization_ids", "q_organization_job_titles",
    "organization_job_locations", "lookalike_organization_ids",
}
RANGE_KEYS = {
    "revenue_range", "latest_funding_amount_range", "total_funding_range",
    "latest_funding_date_range", "organization_num_jobs_range",
    "organization_job_posted_at_range", "organization_headcount_growth_range",
}
SCALAR_KEYS = {"q_organization_name", "organization_headcount_growth_past_n_months"}
ALL_KEYS = LIST_KEYS | RANGE_KEYS | SCALAR_KEYS
LIMITS = {"q_not_organization_keyword_tags": 150, "q_organization_domains_list": 1000,
          "lookalike_organization_ids": 5}


class BriefError(ValueError):
    pass


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:48] or "idea"


def load(path):
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BriefError("brief not found: %s" % p)
    except json.JSONDecodeError as e:
        raise BriefError("brief.json is not valid JSON: %s" % e)


def sha(brief):
    """Hash of the parts that change what Apollo returns (not the notes)."""
    keep = {"apollo": brief.get("apollo"), "exclusions": brief.get("exclusions")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:12]


def _check_filters(f, where, errors):
    for k, v in (f or {}).items():
        if k not in ALL_KEYS:
            errors.append("%s: unknown Apollo filter '%s'" % (where, k))
            continue
        if k in LIST_KEYS:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errors.append("%s.%s must be a list of strings" % (where, k))
            elif k in LIMITS and len(v) > LIMITS[k]:
                errors.append("%s.%s has %d items, Apollo max is %d" % (where, k, len(v), LIMITS[k]))
        elif k in RANGE_KEYS:
            if not isinstance(v, dict) or not (set(v) <= {"min", "max"}):
                errors.append("%s.%s must be an object with min and/or max" % (where, k))
        if k == "organization_num_employees_ranges" and isinstance(v, list):
            for r in v:
                if not re.fullmatch(r"\d+,\d+", r):
                    errors.append("%s: employee range '%s' must look like 25,1000" % (where, r))
        if k == "organization_headcount_growth_past_n_months" and v not in (6, 12, 24):
            errors.append("%s.%s must be 6, 12 or 24" % (where, k))


def validate(brief):
    """Return a list of problems (empty list means OK)."""
    errors = []
    idea = brief.get("idea") or {}
    if not idea.get("name"):
        errors.append("idea.name is required")
    if not idea.get("slug"):
        errors.append("idea.slug is required")
    elif slugify(idea["slug"]) != idea["slug"]:
        errors.append("idea.slug must be lowercase-hyphen: %s" % slugify(idea["slug"]))
    ap = brief.get("apollo") or {}
    base = ap.get("base") or {}
    sets = ap.get("filter_sets") or []
    _check_filters(base, "apollo.base", errors)
    if not sets:
        errors.append("apollo.filter_sets needs at least one set (use one set with a label if there is a single segment)")
    labels = set()
    for i, s in enumerate(sets):
        lab = s.get("label")
        if not lab:
            errors.append("apollo.filter_sets[%d].label is required" % i)
        elif lab in labels:
            errors.append("duplicate filter set label '%s'" % lab)
        labels.add(lab)
        _check_filters({k: v for k, v in s.items() if k != "label"}, "apollo.filter_sets[%d]" % i, errors)
        merged = merge_filters(base, s)
        if not merged.get("organization_locations"):
            errors.append("filter set '%s': organization_locations missing (countries are a hard filter)" % lab)
        if not merged.get("organization_num_employees_ranges"):
            errors.append("filter set '%s': organization_num_employees_ranges missing (size band is a hard filter)" % lab)
    ppl = brief.get("people") or {}
    for t in ("T1", "T2"):
        if not (ppl.get(t) or {}).get("titles"):
            errors.append("people.%s.titles is required (with synonyms)" % t)
    try:
        people_caps(brief)
    except BriefError as e:
        errors.append(str(e))
    import signals as signalsmod
    errors.extend(signalsmod.validate(brief.get("signals")))
    pil = brief.get("pilot")
    if pil is not None:
        if not isinstance(pil, dict):
            errors.append("pilot must be an object")
        else:
            import config
            lo, hi = config.get("pilot.min_size", 10), config.get("pilot.max_size", 20)
            for k in ("accounts_size", "people_size"):
                v = pil.get(k)
                if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi):
                    errors.append("pilot.%s must be a whole number from %d to %d" % (k, lo, hi))
    return errors


def merge_filters(base, fset):
    """Set keys override base keys. The label is dropped."""
    out = {k: v for k, v in (base or {}).items() if v not in (None, [], {})}
    for k, v in fset.items():
        if k == "label":
            continue
        out[k] = v
    return out


def filter_sets(brief):
    """List of (label, filters) ready for the Apollo client."""
    ap = brief.get("apollo") or {}
    return [(s["label"], merge_filters(ap.get("base"), s)) for s in ap.get("filter_sets", [])]


def excluded_domains(brief):
    return {norm_domain(d) for d in ((brief.get("exclusions") or {}).get("domains") or []) if norm_domain(d)}


def to_params(filters, page=None, per_page=None):
    """Filters dict -> list of (key, value) tuples using Apollo's bracket syntax."""
    params = []
    for k, v in filters.items():
        if v in (None, [], {}):
            continue
        if k in LIST_KEYS:
            for x in v:
                params.append((k + "[]", str(x)))
        elif k in RANGE_KEYS:
            for sub in ("min", "max"):
                if v.get(sub) is not None:
                    params.append(("%s[%s]" % (k, sub), str(v[sub])))
        else:
            params.append((k, str(v)))
    if page is not None:
        params.append(("page", str(page)))
    if per_page is not None:
        params.append(("per_page", str(per_page)))
    return params


def to_rows(brief):
    """Flatten a brief into [section, key, value, note] rows for the '1 Brief' tab (key is unique)."""
    rows = []

    def add(section, key, value, note=""):
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        rows.append({"section": section, "key": "%s.%s" % (section, key), "value": value, "note": note})

    idea = brief.get("idea") or {}
    for k in ("name", "slug", "one_liner", "memo_source", "memo_url", "test"):
        if k in idea:
            add("idea", k, idea[k])
    icp = brief.get("icp") or {}
    if icp.get("summary"):
        add("icp", "summary", icp["summary"])
    for i, h in enumerate(icp.get("hard") or []):
        add("icp", "hard_%d" % (i + 1), h.get("criterion", h) if isinstance(h, dict) else h,
            h.get("reason", "") if isinstance(h, dict) else "")
    for i, h in enumerate(icp.get("soft") or []):
        add("icp", "soft_%d" % (i + 1), h.get("criterion", h) if isinstance(h, dict) else h,
            h.get("reason", "") if isinstance(h, dict) else "")
    ap = brief.get("apollo") or {}
    if ap.get("base"):
        add("apollo", "base", ap["base"], "applies to every filter set")
    for s in ap.get("filter_sets") or []:
        add("apollo", "set:%s" % s.get("label"), {k: v for k, v in s.items() if k != "label"},
            "overrides base for this set")
    ppl = brief.get("people") or {}
    for t in ("T1", "T2"):
        if ppl.get(t):
            add("people", "%s_titles" % t, ppl[t].get("titles"), "seniorities: %s" % ",".join(ppl[t].get("seniorities") or []))
    caps = ppl.get("caps") or {}
    if caps:
        add("people", "caps", caps, "max people per company per tier")
    tr = brief.get("tier_rules") or {}
    for t in ("T1", "T2"):
        if tr.get(t):
            add("tier_rules", t, tr[t])
    ex = brief.get("exclusions") or {}
    for k, v in ex.items():
        add("exclusions", k, v)
    q = brief.get("qualify") or {}
    for k, v in q.items():
        add("qualify", k, v)
    for i, d in enumerate(brief.get("decisions") or []):
        add("decisions", str(i + 1), "%s: %s" % (d.get("topic"), d.get("decision")), d.get("type", ""))
    vol = brief.get("volume") or {}
    if vol:
        add("volume", "settings", vol)
    for i, sg in enumerate(brief.get("signals") or []):
        if isinstance(sg, dict):
            if sg.get("source_field"):
                what = "%s %s %s" % (sg.get("source_field"), sg.get("op"), sg.get("value"))
            else:
                what = sg.get("description", "")
            add("signals", str(i + 1), "%s: %s" % (sg.get("name"), what), sg.get("strength", ""))
    if brief.get("pilot"):
        add("pilot", "settings", brief["pilot"])
    return rows


# ---- people caps (one place) ----------------------------------------------------------------
def people_caps(brief=None):
    """Max people per company per tier. Precedence: brief.people.caps overrides config.people_caps.
    Always returns {"T1": int, "T2": int}; invalid values raise BriefError."""
    import config
    caps = {"T1": 5, "T2": 3}
    caps.update({k: v for k, v in (config.get("people_caps") or {}).items() if k in ("T1", "T2")})
    caps.update({k: v for k, v in (((brief or {}).get("people") or {}).get("caps") or {}).items() if k in ("T1", "T2")})
    for k, v in caps.items():
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise BriefError("people cap %s must be a whole number of 0 or more, got %r" % (k, v))
    return caps
