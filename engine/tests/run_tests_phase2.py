"""Phase 2 offline tests (no network, no credits). Run together with Phase 1:  python3 -I tests/run_tests.py
Imported by run_tests.py (which sets the temp lists dir, the zero Apollo interval and a fake key first)."""
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "workflows"))
import config  # noqa: E402

import activity as amod  # noqa: E402
import apollo  # noqa: E402
import brief as briefmod  # noqa: E402
import enrich as emod  # noqa: E402
import n8n  # noqa: E402
import people as pm  # noqa: E402
import phones as phmod  # noqa: E402
import quality  # noqa: E402
import ready as rdy  # noqa: E402
import schema  # noqa: E402
import sheet as sheetmod  # noqa: E402
import stages  # noqa: E402
import tier as tmod  # noqa: E402
import verify as vmod  # noqa: E402
import waterfall  # noqa: E402
from run import Run  # noqa: E402
from util import append_jsonl, read_csv, read_jsonl, write_csv, write_json  # noqa: E402

BRIEF = {"idea": {"name": "Test Idea", "slug": "x", "one_liner": "ideal", "test": False},
         "apollo": {"base": {"organization_locations": ["United Kingdom"], "organization_num_employees_ranges": ["25,1000"]},
                    "filter_sets": [{"label": "a", "q_organization_keyword_tags": ["wholesaler"]}]},
         "people": {"T1": {"titles": ["Chief Operating Officer", "COO", "Owner", "Managing Director"], "seniorities": ["c_suite", "owner"]},
                    "T2": {"titles": ["Head of Compliance", "Quality Manager"], "seniorities": ["head", "manager"]},
                    "caps": {"T1": 2, "T2": 1}},
         "tier_rules": {"T1": "budget holder", "T2": "compliance owner"}}


def make_run(slug, brief=None, sheet=True):
    run = Run.create(slug, "2026-03-01")
    write_json(run.brief_path, brief or BRIEF)
    if sheet:
        write_json(run.sheet_path, {"sheet_id": "S1", "url": "http://x"})
    return run


def qualified(run, orgs):
    """orgs: [(org_id, domain, name, flag)] -> accounts.csv + qualify/qualified.csv."""
    rows = [{"org_id": o, "domain": d, "name": n, "country": "UK", "flag": f, "confidence": "0.9"} for o, d, n, f in orgs]
    write_csv(run.accounts_csv, rows, schema.ACCOUNT_BASE_COLS)
    write_csv(run.qdir / "qualified.csv", rows, schema.ACCOUNT_COLS)


def person(pid, oid, title, name="Ann", **kw):
    d = {"id": pid, "first_name": name, "last_name_obfuscated": "Sm***h", "title": title, "has_email": True,
         "has_direct_phone": "Yes"}
    d.update(kw)
    return d


class FakePeopleApollo:
    """Transport for mixed_people/api_search keyed by organization id; also answers bulk_match."""
    def __init__(self, by_org=None, fail_orgs=(), hour_left="5000"):
        self.by_org, self.fail_orgs, self.calls, self.hour_left = by_org or {}, set(fail_orgs), [], hour_left
        self.bulk = []

    def __call__(self, method, url, headers, data, timeout):
        from urllib.parse import parse_qs, urlparse
        u = urlparse(url)
        self.calls.append(url)
        rh = {"x-hourly-requests-left": self.hour_left, "x-minute-requests-left": "150"}
        if u.path.endswith("/mixed_people/api_search"):
            q = parse_qs(u.query)
            oid = (q.get("organization_ids[]") or [""])[0]
            if oid in self.fail_orgs:
                return 500, rh, b"boom"
            ppl = self.by_org.get(oid, [])
            return 200, rh, json.dumps({"people": ppl, "total_entries": len(ppl)}).encode()
        if u.path.endswith("/people/bulk_match"):
            body = json.loads(data)
            self.bulk.append((parse_qs(u.query), body))
            matches, credits = [], 0
            for d in body["details"]:
                if d["id"].startswith("nomatch"):
                    matches.append(None)
                    continue
                credits += 1
                matches.append({"id": d["id"], "first_name": d["first_name"], "last_name": "Smith",
                                "title": "Owner", "linkedin_url": "http://www.linkedin.com/in/%s" % d["id"],
                                "email": "email_not_unlocked@domain.com" if d["id"].startswith("noemail") else "%s@%s" % (d["id"], d["domain"]),
                                "email_status": "verified", "country": "United Kingdom", "seniority": "owner",
                                "organization": {"name": d["organization_name"], "primary_domain": d["domain"]}})
            out = {"status": "success", "matches": matches, "credits_consumed": credits + 0.0,
                   "missing_records": sum(1 for m in matches if m is None), "request_id": -42}
            if "reveal_phone_number" in u.query:
                out["phone_enrichment"] = {"status": "pending", "request_id": -42}
                out["credits_consumed"] = credits * 8.0
            return 200, rh, json.dumps(out).encode()
        return 404, rh, b"{}"


def client(tr, run=None):
    return apollo.ApolloClient(api_key="k", transport=tr, sleep=lambda s: None, usage_log=(run.usage_log if run else None))


class TestCapsAndTitles(unittest.TestCase):
    def test_caps_precedence(self):
        self.assertEqual(briefmod.people_caps({}), {"T1": 5, "T2": 3})  # config default
        self.assertEqual(briefmod.people_caps(BRIEF), {"T1": 2, "T2": 1})  # brief overrides
        self.assertEqual(briefmod.people_caps({"people": {"caps": {"T2": 0}}}), {"T1": 5, "T2": 0})  # partial override
        with self.assertRaises(briefmod.BriefError):
            briefmod.people_caps({"people": {"caps": {"T1": -1}}})
        with self.assertRaises(briefmod.BriefError):
            briefmod.people_caps({"people": {"caps": {"T1": "5"}}})
        b = json.loads(json.dumps(BRIEF))
        b["people"]["caps"]["T1"] = 1.5
        self.assertTrue(any("cap" in e for e in briefmod.validate(b)))

    def test_title_rank_order_and_hint(self):
        r = lambda t: pm.title_rank(t, BRIEF)
        self.assertEqual(r("Chief Operating Officer"), 0)
        self.assertLess(r("COO"), r("Owner"))
        self.assertLess(r("Owner"), r("Managing Director"))
        self.assertGreater(r("Quality Manager"), 99)  # T2 starts at 100
        self.assertEqual(r("Gardener"), 1000)
        self.assertEqual(r("Managing Director"), 6)  # exact beats contained
        self.assertEqual(r("Co-Owner"), 5)  # word-boundary containment is one step worse than exact
        self.assertEqual(pm.title_hint(0), "T1")
        self.assertEqual(pm.title_hint(101), "T2")
        self.assertEqual(pm.title_hint(1000), "")

    def test_apply_caps_after_tiering(self):
        rows = [{"person_id": "p%d" % i, "org_id": "o1", "title_rank": i} for i in range(6)]
        tiers = {"p0": "T1", "p1": "T2", "p2": "T1", "p3": "T1", "p4": "X", "p5": "T2"}
        cap = pm.apply_caps(rows, {"T1": 2, "T2": 1}, tiers, pool_size=10)
        self.assertEqual(cap["p0"], "selected")
        self.assertEqual(cap["p2"], "selected")
        self.assertEqual(cap["p3"], "over_cap")  # third T1, best titles stay
        self.assertEqual(cap["p1"], "selected")
        self.assertEqual(cap["p5"], "over_cap")
        self.assertEqual(cap["p4"], "not_tiered")

    def test_apply_caps_pool_and_untiered_and_skipped(self):
        rows = [{"person_id": "p%d" % i, "org_id": "o1", "title_rank": 1000 - i} for i in range(5)]
        cap = pm.apply_caps(rows, {"T1": 1, "T2": 1}, {}, pool_size=3)
        self.assertEqual(sorted(cap.values()), ["candidate"] * 3 + ["over_cap"] * 2)
        cap = pm.apply_caps(rows, {"T1": 1, "T2": 1}, {}, tier_skipped=True, pool_size=3)
        self.assertEqual(sorted(cap.values()), ["over_cap"] * 3 + ["selected"] * 2)  # T1 cap + T2 cap, by title priority
        # caps of zero select nobody
        cap = pm.apply_caps(rows, {"T1": 0, "T2": 0}, {"p0": "T1"}, pool_size=3)
        self.assertEqual(cap["p0"], "over_cap")
        # per company, not global
        rows2 = rows + [{"person_id": "q1", "org_id": "o2", "title_rank": 0}]
        self.assertEqual(pm.apply_caps(rows2, {"T1": 1, "T2": 1}, {"q1": "T1"}, pool_size=3)["q1"], "selected")

    def test_search_query_union_and_hash(self):
        q = pm.search_query(BRIEF)
        self.assertEqual(q["titles"][:2], ["Chief Operating Officer", "COO"])
        self.assertIn("manager", q["seniorities"])
        self.assertIn("c_suite", q["seniorities"])
        b2 = json.loads(json.dumps(BRIEF))
        b2["people"]["T2"]["titles"].append("Head of Quality")
        self.assertNotEqual(pm.search_query(b2)["sha"], q["sha"])


class TestVerdictAndChannels(unittest.TestCase):
    def test_email_verdict(self):
        v = pm.email_verdict
        self.assertEqual(v("", None), ("missing", "email_missing"))
        self.assertEqual(v("a@b.com", None), ("unverified", ""))
        self.assertEqual(v("a@b.com", {"result": "ok"}), ("valid", ""))
        self.assertEqual(v("a@b.com", {"result": "catch_all"}), ("catch_all", "catch_all_secondary_verify"))
        self.assertEqual(v("a@b.com", {"result": "invalid"})[0], "invalid")
        self.assertEqual(v("a@b.com", {"result": "disposable"})[0], "invalid")
        self.assertEqual(v("a@b.com", {"result": "unknown"}), ("unknown", "email_unknown"))
        self.assertEqual(v("a@b.com", {"result": "error"}), ("error", ""))
        self.assertEqual(v("info@b.com", {"result": "ok"})[0], "role")  # only a person's address is sendable

    def test_linkedin_active_value(self):
        p = {"linkedin_url": "u"}
        self.assertEqual(pm.linkedin_active_value(p, {"activity_status": "Active"}), "yes")
        self.assertEqual(pm.linkedin_active_value(p, {"activity_status": "Inactive"}), "no")
        self.assertEqual(pm.linkedin_active_value(p, {"activity_status": "Shell"}), "no")
        self.assertEqual(pm.linkedin_active_value(p, {"activity_status": ""}), "unknown")
        self.assertEqual(pm.linkedin_active_value(p, None), "")
        self.assertEqual(pm.linkedin_active_value({}, {"activity_status": "Active"}), "")

    def test_channels(self):
        base = {"cap_status": "selected", "tier": "T1", "linkedin_url": "u", "linkedin_active": "yes",
                "email_verdict": "valid", "phone": "+44"}
        self.assertEqual(pm.channels_for(base), ["linkedin", "email", "call"])
        self.assertEqual(pm.channels_for(dict(base, tier="T2")), ["linkedin", "email"])  # T2 never gets a call
        self.assertEqual(pm.channels_for(dict(base, tier="")), ["linkedin", "email"])  # unknown tier acts as T2
        self.assertEqual(pm.channels_for(dict(base, linkedin_active="no")), ["email", "call"])  # inactive: no LinkedIn
        self.assertEqual(pm.channels_for(dict(base, email_verdict="catch_all")), ["linkedin", "call"])
        self.assertEqual(pm.channels_for(dict(base, email_verdict="invalid", linkedin_active="unknown")), ["call"])
        self.assertEqual(pm.channels_for(dict(base, phone="")), ["linkedin", "email"])
        self.assertEqual(pm.channels_for(dict(base, cap_status="over_cap")), [])
        self.assertEqual(pm.channels_for(dict(base, linkedin_active="")), ["email", "call"])  # unchecked is not active
        self.assertEqual(pm.channels_for(dict(base, linkedin_active=""), activity_skipped=True), ["linkedin", "email", "call"])


class TestPeopleSearch(unittest.TestCase):
    def setUp(self):
        self.run = make_run("ps-%s" % self.id().split(".")[-1])
        qualified(self.run, [("o1", "a.com", "A Ltd", "keep"), ("o2", "b.com", "B Ltd", "review"),
                             ("o3", "c.com", "C Ltd", "keep"), ("o4", "d.com", "D Ltd", "drop")])

    def test_search_ledger_resume_none_and_tabs(self):
        tr = FakePeopleApollo({"o1": [person("p1", "o1", "COO"), person("p2", "o1", "Owner")], "o2": []})
        rep = pm.run_search(self.run, BRIEF, client(tr, self.run), progress=None)
        self.assertEqual((rep["searched"], rep["found"], rep["none"], rep["people"]), (3, 1, 2, 2))  # o4 is dropped, not searched
        self.assertEqual(len(tr.calls), 3)
        self.assertIn("organization_ids%5B%5D=o1", tr.calls[0])
        self.assertIn("person_titles%5B%5D=Chief+Operating+Officer", tr.calls[0])  # T1 and T2 titles in ONE call
        self.assertIn("person_titles%5B%5D=Quality+Manager", tr.calls[0])
        n = len(tr.calls)
        rep2 = pm.run_search(self.run, BRIEF, client(tr, self.run), progress=None)  # resume: nothing new
        self.assertEqual((rep2["searched"], len(tr.calls)), (0, n))
        nop = {r["org_id"]: r for r in pm.no_people_rows(self.run)}
        self.assertEqual(set(nop), {"o2", "o3"})
        self.assertTrue(nop["o2"]["reason"].startswith("no_people_found"))
        rows = pm.rebuild(self.run, BRIEF)
        self.assertEqual({r["person_id"] for r in rows}, {"p1", "p2"})
        self.assertTrue(all(r["cap_status"] == "candidate" and r["company"] == "A Ltd" for r in rows))
        self.assertEqual({r["person_id"]: r["title_hint"] for r in rows}, {"p1": "T1", "p2": "T1"})

    def test_error_is_retried_and_does_not_count_as_done(self):
        tr = FakePeopleApollo({"o1": [person("p1", "o1", "COO")]}, fail_orgs=["o2"])
        c = client(tr, self.run)
        c.cfg = dict(c.cfg, max_retries=1)
        rep = pm.run_search(self.run, BRIEF, c, progress=None)
        self.assertEqual(rep["errors"], 1)
        self.assertEqual(pm.ledger(self.run)["o2"]["status"], "error")
        self.assertIn("search_error", pm.no_people_rows(self.run)[0]["reason"] + pm.no_people_rows(self.run)[1]["reason"])
        tr.fail_orgs.clear()
        rep2 = pm.run_search(self.run, BRIEF, client(tr, self.run), progress=None)
        self.assertEqual(rep2["searched"], 1)  # only the failed company again
        self.assertEqual(pm.ledger(self.run)["o2"]["status"], "none")

    def test_query_change_needs_acceptance(self):
        tr = FakePeopleApollo({"o1": [person("p1", "o1", "COO")]})
        pm.run_search(self.run, BRIEF, client(tr, self.run), progress=None)
        b2 = json.loads(json.dumps(BRIEF))
        b2["people"]["T2"]["titles"].append("Head of Quality")
        with self.assertRaises(pm.PeopleError):
            pm.run_search(self.run, b2, client(tr, self.run), progress=None)
        rep = pm.run_search(self.run, b2, client(tr, self.run), accept_query_change=True, progress=None)
        self.assertEqual(rep["searched"], 3)  # old search archived, everything again
        self.assertTrue(list((self.run.dir / "people").glob("search.ledger.jsonl.old-*")))

    def test_stops_cleanly_when_hourly_budget_is_low(self):
        tr = FakePeopleApollo({}, hour_left="10")
        rep = pm.run_search(self.run, BRIEF, client(tr, self.run), progress=None)
        self.assertEqual(rep["searched"], 1)  # first answer carries the header, then it pauses
        self.assertIn("hourly", rep["paused"])

    def test_duplicate_person_ids_across_companies_are_skipped(self):
        tr = FakePeopleApollo({"o1": [person("p1", "o1", "COO")], "o2": [person("p1", "o2", "COO")]})
        rep = pm.run_search(self.run, BRIEF, client(tr, self.run), progress=None)
        self.assertEqual((rep["people"], rep["duplicates_skipped"]), (1, 1))

    def test_pool_needs_finalized_qualify(self):
        r = make_run("ps-noq")
        with self.assertRaises(pm.PeopleError):
            pm.pool_accounts(r)


class TestTier(unittest.TestCase):
    def setUp(self):
        self.run = make_run("tier-%s" % self.id().split(".")[-1])
        qualified(self.run, [("o1", "a.com", "A Ltd", "keep"), ("o2", "b.com", "B Ltd", "keep")])
        tr = FakePeopleApollo({"o1": [person("p%d" % i, "o1", "COO") for i in range(4)],
                               "o2": [person("q%d" % i, "o2", "Owner") for i in range(2)]})
        pm.run_search(self.run, BRIEF, client(tr, self.run), progress=None)
        pm.rebuild(self.run, BRIEF)
        self.t = tmod.Tier(self.run)
        self.spec = tmod.spec_from_brief(BRIEF)

    def test_prompt_blocks_and_spec(self):
        text = tmod.build_prompt(self.spec)
        for m in tmod.MARKERS:
            self.assertIn(m, text)
        with self.assertRaises(ValueError):
            tmod.build_prompt({"idea": "x", "t1": "a"})
        with self.assertRaises(ValueError):
            tmod.check_prompt("no blocks")
        self.assertIn("budget holder", text)  # the user's own tier rule words are in the prompt

    def test_lock_is_tied_to_prompt(self):
        self.t.set_spec(self.spec)
        self.t.lock(2)
        self.assertTrue(self.t.is_locked())
        self.t.set_spec(dict(self.spec, extra_rules=["edge"]))
        self.assertFalse(self.t.is_locked())

    def test_tuning_streak_simulated_label(self):
        self.assertEqual(self.t.log_round(1, 1, "x", simulated=True), 0)
        self.assertEqual(self.t.log_round(2, 0, simulated=True), 1)
        self.assertTrue(all(r["simulated"] for r in self.t.tuning()["rounds"]))
        self.t.set_spec(self.spec)
        self.assertTrue(self.t.status()["tuning_simulated"])

    def test_validate_item_strict(self):
        ids = {"p0"}
        self.assertEqual(tmod.validate_item({"id": "p0", "tier": "t1", "reason": "ok"}, ids)[0]["tier"], "T1")
        self.assertIsNotNone(tmod.validate_item({"id": "p0", "tier": "T3", "reason": "ok"}, ids)[1])
        self.assertIsNotNone(tmod.validate_item({"id": "p0", "tier": "T1", "reason": " "}, ids)[1])
        self.assertIsNone(tmod.validate_item({"id": "zz", "tier": "T1", "reason": "r"}, ids)[0])

    def test_batches_grouped_by_company_ingest_caps_and_retry(self):
        self.t.set_spec(self.spec)
        res = self.t.make_batches(size=4)
        sizes = sorted(len(json.load(open(p))["rows"]) for p in res["batches"])
        self.assertEqual(sizes, [2, 4])  # company A (4) and company B (2) are never mixed beyond the size
        b = json.load(open(res["batches"][0]))
        ids = [r["id"] for r in b["rows"]]
        out = [{"id": ids[0], "tier": "T1", "reason": "fits"}, {"id": ids[1], "tier": "banana", "reason": "bad"}]
        open(b["result_file"], "w").write(json.dumps(out))
        rep = self.t.ingest_file(b["result_file"])
        self.assertEqual((rep["ok"], rep["invalid"], rep["missing"]), (1, 1, len(ids) - 1))
        self.assertEqual(len(self.t.results()), 1)
        res2 = self.t.make_batches(size=10)  # retry: the tiered one is gone, the invalid one is back, in-flight skipped
        self.assertGreaterEqual(res2["pending"], 1)
        # tier everything, then caps apply: A has 4 T1 candidates, cap T1 is 2
        for p in pm.load_table(self.run):
            if p["org_id"] == "o1":
                append_jsonl(self.t.results_path, {"person_id": p["person_id"], "tier": "T1", "reason": "r"})
            else:
                append_jsonl(self.t.results_path, {"person_id": p["person_id"], "tier": "T2", "reason": "r"})
        fin = self.t.finalize(push=False)
        self.assertEqual(fin["selected_by_tier"], {"T1": 2, "T2": 1})
        self.assertEqual(fin["cap_status"]["over_cap"], 2 + 1)
        rows = pm.load_table(self.run)
        self.assertEqual(len(rows), 6)  # rows are never deleted

    def test_skip_marks_stage_skipped_and_picks_by_title(self):
        write_json(pm.Files(self.run).tier_skipped, {"note": "user said so"})
        rows = pm.rebuild(self.run, BRIEF)
        self.assertEqual(sum(1 for r in rows if r["cap_status"] == "selected"), 2 + 1 + 2)  # per company up to T1+T2 caps = 3
        self.assertEqual(stages.check_tier(self.run, {"people": {"status": "done"}})["status"], "skipped")


class TestEnrich(unittest.TestCase):
    def setUp(self):
        self.run = make_run("en-%s" % self.id().split(".")[-1])
        qualified(self.run, [("o1", "a.com", "A Ltd", "keep")])
        tr = FakePeopleApollo({"o1": [person("p1", "o1", "COO"), person("noemail1", "o1", "Owner"),
                                      person("nomatch1", "o1", "Managing Director"), person("p9", "o1", "Gardener")]})
        pm.run_search(self.run, BRIEF, client(tr, self.run), progress=None)
        pm.rebuild(self.run, BRIEF)
        t = tmod.Tier(self.run)
        for p in pm.load_table(self.run):
            append_jsonl(t.results_path, {"person_id": p["person_id"], "tier": "X" if p["person_id"] == "p9" else "T1", "reason": "r"})
        pm.rebuild(self.run, BRIEF)  # caps T1=2 -> p1 and noemail1 selected (best titles), nomatch1 over cap

    def test_only_capped_people_are_sent_and_credits_are_real(self):
        rows = pm.load_table(self.run)
        self.assertEqual({r["person_id"] for r in rows if r["cap_status"] == "selected"}, {"p1", "noemail1"})
        tr = FakePeopleApollo()
        rep = emod.run_enrich(self.run, client(tr, self.run), progress=None)
        self.assertEqual((rep["requested"], rep["matched"], rep["with_email"]), (2, 2, 1))  # placeholder email is not an email
        self.assertEqual(rep["credits"], 2.0)
        sent = [d["id"] for q, body in tr.bulk for d in body["details"]]
        self.assertEqual(sorted(sent), ["noemail1", "p1"])  # over_cap, X and not-selected people never cost credits
        usage = read_jsonl(self.run.usage_log)
        self.assertTrue(any(u["endpoint"] == "people/bulk_match" and u["credits"] == 2.0 for u in usage))
        rep2 = emod.run_enrich(self.run, client(tr, self.run), progress=None)  # re-run never pays twice
        self.assertEqual(rep2["requested"], 0)
        self.assertEqual(len(tr.bulk), 1)
        rows = {r["person_id"]: r for r in pm.load_table(self.run)}
        self.assertEqual(rows["p1"]["email"], "p1@a.com")
        self.assertEqual(rows["p1"]["last_name"], "Smith")
        self.assertEqual(rows["p1"]["linkedin_url"], "http://www.linkedin.com/in/p1")
        self.assertEqual(rows["noemail1"]["email"], "")
        self.assertEqual(rows["noemail1"]["email_verdict"], "missing")
        self.assertEqual(rows["noemail1"]["waterfall_needed"], "email_missing")

    def test_no_match_is_recorded_and_estimate(self):
        est = emod.estimate(pm.load_table(self.run))
        self.assertEqual((est["people"], est["calls"]), (2, 1))

    def test_bulk_match_limits(self):
        c = client(FakePeopleApollo())
        with self.assertRaises(apollo.ApolloError):
            c.bulk_match([{"id": str(i)} for i in range(11)])
        with self.assertRaises(apollo.ApolloError):
            c.bulk_match([{"id": "a"}], reveal_phone=True)  # needs a webhook

    def test_duplicate_humans_found_after_enrichment(self):
        rows = [{"person_id": "a", "cap_status": "selected", "title_rank": 1, "linkedin_url": "http://www.linkedin.com/in/x/", "email": "", "tier_reason": ""},
                {"person_id": "b", "cap_status": "selected", "title_rank": 2, "linkedin_url": "https://linkedin.com/in/X", "email": "", "tier_reason": ""},
                {"person_id": "c", "cap_status": "selected", "title_rank": 3, "linkedin_url": "", "email": "Z@a.com", "tier_reason": ""},
                {"person_id": "d", "cap_status": "selected", "title_rank": 4, "linkedin_url": "", "email": "z@a.com", "tier_reason": ""}]
        pm.dedupe_selected(rows)
        self.assertEqual([r["cap_status"] for r in rows], ["selected", "duplicate", "selected", "duplicate"])


class FakeMV:
    def __init__(self, answers):
        self.answers, self.seen = answers, []

    def __call__(self, method, url, headers, data, timeout):
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(url).query)
        self.seen.append((url, headers))
        e = q["email"][0]
        a = self.answers.get(e, {"result": "ok"})
        if isinstance(a, int):
            return a, {}, b"{}"
        return 200, {}, json.dumps(dict({"email": e, "subresult": "mailbox_exists", "quality": "good", "error": ""}, **a)).encode()


class TestVerify(unittest.TestCase):
    def test_results_user_agent_and_key_hygiene(self):
        tr = FakeMV({"c@x.com": {"result": "catch_all", "subresult": "accept_all"}, "i@x.com": {"result": "invalid", "subresult": "mailbox_not_found"}})
        mv = vmod.MillionVerifier(api_key="SECRETKEY", transport=tr, sleep=lambda s: None)
        self.assertEqual(mv.verify("o@x.com")["result"], "ok")
        self.assertEqual(mv.verify("c@x.com")["result"], "catch_all")
        r = mv.verify("i@x.com")
        self.assertEqual((r["result"], r["subresult"]), ("invalid", "mailbox_not_found"))
        url, headers = tr.seen[0]
        self.assertIn("Mozilla", headers["User-Agent"])  # a browser User-Agent is required or MV answers 403
        self.assertIn("api=SECRETKEY", url)

    def test_fatal_and_transient(self):
        with self.assertRaises(vmod.MVError):
            vmod.MillionVerifier(api_key="k", transport=FakeMV({"a@x.com": 403}), sleep=lambda s: None).verify("a@x.com")
        n = []

        def flaky(*a):
            n.append(1)
            raise OSError("down SECRETKEY")
        r = vmod.MillionVerifier(api_key="SECRETKEY", transport=flaky, sleep=lambda s: None).verify("a@x.com")
        self.assertEqual(r["result"], "error")
        self.assertNotIn("SECRETKEY", json.dumps(r))  # the key never lands in logs or cache
        self.assertEqual(len(n), config.get("verify.max_retries"))
        with self.assertRaises(vmod.MVError):
            vmod.MillionVerifier(api_key="k", transport=FakeMV({"a@x.com": {"result": "", "error": "Invalid API key"}}),
                                 sleep=lambda s: None).verify("a@x.com")

    def test_missing_key_is_detected(self):
        old = os.environ.pop("MILLIONVERIFIER_API_KEY", None)
        try:
            self.assertFalse(vmod.key_available())
            with self.assertRaisesRegex(vmod.MVError, "MILLIONVERIFIER_API_KEY"):
                vmod.MillionVerifier()
        finally:
            if old:
                os.environ["MILLIONVERIFIER_API_KEY"] = old

    def test_run_verify_caches_and_records_catch_all(self):
        run = make_run("vf")
        qualified(run, [("o1", "x.com", "X", "keep")])
        tr = FakePeopleApollo({"o1": [person("p1", "o1", "COO"), person("p2", "o1", "Owner")]})
        pm.run_search(run, BRIEF, client(tr, run), progress=None)
        pm.rebuild(run, BRIEF)
        t = tmod.Tier(run)
        for p in pm.load_table(run):
            append_jsonl(t.results_path, {"person_id": p["person_id"], "tier": "T1", "reason": "r"})
        emod.run_enrich(run, client(FakePeopleApollo(), run), progress=None)
        mvt = FakeMV({"p2@x.com": {"result": "catch_all"}})
        mv = vmod.MillionVerifier(api_key="k", transport=mvt, sleep=lambda s: None)
        rep = vmod.run_verify(run, mv=mv, progress=None)
        self.assertEqual(rep["results"], {"ok": 1, "catch_all": 1})
        self.assertEqual(vmod.run_verify(run, mv=mv, progress=None)["to_check"], 0)  # cached: no second charge
        self.assertEqual(len(mvt.seen), 2)
        rows = {r["person_id"]: r for r in pm.rebuild(run, BRIEF)}
        self.assertEqual((rows["p1"]["email_verdict"], rows["p1"]["mv_result"]), ("valid", "ok"))
        self.assertEqual((rows["p2"]["email_verdict"], rows["p2"]["waterfall_needed"]), ("catch_all", "catch_all_secondary_verify"))
        self.assertEqual(waterfall.write_list(run, list(rows.values())), {"catch_all_secondary_verify": 1})
        with self.assertRaises(waterfall.ProviderNotSetUp):
            waterfall.PROVIDERS["prospeo"].find_email({})

    def test_errors_are_retried(self):
        rows = [{"cap_status": "selected", "email": "a@x.com"}, {"cap_status": "selected", "email": "b@x.com"},
                {"cap_status": "over_cap", "email": "c@x.com"}]
        cache = {"a@x.com": {"result": "error"}, "b@x.com": {"result": "ok"}}
        self.assertEqual(vmod.todo_emails(rows, cache), ["a@x.com"])


class TestReviewPhase2Fixes(unittest.TestCase):
    """Defects fixed in the Phase 2 review (REVIEW-PHASE2.md)."""

    def test_matches_are_paired_by_person_id_not_position(self):
        chunk = [{"person_id": "a"}, {"person_id": "b"}, {"person_id": "c"}]
        # Apollo answer out of order, one null, one merged record under a new id in position 3
        out = emod.align_matches(chunk, [{"person_id": "b", "email": "b@x.com"}, None, {"person_id": "z", "email": "z@x.com"}])
        self.assertEqual([m and m["person_id"] for m in out], [None, "b", "z"])
        out = emod.align_matches(chunk, [{"person_id": "a"}, {"person_id": "b"}])  # short list
        self.assertEqual([m and m["person_id"] for m in out], ["a", "b", None])

    def test_mv_blocked_ip_is_fatal_and_internal_error_backs_off(self):
        # error texts seen live with MillionVerifier's demo keys
        with self.assertRaises(vmod.MVError):
            vmod.MillionVerifier(api_key="k", transport=FakeMV({"a@x.com": {"result": "", "error": "IP address blocked"}}),
                                 sleep=lambda s: None).verify("a@x.com")
        with self.assertRaises(vmod.MVError):
            vmod.MillionVerifier(api_key="k", transport=FakeMV({"a@x.com": {"result": "error", "error": "Apikey not found"}}),
                                 sleep=lambda s: None).verify("a@x.com")
        slept = []
        r = vmod.MillionVerifier(api_key="k", transport=FakeMV({"a@x.com": {"result": "", "error": "Internal error"}}),
                                 sleep=slept.append).verify("a@x.com")
        self.assertEqual((r["result"], r["subresult"]), ("error", "Internal error"))
        self.assertEqual(len(slept), config.get("verify.max_retries"))

    def test_profile_key_matches_activity_cache_key(self):
        u = "http://www.linkedin.com/in/jane-doe/en?trk=x"
        self.assertEqual(pm.profile_key(u), pm.norm_url(amod.canonical_url(u)))
        self.assertEqual(pm.profile_key("https://linkedin.com/in/jane-doe/"), "linkedin.com/in/jane-doe")

    def test_phone_hint_maps_false_to_no(self):
        self.assertEqual(pm._phone_hint(False), "no")
        self.assertEqual(pm._phone_hint("Yes"), "Yes")
        self.assertEqual(pm._phone_hint(None), "")
        self.assertTrue(pm._phone_hint("Maybe: please request direct dial via people/bulk_match").startswith("Maybe"))


class TestQuality(unittest.TestCase):
    def rows(self, n=10, **over):
        out = []
        for i in range(n):
            r = {"person_id": "p%d" % i, "org_id": "o%d" % (i // 2), "domain": "d%d.com" % (i // 2), "cap_status": "selected",
                 "email": "person%d@d%d.com" % (i, i // 2), "mv_result": "ok", "title": "Managing Director",
                 "title_rank": 6, "tier": "T1", "first_name": "Anna", "last_name": "Brown"}
            r.update(over)
            out.append(r)
        return out

    def test_clean_list_is_an_a_and_flagged_small(self):
        flags = {"o%d" % i: "keep" for i in range(5)}
        rep = quality.score(self.rows(), BRIEF, flags)
        self.assertEqual(rep["grade"], "A+")
        self.assertTrue(rep["indicative_only"])
        self.assertEqual(len(rep["dims"]), 8)  # the 8 checks
        self.assertEqual([d["key"] for d in rep["dims"]][:2], ["email_verification", "duplicate_emails"])

    def test_problems_lower_the_grade_and_are_reported(self):
        rows = self.rows(10)
        rows[0].update(mv_result="invalid")
        rows[1].update(mv_result="catch_all")
        rows[2].update(email="info@d1.com")
        rows[3].update(title="Intern", title_rank=1000, tier="")
        rows[4].update(first_name="ADMIN", last_name="")
        rows[5].update(email=rows[6]["email"])
        rep = quality.score(rows, BRIEF, {"o%d" % i: "review" for i in range(5)})
        self.assertLess(rep["score"], 80)
        text = " ".join(rep["issues"])
        self.assertIn("not `ok`", text)
        self.assertIn("catch-all", text)
        self.assertIn("duplicate emails", text)
        md = quality.render(rep, "run")
        self.assertIn("Pre-send checklist", md)

    def test_unverified_list_scores_zero_on_verification(self):
        rows = self.rows(10, mv_result="")
        rep = quality.score(rows, BRIEF, {})
        self.assertEqual(rep["dims"][0]["score"], 0)

    def test_domain_limit_follows_caps_not_the_original_two(self):
        rows = self.rows(8, org_id="o1", domain="same.com")
        rep = quality.score(rows, BRIEF, {})
        d = next(x for x in rep["dims"] if x["key"] == "domain_concentration")
        self.assertEqual(d["score"], 100 - round(100.0 * 5 / 8))  # caps are 2+1=3, five rows above the limit
        self.assertEqual(quality.letter(92), "A")
        self.assertEqual(quality.letter(59), "F")

    def test_empty(self):
        self.assertEqual(quality.score([], BRIEF)["grade"], "F")


class FakeN8n:
    """Replaces n8n.get_workflow / set_active / backup_workflow / webhook calls."""
    def __init__(self, active=False, contract=True):
        self.active, self.contract, self.toggles = active, contract, []

    def install(self):
        self.old = (n8n.get_workflow, n8n.set_active, n8n.backup_workflow)
        n8n.get_workflow = lambda wid: {"name": "LinkedIn Activity Checker", "active": self.active,
                                        "nodes": [{"name": "Config", "parameters": {"jsCode": "IL_CONTRACT_V1" if self.contract else "x"}}]}
        n8n.set_active = lambda wid, on: (self.toggles.append(on), setattr(self, "active", on), on)[2]
        n8n.backup_workflow = lambda wid, label: "/tmp/backup-%s.json" % label

    def restore(self):
        n8n.get_workflow, n8n.set_active, n8n.backup_workflow = self.old


class FakeChecker:
    """Stands in for activity.Checker: records calls, returns scripted leads."""
    def __init__(self, run, leads=None, end=True, fail_upsert=False):
        self.run = run
        self.cfg = config.get("activity")
        self.leads_tab, self.runs_tab = amod.tab_names(run)
        self.sheet_id, self.wid = "SHEET", self.cfg["workflow_id"]
        self.leads, self.end, self.fail_upsert, self.upserted = leads or [], end, fail_upsert, []

    def assert_contract(self):
        pass

    def upsert(self, rows):
        if self.fail_upsert:
            raise amod.ActivityError("webhook down")
        self.upserted += rows

    def wait_rows_present(self, urls, timeout_s=0):
        return True

    def start_run(self, n):
        return time.time()

    def wait_run_end(self, started, timeout_s, poll_s):
        return {"stage": "run_end", "usage_usd": "0.12"} if self.end else None

    def read_leads(self):
        return self.leads


class TestActivity(unittest.TestCase):
    def setUp(self):
        self.run = make_run("act-%s" % self.id().split(".")[-1])
        qualified(self.run, [("o1", "a.com", "A Ltd", "keep")])
        tr = FakePeopleApollo({"o1": [person("p1", "o1", "COO"), person("p2", "o1", "Owner")]})
        pm.run_search(self.run, BRIEF, client(tr, self.run), progress=None)
        pm.rebuild(self.run, BRIEF)
        t = tmod.Tier(self.run)
        for p in pm.load_table(self.run):
            append_jsonl(t.results_path, {"person_id": p["person_id"], "tier": "T1", "reason": "r"})
        emod.run_enrich(self.run, client(FakePeopleApollo(), self.run), progress=None)
        self.n8n = FakeN8n()
        self.n8n.install()

    def tearDown(self):
        self.n8n.restore()

    def test_canonical_url_and_finality(self):
        self.assertEqual(amod.canonical_url("http://www.linkedin.com/in/jane-doe/?x=1"), "https://www.linkedin.com/in/jane-doe")
        self.assertEqual(amod.canonical_url("https://uk.linkedin.com/company/x"), "")
        self.assertEqual(amod.canonical_url(""), "")
        self.assertTrue(amod.is_final({"activity_status": "Active"}))
        self.assertTrue(amod.is_final({"activity_status": "", "scrape_attempts": 3}))
        self.assertFalse(amod.is_final({"activity_status": "", "scrape_attempts": 1, "scrape_error": "retry"}))

    def test_flow_caches_activates_only_for_the_run_and_maps_status(self):
        leads = [{"linkedin_url": "https://www.linkedin.com/in/p1", "activity_status": "Active", "scrape_attempts": 1},
                 {"linkedin_url": "https://www.linkedin.com/in/p2", "activity_status": "Shell", "scrape_attempts": 1}]
        ch = FakeChecker(self.run, leads)
        rep = amod.run_activity(self.run, checker=ch, progress=lambda *a: None)
        self.assertEqual(self.n8n.toggles, [True, False])  # on for the run, off afterwards
        self.assertFalse(self.n8n.active)
        self.assertEqual(len(ch.upserted), 2)
        self.assertEqual((rep["counts"]["Active"], rep["counts"]["Shell"]), (1, 1))
        rows = {r["person_id"]: r for r in pm.rebuild(self.run, BRIEF)}
        self.assertEqual((rows["p1"]["linkedin_active"], rows["p2"]["linkedin_active"]), ("yes", "no"))
        again = amod.run_activity(self.run, checker=FakeChecker(self.run, leads), progress=lambda *a: None)
        self.assertEqual(again["to_check"], 0)  # cached by profile URL: never checked twice
        self.assertEqual(self.n8n.toggles, [True, False])

    def test_deactivates_even_when_the_run_fails(self):
        with self.assertRaises(amod.ActivityError):
            amod.run_activity(self.run, checker=FakeChecker(self.run, fail_upsert=True), progress=lambda *a: None)
        self.assertEqual(self.n8n.toggles, [True, False])

    def test_timeout_keeps_it_on_for_resume_but_marks_it_ours(self):
        ch = FakeChecker(self.run, [], end=False)
        rep = amod.run_activity(self.run, checker=ch, progress=lambda *a: None)
        self.assertIn("timed out", rep["note"])
        self.assertEqual(self.n8n.toggles, [True])
        self.assertTrue(read_json_state(self.run)["activated_by_us"])
        leads = [{"linkedin_url": "https://www.linkedin.com/in/p1", "activity_status": "Inactive"},
                 {"linkedin_url": "https://www.linkedin.com/in/p2", "activity_status": "Active"}]
        rep2 = amod.run_activity(self.run, checker=FakeChecker(self.run, leads), resume=True, progress=lambda *a: None)
        self.assertEqual(self.n8n.toggles, [True, False])  # resume collected, then switched it off
        self.assertEqual(rep2["counts"]["final"], 2)

    def test_checker_already_active_is_left_active(self):
        self.n8n.active = True
        amod.run_activity(self.run, checker=FakeChecker(self.run, []), progress=lambda *a: None)
        self.assertEqual(self.n8n.toggles, [])

    def test_missing_contract_is_refused(self):
        class NoContract(amod.Checker):
            def __init__(self):
                pass
        self.n8n.contract = False
        c = NoContract()
        c.wid = "x"
        with self.assertRaisesRegex(amod.ActivityError, "contract"):
            c.assert_contract()

    def test_pending_rows_are_not_cached(self):
        ch = FakeChecker(self.run, [{"linkedin_url": "https://www.linkedin.com/in/p1", "activity_status": "", "scrape_attempts": 1,
                                     "scrape_error": "posts scrape failed, will retry"}])
        rep = amod.run_activity(self.run, checker=ch, progress=lambda *a: None)
        self.assertEqual(rep["counts"]["pending"], 1)
        self.assertEqual(len(amod.cache(self.run)), 0)


def read_json_state(run):
    from util import read_json
    return read_json(pm.Files(run).activity_state, {})


class TestPhones(unittest.TestCase):
    def test_parse_row_shapes(self):
        row = {"person_id": "p1", "request_id": "5", "phones_json": json.dumps([{"sanitized_number": "+441", "type_cd": "work_hq"},
                                                                                 {"sanitized_number": "+447", "type_cd": "mobile"}])}
        self.assertEqual(phmod.parse_row(row), [("p1", "received", "+447", "mobile", "5")])  # mobile wins
        self.assertEqual(phmod.parse_row({"person_id": "p2", "phones_json": "[]"})[0][1], "none")
        raw = {"person_id": "", "request_id": "6", "raw_json": json.dumps({"people": [{"id": "p3", "phone_numbers": [{"raw_number": "+33"}]}]})}
        self.assertEqual(phmod.parse_row(raw), [("p3", "received", "+33", "", "6")])
        self.assertEqual(phmod.parse_row({"person_id": "", "raw_json": "not json"}), [])

    def test_t1_only_request_and_collect(self):
        run = make_run("ph")
        qualified(run, [("o1", "a.com", "A Ltd", "keep")])
        tr = FakePeopleApollo({"o1": [person("p1", "o1", "COO"), person("p2", "o1", "Quality Manager"),
                                      person("p3", "o1", "Owner", has_direct_phone="No")]})
        pm.run_search(run, BRIEF, client(tr, run), progress=None)
        pm.rebuild(run, BRIEF)
        t = tmod.Tier(run)
        tiers = {"p1": "T1", "p2": "T2", "p3": "T1"}
        for pid, tt in tiers.items():
            append_jsonl(t.results_path, {"person_id": pid, "tier": tt, "reason": "r"})
        emod.run_enrich(run, client(FakePeopleApollo(), run), progress=None)
        old = (phmod.receiver, phmod.table_rows)
        phmod.receiver = lambda: ("https://n8n.example/webhook/secret", "TBL")
        rows_in_table = []
        phmod.table_rows = lambda tid: rows_in_table
        try:
            tr2 = FakePeopleApollo()
            rep = phmod.run_phones(run, client(tr2, run), poll=False, progress=None)
            self.assertEqual((rep["requested"], rep["skipped_no_phone"]), (1, 1))  # only p1; p2 is T2, p3 Apollo says no phone
            q, body = tr2.bulk[0]
            self.assertEqual([d["id"] for d in body["details"]], ["p1"])
            self.assertEqual(q["reveal_phone_number"], ["true"])
            self.assertEqual(q["webhook_url"], ["https://n8n.example/webhook/secret"])
            self.assertEqual(rep["credits"], 8.0)
            st = phmod.state(run)
            self.assertEqual((st["p1"]["status"], st["p3"]["status"]), ("requested", "not_available"))
            rep2 = phmod.run_phones(run, client(tr2, run), poll=False, progress=None)  # never requested twice
            self.assertEqual(rep2["requested"], 0)
            self.assertEqual(len(tr2.bulk), 1)
            self.assertEqual(phmod.collect(run, "TBL")["still_waiting"], 1)
            rows_in_table.append({"person_id": "p1", "request_id": "-42", "phones_json": json.dumps([{"sanitized_number": "+447700900001", "type_cd": "mobile"}]),
                                  "raw_json": json.dumps({"credits_consumed": 5, "people": [{"id": "p1", "phone_numbers": [{"sanitized_number": "+447700900001"}]}]})})
            self.assertEqual(phmod.collect(run, "TBL")["received"], 1)
            wh = [u for u in read_jsonl(run.usage_log) if u["endpoint"] == "phone_webhook"]
            self.assertEqual([u["credits"] for u in wh], [5.0])  # the phone part of the cost is logged once
            phmod.collect(run, "TBL")
            self.assertEqual(len([u for u in read_jsonl(run.usage_log) if u["endpoint"] == "phone_webhook"]), 1)
            rows = {r["person_id"]: r for r in pm.rebuild(run, BRIEF)}
            self.assertEqual((rows["p1"]["phone"], rows["p1"]["phone_status"]), ("+447700900001", "received"))
            self.assertEqual(rows["p2"]["phone"], "")
        finally:
            phmod.receiver, phmod.table_rows = old

    def test_receiver_must_be_deployed(self):
        old = config.cfg()["phones"].pop("webhook_path", None)
        old_t = config.cfg()["phones"].pop("data_table_id", None)
        try:
            with self.assertRaisesRegex(phmod.PhoneError, "deploy_phone_webhook"):
                phmod.receiver()
        finally:
            if old:
                config.cfg()["phones"]["webhook_path"] = old
            if old_t:
                config.cfg()["phones"]["data_table_id"] = old_t


class FakeSheet:
    def __init__(self):
        self.upserts, self.schema_calls = [], 0

    def ensure_schema(self, sid, tabs=None):
        self.schema_calls += 1
        return {}

    def upsert(self, sid, tab, key, recs):
        self.upserts.append((tab, key, [dict(r) for r in recs]))
        return {"updated": 0, "appended": len(recs), "skipped": 0, "unknown_columns": []}


def full_run(slug, test=False):
    """A run with every artifact present, for registry and Ready tests."""
    b = json.loads(json.dumps(BRIEF))
    b["idea"]["test"] = test
    run = make_run(slug, b)
    write_json(run.ledger_path, {"complete": True, "leaves": {}})
    qualified(run, [("o1", "a.com", "A Ltd", "keep"), ("o2", "b.com", "B Ltd", "keep")])
    (run.qdir / "prompt.md").write_text("x")
    for oid in ("o1", "o2"):
        append_jsonl(run.qdir / "results.jsonl", {"org_id": oid, "flag": "keep"})
    time.sleep(0.01)
    write_csv(run.qdir / "qualified.csv", read_csv(run.qdir / "qualified.csv"), schema.ACCOUNT_COLS)
    tr = FakePeopleApollo({"o1": [person("p1", "o1", "COO"), person("p2", "o1", "Quality Manager"), person("p3", "o1", "Owner")], "o2": []})
    pm.run_search(run, b, client(tr, run), progress=None)
    pm.rebuild(run, b)
    t = tmod.Tier(run)
    for pid, tt in (("p1", "T1"), ("p2", "T2"), ("p3", "T1")):
        append_jsonl(t.results_path, {"person_id": pid, "tier": tt, "reason": "budget holder"})
    emod.run_enrich(run, client(FakePeopleApollo(), run), progress=None)
    return run, b


class TestRegistryAndReady(unittest.TestCase):
    def test_registry_order_and_new_stage_plugs_in(self):
        self.assertEqual(stages.names(), ["brief", "pilot_accounts", "accounts", "signals", "qualify", "people", "tier", "pilot_people",
                                          "enrich_verify", "activity", "phones", "ready", "copy", "idea_page", "launch"])
        # Phase 3 stages are registered after ready; the pilot gates and signals were added later (see PLAN.md)
        self.assertEqual(stages.required_names(), stages.names()[:-1])  # launch is the action AFTER READY
        stages.register("zz", "zz", "/iv-zz {run}", lambda run, done: {"status": "pending", "detail": "x"})
        try:
            run = make_run("reg")
            self.assertIn("zz", stages.derive(run))
            self.assertIn("zz", run.stage_status())
        finally:
            stages.REGISTRY.pop()

    def test_next_command_walks_the_registry(self):
        run = make_run("nc")
        self.assertIn("/iv-accounts", run.next_command())
        write_json(run.ledger_path, {"complete": True})
        write_csv(run.accounts_csv, [{"org_id": "a", "domain": "a.com", "name": "A"}], schema.ACCOUNT_BASE_COLS)
        self.assertIn("/iv-qualify", run.next_command())

    def test_full_run_becomes_ready_only_when_everything_is_done(self):
        run, b = full_run("full")
        self.assertTrue(run.write_summary().startswith("NOT READY"))
        pm.rebuild(run, b)
        st = run.stage_status()
        self.assertEqual(st["people"]["status"], "done")
        self.assertEqual(st["tier"]["status"], "done")
        self.assertEqual(st["enrich_verify"]["status"], "partial")  # emails not verified yet
        # verify
        mv = vmod.MillionVerifier(api_key="k", transport=FakeMV({"p3@a.com": {"result": "invalid"}}), sleep=lambda s: None)
        vmod.run_verify(run, mv=mv, progress=None)
        pm.rebuild(run, b)
        self.assertEqual(run.stage_status()["enrich_verify"]["status"], "done")
        # activity (cache) and phones
        f = pm.Files(run)
        for pid, st_ in (("p1", "Active"), ("p2", "Inactive"), ("p3", "Inactive")):
            append_jsonl(f.activity_cache, {"linkedin_key": pm.norm_url("http://www.linkedin.com/in/%s" % pid),
                                            "activity_status": st_, "checked_at": "2026-03-01T00:00:00Z"})
        write_json(f.phones_skipped, {"note": "test"})
        rows = pm.rebuild(run, b)
        by = {r["person_id"]: r for r in rows}
        self.assertEqual(by["p1"]["channels"], "linkedin+email")  # T1 but no phone (phones skipped)
        self.assertEqual(by["p3"]["channels"], "")  # inactive and invalid email: nothing left
        self.assertEqual(by["p2"]["cap_status"], "selected")
        self.assertEqual(run.stage_status()["phones"]["status"], "skipped")
        self.assertEqual(run.stage_status()["ready"]["status"], "pending")
        fs = FakeSheet()
        rep = rdy.build(run, push=True, sc=fs)
        self.assertEqual((rep["linkedin"], rep["email"], rep["calls"]), (1, 2, 0))
        first = run.write_summary()
        self.assertTrue(first.startswith("NOT READY: copy is pending"), first)  # Phase 3: copy and the idea page are needed too
        self.assertIn("/iv-copy", first)
        import run_tests_phase3 as p3
        p3.approved_copy(run)
        write_json(run.dir / "idea-page" / "skipped.json", {"note": "test"})
        first = run.write_summary()
        self.assertTrue(first.startswith("READY: 2 qualified companies, ready to launch: LinkedIn 1, Email 2, Calls 0"), first)
        self.assertTrue(first.endswith("Next: /iv-launch %s" % run.dir.name), first)  # launch is after READY, not part of it
        self.assertIn("List quality", run.summary_path.read_text())

    def test_test_run_is_never_ready(self):
        run, b = full_run("testflag", test=True)
        self.assertIn("TEST run", run.write_summary())

    def test_ready_records_calls_layout_and_withdrawal(self):
        rows = [{"person_id": "p1", "tier": "T1", "first_name": "A", "last_name": "B", "title": "COO", "company": "Co", "country": "UK",
                 "domain": "co.com", "linkedin_url": "u", "email": "a@co.com", "channels": "linkedin+email+call", "phone": "+44",
                 "tier_reason": "budget holder", "linkedin_active": "yes", "email_verdict": "valid"},
                {"person_id": "p2", "tier": "T2", "first_name": "C", "last_name": "D", "title": "QM", "company": "Co", "country": "UK",
                 "domain": "co.com", "linkedin_url": "v", "email": "c@co.com", "channels": "email", "phone": "", "tier_reason": "",
                 "linkedin_active": "no", "email_verdict": "valid"}]
        rec = rdy.records(rows, "Idea X")
        self.assertEqual(len(rec[schema.TAB_READY_LI]), 1)
        self.assertEqual(len(rec[schema.TAB_READY_EMAIL]), 2)
        call = rec[schema.TAB_READY_CALLS][0]
        for col in ("first_name", "last_name", "title", "company", "phone", "linkedin_url", "email", "idea", "call_notes"):
            self.assertIn(col, call)  # Mansi's layout
            self.assertIn(col, schema.TABS[schema.TAB_READY_CALLS])
        self.assertEqual(call["idea"], "Idea X")
        self.assertIn("budget holder", call["call_notes"])

    def test_withdrawn_instead_of_deleted(self):
        run, b = full_run("wd")
        f = pm.Files(run)
        write_json(f.phones_skipped, {"note": "t"})
        write_json(f.activity_skipped, {"note": "t"})
        vmod.run_verify(run, mv=vmod.MillionVerifier(api_key="k", transport=FakeMV({}), sleep=lambda s: None), progress=None)
        fs = FakeSheet()
        rep = rdy.build(run, push=True, sc=fs)
        self.assertEqual(rep["email"], 3)
        # one person becomes invalid later
        append_jsonl(f.mv, {"email": "p3@a.com", "result": "invalid", "subresult": "x", "checked_at": "t"})
        fs2 = FakeSheet()
        rep2 = rdy.build(run, push=True, sc=fs2)
        self.assertEqual(rep2["email"], 2)
        sent = [(tab, r) for tab, key, recs in fs2.upserts if tab == schema.TAB_READY_EMAIL for r in recs]
        self.assertEqual([r for t, r in sent if r["person_id"] == "p3"], [{"person_id": "p3", "status": "withdrawn"}])


class TestSheetAdditions(unittest.TestCase):
    def test_payloads(self):
        sent = []

        def tr(method, url, headers, data, timeout):
            sent.append(json.loads(data))
            return 200, {}, json.dumps({"ok": True, "added": ["x"], "existing": 3, "shared": [{"target": "domain:d.com", "ok": True}]}).encode()
        c = sheetmod.SheetClient(url="u", secret="s", transport=tr, sleep=lambda s: None)
        self.assertEqual(c.add_columns("SID", "4 People", ["a", "b"]), {"added": ["x"], "existing": 3})
        self.assertEqual(sent[-1], {"action": "add_columns", "sheet_id": "SID", "tab": "4 People", "headers": ["a", "b"]})
        c.share("SID", domain="d.com", emails=["a@d.com"], role="writer")
        self.assertEqual(sent[-1], {"action": "share", "sheet_id": "SID", "role": "writer", "notify": False, "domain": "d.com", "emails": ["a@d.com"]})
        c.ensure_schema("SID")
        self.assertEqual(len([s for s in sent if s["action"] == "add_columns"]), 1 + len(schema.TAB_ORDER))

    def test_share_error_gets_a_hint(self):
        c = sheetmod.SheetClient(url="u", secret="s", sleep=lambda s: None,
                                 transport=lambda *a: (200, {}, b'{"ok":false,"error":"insufficient scope"}'))
        with self.assertRaisesRegex(sheetmod.SheetError, "Share by hand"):
            c.share("SID", domain="d.com")

    def test_people_schema_has_new_columns_and_ready_keys(self):
        for c in ("title_rank", "cap_status", "mv_result", "mv_subresult", "email_verdict", "linkedin_active", "phone_status", "channels"):
            self.assertIn(c, schema.PEOPLE_COLS)
        self.assertEqual(len(schema.PEOPLE_COLS), len(set(schema.PEOPLE_COLS)))
        for tab in (schema.TAB_READY_LI, schema.TAB_READY_EMAIL, schema.TAB_READY_CALLS):
            self.assertEqual(schema.TABS[tab][0], "person_id")  # upsert key
        for c in schema.PEOPLE_COLS:
            self.assertIn(c, pm.TABLE_COLS)

    def test_push_only_changed_rows(self):
        run, b = full_run("push")
        rows = pm.rebuild(run, b)
        fs = FakeSheet()
        r1 = pm.push_to_sheet(run, rows, sc=fs)
        self.assertEqual(r1["people_pushed"], 3)
        self.assertEqual(r1["no_people_pushed"], 1)
        r2 = pm.push_to_sheet(run, rows, sc=fs)
        self.assertEqual(r2["people_pushed"], 0)  # nothing changed, nothing sent
        rows[0]["tier_reason"] = "changed"
        self.assertEqual(pm.push_to_sheet(run, rows, sc=fs)["people_pushed"], 1)


class TestBridgeWorkflow(unittest.TestCase):
    def test_new_actions_are_wired(self):
        import build_sheets_bridge as bsb
        wf = bsb.build()
        names = {n["name"] for n in wf["nodes"]}
        for n in ("Cols Get Props", "Cols Get Header", "Cols Plan", "Cols Has Work?", "Cols Structure", "Cols Write Header", "Share Permission"):
            self.assertIn(n, names)
        route = next(n for n in wf["nodes"] if n["name"] == "Route")
        rules = [r["outputKey"] for r in route["parameters"]["rules"]["values"]]
        self.assertEqual(rules[-2:], ["add_columns", "share"])
        outs = wf["connections"]["Route"]["main"]
        self.assertEqual(len(outs), len(rules) + 1)  # one per rule plus the error fallback
        self.assertEqual(outs[rules.index("add_columns")][0]["node"], "Cols Get Props")
        self.assertEqual(outs[rules.index("share")][0]["node"], "Share Permission")
        self.assertEqual(outs[-1][0]["node"], "Build Response")
        for src, c in wf["connections"].items():
            self.assertIn(src, names)
            for branch in c["main"]:
                for link in branch:
                    self.assertIn(link["node"], names)
        plan = next(n for n in wf["nodes"] if n["name"] == "Plan")["parameters"]["jsCode"]
        self.assertIn("'add_columns', 'share'", plan)
        self.assertNotIn("}}", plan.replace("}}", "} }")) if False else None
        wr = next(n for n in wf["nodes"] if n["name"] == "Cols Write Header")
        self.assertEqual(wr["parameters"]["method"], "PUT")  # values update is a PUT, a POST returns an HTML 404

    def test_activity_patch_is_idempotent_and_validated(self):
        import patch_activity_checker as pac
        js = "const body = {};\nconst cfg = {};\nreturn [{ json: { cfg, action: String(body.action || 'run'), rows: [] } }];"
        new, changed = pac.patched(js)
        self.assertTrue(changed)
        self.assertIn(pac.MARK, new)
        again, changed2 = pac.patched(new)
        self.assertFalse(changed2)
        self.assertEqual(again, new)
        with self.assertRaises(SystemExit):
            pac.patched("no anchor here")

    def test_phone_receiver_workflow_shape(self):
        import deploy_phone_webhook as dpw
        wf = dpw.build("TBL", "idea-launch-apollo-phones-abc")
        self.assertEqual(wf["name"], "Idea Launch | Apollo Phone Webhook")
        self.assertEqual(wf["nodes"][0]["parameters"]["path"], "idea-launch-apollo-phones-abc")
        self.assertEqual(wf["nodes"][2]["parameters"]["dataTableId"]["value"], "TBL")
        self.assertEqual(set(wf["connections"]), {"Webhook", "Flatten"})


class TestApolloAdditions(unittest.TestCase):
    def test_usage_credits_from_response_and_hour_floor(self):
        run = make_run("au")
        tr = FakePeopleApollo(hour_left="5")
        c = client(tr, run)
        c.bulk_match([{"id": "a", "first_name": "x", "organization_name": "o", "domain": "d.com"}])
        self.assertTrue(c.hour_budget_low())
        self.assertEqual(read_jsonl(run.usage_log)[0]["credits"], 1.0)
        self.assertEqual(run.apollo_usage()["apollo_credits"], 1.0)

    def test_placeholder_email_and_normalize(self):
        m = apollo.ApolloClient.normalize_match({"id": "1", "email": "email_not_unlocked@domain.com", "first_name": "A",
                                                 "organization": {"primary_domain": "www.X.com"}})
        self.assertEqual((m["email"], m["org_domain"]), ("", "x.com"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
