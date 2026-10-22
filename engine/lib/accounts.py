"""Stage 2 logic: Apollo organization search from brief.json -> accounts.csv + "2 Accounts" tab.

Flow: dry_run() counts matches (1 credit per count call) and writes accounts.plan.json;
execute() pages through the plan leaf by leaf, streaming rows and a ledger so a crash resumes at
the right page, then dedupes (org id, then domain), applies the brief's excluded domains, writes
accounts.csv atomically and appends NEW rows to the sheet. Every company is kept.
"""
from __future__ import annotations

import hashlib
import json
import math
import os

import apollo
import brief as briefmod
import config
import schema
import volume
from run import RunError
from util import (append_jsonl, norm_domain, now_iso, read_csv, read_json, read_jsonl, write_csv, write_json)


def _leaf_key(filters):
    return hashlib.sha1(json.dumps(filters, sort_keys=True).encode()).hexdigest()[:10]


def plan_path(run):
    return run.dir / "accounts.plan.json"


def dry_run(run, brief, client=None):
    """Count-first sizing for every filter set. Returns the plan dict (also saved)."""
    client = client or apollo.ApolloClient(usage_log=run.usage_log, label="accounts-dry-run")
    per_page = config.get("apollo.per_page")
    plan = {"brief_sha": briefmod.sha(brief), "created_at": now_iso(), "sets": []}
    for label, filters in briefmod.filter_sets(brief):
        client.label = "plan:" + label
        leaves = client.plan(filters)
        total = sum(l["total"] for l in leaves)
        plan["sets"].append({
            "label": label, "total": total, "sharded": len(leaves) > 1,
            "truncated": any(l["truncated"] for l in leaves),
            "est_pages": sum(min(int(math.ceil(l["total"] / float(per_page))), config.get("apollo.max_pages"))
                             for l in leaves),
            "leaves": [{"key": _leaf_key(l["filters"]), "filters": l["filters"], "total": l["total"],
                        "truncated": l["truncated"]} for l in leaves]})
    plan["total_matches"] = sum(s["total"] for s in plan["sets"])
    plan["est_credits"] = sum(s["est_pages"] for s in plan["sets"]) * config.get("apollo.credits_per_org_search_page")
    plan["sizing"] = volume.sizing(brief)
    write_json(plan_path(run), plan)
    run.log("accounts", "dry_run", "matches=%d est_credits=%d" % (plan["total_matches"], plan["est_credits"]),
            {"matches": plan["total_matches"], "est_credits": plan["est_credits"]})
    return plan


def format_plan(plan):
    lines = ["Apollo company search plan (matches overlap between sets, so unique accounts will be fewer)", ""]
    for s in plan["sets"]:
        lines.append("  %-28s %7d matches  ~%d pages%s%s" % (
            s["label"], s["total"], s["est_pages"], "  (sharded to stay under the 50k cap)" if s["sharded"] else "",
            "  WARNING: truncated at the cap" if s["truncated"] else ""))
    lines += ["", "  Total matches: %d   Estimated Apollo credits: %d (1 credit per 100 companies)"
              % (plan["total_matches"], plan["est_credits"])]
    sz = plan["sizing"]
    lines.append("  Volume math wants about %d to %d accounts for %d to %d verified emails "
                 "and %d for %d LinkedIn-active people."
                 % (sz["accounts_for_email_min"], sz["accounts_for_email_max"],
                    sz["targets"]["verified_emails_min"], sz["targets"]["verified_emails_max"],
                    sz["accounts_for_linkedin_min"], sz["targets"]["linkedin_active_min"]))
    return "\n".join(lines)


def _archive(run, *paths):
    stamp = now_iso().replace(":", "")
    for p in paths:
        if p.exists():
            os.replace(p, p.with_name(p.name + ".old-" + stamp))


def finalize_csv(run, brief):
    """Dedupe the stream into accounts.csv (and accounts.excluded.csv). Returns (kept, dups, excluded)."""
    excl = briefmod.excluded_domains(brief)
    seen_id, seen_dom, kept, excluded, dups = {}, {}, [], [], 0
    for r in read_jsonl(run.accounts_stream):
        oid, dom = r.get("org_id"), r.get("domain")
        key = oid or ("dom:" + dom)
        hit = seen_id.get(key) or (seen_dom.get(dom) if dom else None)
        if hit is not None:
            dups += 1
            labs = set(hit["source_filters"].split("+")) | set(r["source_filters"].split("+"))
            hit["source_filters"] = "+".join(sorted(labs))
            continue
        if dom and dom in excl:
            excluded.append(r)
            continue
        seen_id[key] = r
        if dom:
            seen_dom[dom] = r
        kept.append(r)
    write_csv(run.accounts_csv, kept, schema.ACCOUNT_BASE_COLS)
    if excluded:
        write_csv(run.dir / "accounts.excluded.csv", excluded, schema.ACCOUNT_BASE_COLS)
    return kept, dups, excluded


def push_new_to_sheet(run, rows):
    """Append only accounts whose org_id is not already on the tab (never touches qualify columns)."""
    import sheet as sheetmod
    sc = sheetmod.SheetClient()
    sid = run.sheet_id()
    if not sid:
        raise RunError("no sheet for this run yet (run /iv-brief first)")
    have = {str(r.get("org_id")) for r in sc.read_records(sid, schema.TAB_ACCOUNTS)}
    new = [r for r in rows if r["org_id"] not in have]
    if new:
        sc.add_columns(sid, schema.TAB_ACCOUNTS, schema.ACCOUNT_COLS)  # signal and pilot columns on sheets made before them
        sc.append_records(sid, schema.TAB_ACCOUNTS, new, schema.ACCOUNT_COLS)
    return len(new), len(rows) - len(new)


def execute(run, brief, limit=None, accept_brief_change=False, client=None, push=True):
    client = client or apollo.ApolloClient(usage_log=run.usage_log, label="accounts")
    sha = briefmod.sha(brief)
    ledger = read_json(run.ledger_path, None)
    st = run.load_state()
    if ledger and ledger.get("brief_sha") not in (None, sha):
        if not accept_brief_change:
            raise RunError("brief.json changed since accounts were pulled (Apollo filters or exclusions). "
                           "Re-run with --accept-brief-change to archive the old pull and start fresh.")
        _archive(run, run.ledger_path, run.accounts_stream, plan_path(run), run.accounts_csv)
        ledger = None
    per_page = config.get("apollo.per_page")
    added_at = now_iso()

    if limit:  # small test pull: first filter sets in order, no counting or sharding
        have = len(read_jsonl(run.accounts_stream))
        if have >= limit:
            print("already have %d streamed rows (limit %d), nothing to pull" % (have, limit))
        else:
            if not ledger:
                ledger = {"brief_sha": sha, "limit": limit, "complete": False, "leaves": {}}
                write_json(run.ledger_path, ledger)
            got = have
            sets = briefmod.filter_sets(brief)
            quota = int(math.ceil(limit / float(len(sets))))  # spread a test pull across the segments
            for label, filters in sets:
                if got >= limit:
                    break
                client.label = "limit-test:" + label
                take = min(per_page, quota, limit - got)
                res = client.org_page(filters, 1, take)
                rows = res["orgs"][:take]
                for r in rows:
                    r["source_filters"], r["added_at"] = label, added_at
                    append_jsonl(run.accounts_stream, r)
                got += len(rows)
                print("  %s: took %d of %d matches" % (label, len(rows), res["total_entries"]))
        kept, dups, excluded = finalize_csv(run, brief)
        run.log("accounts", "limit_test", "limit=%d rows=%d" % (limit, len(kept)), {"rows": len(kept)})
    else:
        plan = read_json(plan_path(run), None)
        if not plan or plan.get("brief_sha") != sha:
            print("no current plan, counting first (1 credit per count)...")
            plan = dry_run(run, brief, client)
        if not ledger or ledger.get("limit"):
            ledger = {"brief_sha": sha, "complete": False, "leaves": {}}
        run.update_state(brief_sha=sha)
        for s in plan["sets"]:
            for leaf in s["leaves"]:
                key = leaf["key"]
                ent = ledger["leaves"].setdefault(key, {"label": s["label"], "total": leaf["total"],
                                                         "pages_done": 0, "done": False})
                if ent["done"]:
                    continue
                client.label = "pull:" + s["label"]

                def on_page(page, rows, ent=ent, label=s["label"]):
                    for r in rows:
                        r["source_filters"], r["added_at"] = label, added_at
                        append_jsonl(run.accounts_stream, r)
                    ent["pages_done"] = page
                    write_json(run.ledger_path, ledger)

                for _ in client.iter_leaf(leaf["filters"], leaf["total"], start_page=ent["pages_done"] + 1,
                                          per_page=per_page, on_page=on_page):
                    pass
                ent["done"] = True
                write_json(run.ledger_path, ledger)
                print("  %s shard %s: %d matches pulled" % (s["label"], key, leaf["total"]))
        ledger["complete"] = True
        write_json(run.ledger_path, ledger)
        kept, dups, excluded = finalize_csv(run, brief)
        run.log("accounts", "pull_complete", "accounts=%d dups=%d excluded=%d" % (len(kept), dups, len(excluded)),
                {"accounts": len(kept), "duplicates": dups, "excluded": len(excluded)})
    if push:
        n_new, n_have = push_new_to_sheet(run, kept)
        print("sheet '%s': %d new rows appended, %d already there" % (schema.TAB_ACCOUNTS, n_new, n_have))
    return {"accounts": len(kept), "duplicates": dups, "excluded": len(excluded),
            "complete": bool(not limit)}
