"""Google Sheet tab names and headers (one sheet per idea). Edit headers here, not in scripts.

Tab names follow PLAN.md. Rows are written RAW (no formula interpretation). Phase 1 uses tabs
1, 2 and 9, phase 2 fills 3 to 7. Existing sheets are migrated with SheetClient.ensure_schema().
"""
from __future__ import annotations

TAB_BRIEF = "1 Brief"
TAB_ACCOUNTS = "2 Accounts"
TAB_NO_PEOPLE = "3 Accounts: No People"
TAB_PEOPLE = "4 People"
TAB_READY_LI = "5 Ready: LinkedIn"
TAB_READY_EMAIL = "6 Ready: Email"
TAB_READY_CALLS = "7 Ready: Calls"
TAB_COPY = "8 Copy"
TAB_RUNLOG = "9 Run Log"

ACCOUNT_BASE_COLS = ["org_id", "domain", "name", "website", "linkedin_url", "country", "state", "city",
                     "filter_location", "revenue", "founded_year", "naics", "sic", "phone", "apollo_crm",
                     "source_filters", "added_at"]
QUALIFY_COLS = ["website_status", "qualified", "confidence", "flag", "reason", "qualified_at"]
# Signals (headcounts from Apollo organization enrichment) and pilot review columns. They come AFTER the qualify columns
# so the positional append of new rows keeps working on sheets created before these columns existed (add_columns appends
# missing headers at the end, in this order). Extra departments a brief asks for are added as `dept_<key>` columns.
SIGNAL_COLS = ["employees", "engineering", "operations", "sales", "information_technology", "finance", "marketing",
               "human_resources", "signals_status", "signals_at"]
PILOT_ACCOUNT_COLS = ["pilot", "pilot_review", "pilot_note", "is_seed"]
ACCOUNT_COLS = ACCOUNT_BASE_COLS + QUALIFY_COLS + SIGNAL_COLS + PILOT_ACCOUNT_COLS

# 4 People. One row per Apollo person id. Rows are never deleted; later stages fill their columns.
#  search stage:  person_id .. title, title_rank, cap_status (candidate|over_cap|selected|not_tiered), source, added_at
#  tier stage:    tier (T1|T2|X), tier_reason, cap_status
#  enrich stage:  first_name, last_name, seniority, linkedin_url, email, email_status (Apollo's own), enrich_status
#  verify stage:  email_source, mv_result, mv_subresult, email_verdict, waterfall_needed
#  activity:      activity_status (raw checker value), linkedin_active (yes|no|unknown), linkedin_checked_at
#  phones:        phone, phone_status, phone_source
#  channels:      channels (linkedin+email+call), empty when exclusion_reason is set
#  exclusions:    exclusion_reason (garden leave, retired, ..., from Apollo employment data and the activity checker)
#  pilot gate:    pilot (yes for the pilot people), pilot_review (approve|reject, typed in the sheet or recorded from chat), pilot_note
PEOPLE_COLS = ["person_id", "org_id", "domain", "company", "first_name", "last_name", "title", "seniority",
               "linkedin_url", "email", "email_status", "phone", "country", "tier", "tier_reason", "source",
               "added_at", "title_rank", "cap_status", "enrich_status", "email_source", "mv_result", "mv_subresult",
               "email_verdict", "waterfall_needed", "activity_status", "linkedin_active", "linkedin_checked_at",
               "phone_status", "phone_source", "channels", "exclusion_reason", "pilot", "pilot_review", "pilot_note"]
NO_PEOPLE_REASONS = ("no_people_found", "search_error")

TABS = {
    TAB_BRIEF: ["section", "key", "value", "note"],
    TAB_ACCOUNTS: ACCOUNT_COLS,
    TAB_NO_PEOPLE: ["org_id", "domain", "name", "reason", "checked_at"],
    TAB_PEOPLE: PEOPLE_COLS,
    TAB_READY_LI: ["person_id", "tier", "first_name", "last_name", "title", "company", "linkedin_url", "linkedin_active",
                   "email", "country", "domain", "status"],
    TAB_READY_EMAIL: ["person_id", "tier", "first_name", "last_name", "title", "company", "email", "email_verdict",
                      "linkedin_url", "country", "domain", "status"],
    TAB_READY_CALLS: ["person_id", "first_name", "last_name", "title", "company", "phone", "tier", "country",
                      "linkedin_url", "email", "idea", "call_notes", "status"],
    TAB_COPY: ["channel", "tier", "step", "variant", "subject", "body", "status", "notes", "copy_id", "sender", "words"],
    TAB_RUNLOG: ["timestamp", "stage", "event", "detail", "counts", "apollo_credits", "run_by"],
}

TAB_ORDER = list(TABS)

# Qualify flag values (column `flag`). Rows are never deleted, only flagged.
FLAG_KEEP = "keep"          # qualified and confidence >= min_confidence
FLAG_REVIEW = "review"      # qualified but low confidence: keep in pool, human may look
FLAG_DROP = "drop"          # not qualified (row stays, later stages skip it)
FLAG_DEAD = "dead_site"     # website did not load
FLAG_PARKED = "parked_site" # parked, suspended or empty page
FLAG_ERROR = "error"        # scoring failed, will be retried
POOL_FLAGS = (FLAG_KEEP, FLAG_REVIEW)  # companies that move on to /iv-people

# Tier values (column `tier`). X means "not a buyer for this idea": the row stays, no credits are spent on it.
TIER_T1, TIER_T2, TIER_X = "T1", "T2", "X"
TIERS = (TIER_T1, TIER_T2, TIER_X)
# cap_status values
CAP_CANDIDATE = "candidate"    # found by search, inside the tiering pool, not tiered yet
CAP_SELECTED = "selected"      # tiered and inside the per-company cap: gets enrichment
CAP_OVER = "over_cap"          # tiered but beyond the cap, or beyond the tiering pool
CAP_NOT_TIERED = "not_tiered"  # tier X
CAP_DUP = "duplicate"          # same person as a better-ranked row (same LinkedIn URL or email) found after enrichment
