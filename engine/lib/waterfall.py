"""Waterfall hooks. Prospeo and Amplemarket are NOT set up yet, so nothing here calls them.

What exists now: a clear list of who needs a second source (people.csv column `waterfall_needed`) and one
provider interface, so adding a provider later is one small class, not a refactor.

  email_missing / email_invalid / email_unknown / email_role_address   -> find another email, then verify it
  catch_all_secondary_verify                                          -> a second verifier decides catch_all
  phone (T1 without a phone after Apollo)                              -> phone_waterfall

To add a provider: subclass Provider, fill find_email / find_phone / verify_catch_all, register it in PROVIDERS and
set `enabled` in config.json (waterfall.providers). Results must be written the same way Apollo's are: an
enrich/enrich.jsonl record (email, linkedin_url, status matched) with `email_source` set to the provider, then the
normal MillionVerifier pass runs on it. Keys for Prospeo and Amplemarket are not used until a provider is enabled
(an AMPLEMARKET_API_KEY exists in <repo>/.env, deliberately unused).
"""
from __future__ import annotations

import people as peoplemod
import schema
from util import write_csv

REASONS = ("email_missing", "email_invalid", "email_unknown", "email_role_address", "catch_all_secondary_verify")


class ProviderNotSetUp(RuntimeError):
    pass


class Provider:
    name = "base"
    enabled = False

    def find_email(self, person):
        raise ProviderNotSetUp("%s is not set up" % self.name)

    def find_phone(self, person):
        raise ProviderNotSetUp("%s is not set up" % self.name)

    def verify_catch_all(self, email):
        raise ProviderNotSetUp("%s is not set up" % self.name)


class Prospeo(Provider):
    name = "prospeo"


class Amplemarket(Provider):
    name = "amplemarket"


PROVIDERS = {"prospeo": Prospeo(), "amplemarket": Amplemarket()}


def needed(rows):
    """People (selected) that need a second source, with the reason. Pure."""
    out = []
    for r in rows:
        if r["cap_status"] != schema.CAP_SELECTED:
            continue
        reason = r.get("waterfall_needed") or ""
        if not reason and r.get("tier") == schema.TIER_T1 and r.get("phone_status") in ("none", "not_available"):
            reason = "phone_missing"
        if reason:
            out.append({"person_id": r["person_id"], "company": r["company"], "domain": r["domain"],
                        "first_name": r["first_name"], "last_name": r["last_name"], "title": r["title"],
                        "linkedin_url": r["linkedin_url"], "tier": r["tier"], "reason": reason})
    return out


def write_list(run, rows):
    """Write enrich/waterfall-needed.csv (the hand-off list for Prospeo or Amplemarket later)."""
    f = peoplemod.Files(run)
    items = needed(rows)
    write_csv(f.enrich / "waterfall-needed.csv", items,
              ["person_id", "company", "domain", "first_name", "last_name", "title", "linkedin_url", "tier", "reason"])
    by = {}
    for i in items:
        by[i["reason"]] = by.get(i["reason"], 0) + 1
    return by
