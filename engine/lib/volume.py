"""Volume math: how many accounts must we pull to reach the people targets.

accounts_needed = target_emails / (qualify_pass_rate * people_found_rate
                                   * avg_people_per_account * email_valid_rate)
The assumptions live in config.json (volume_assumptions) and can be overridden per brief.
"""
from __future__ import annotations

import math

import config


def assumptions(brief=None):
    a = dict(config.get("volume_assumptions", {}))
    a.update(((brief or {}).get("volume") or {}).get("assumptions") or {})
    return {k: v for k, v in a.items() if not k.startswith("_")}


def accounts_needed(target_emails, a):
    per_account = (a["qualify_pass_rate"] * a["people_found_rate"]
                   * a["avg_people_per_account"] * a["email_valid_rate"])
    if per_account <= 0:
        raise ValueError("volume assumptions produce zero yield")
    return int(math.ceil(target_emails / per_account))


def sizing(brief=None):
    """Return dict with accounts needed for the low/high email target and the LinkedIn target."""
    a = assumptions(brief)
    t = dict(config.get("targets", {}))
    t.update(((brief or {}).get("volume") or {}).get("targets") or {})
    lo, hi = t["verified_emails_min"], t["verified_emails_max"]
    li = t["linkedin_active_min"]
    li_per_account = (a["qualify_pass_rate"] * a["people_found_rate"]
                      * a["avg_people_per_account"] * a["linkedin_active_rate"])
    return {
        "assumptions": a,
        "targets": t,
        "accounts_for_email_min": accounts_needed(lo, a),
        "accounts_for_email_max": accounts_needed(hi, a),
        "accounts_for_linkedin_min": int(math.ceil(li / li_per_account)),
    }
