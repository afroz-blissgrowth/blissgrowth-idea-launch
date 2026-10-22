"""Phase 4 offline tests: company signals, the two pilot gates, employment exclusions. No network, no credits.
Run together with the other phases:  python3 -I tests/run_tests.py  (run_tests.py sets the temp lists dir first)."""
import copy as stdcopy
import json
import os
import sys
import unittest
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import config  # noqa: E402

import activity as amod  # noqa: E402
import apollo  # noqa: E402
import brief as briefmod  # noqa: E402
import enrich as emod  # noqa: E402
import exclusions  # noqa: E402
import orchestrate  # noqa: E402
import people as pm  # noqa: E402
import pilot  # noqa: E402
import qualify as qmod  # noqa: E402
import schema  # noqa: E402
import signals as sig  # noqa: E402
import stages  # noqa: E402
from run_tests_phase2 import BRIEF, FakePeopleApollo, client, full_run, make_run, person, qualified  # noqa: E402
from util import append_jsonl, read_csv, read_jsonl, write_csv, write_json  # noqa: E402

config.cfg()["signals"]["shared_cache"] = False  # tests share one temp lists dir; the shared-cache test switches it on itself

SIGNALS = [
    {"name": "engineers", "source_field": "engineering", "op": "lte", "value": 200, "strength": "hard"},
    {"name": "sales_share", "source_field": "sales_pct", "op": "gte", "value": 30, "strength": "soft"},
    {"name": "uses_sap", "kind": "text", "description": "Runs SAP or another ERP", "strength": "soft"},
]


def sbrief(slug, signals=None, test=False, **over):
    b = stdcopy.deepcopy(BRIEF)
    b["idea"].update({"test": test, "slug": slug})
    if signals is not None:
        b["signals"] = signals
    b.update(over)
    return b


class FakeOrgApollo:
    """Transport for organizations/bulk_enrich (POST, domains[] in the query) and organizations/enrich (GET, domain)."""
    DATA = {
        "zalando.com": {"id": "z1", "name": "Zalando", "primary_domain": "zalando.com", "estimated_num_employees": 14000,
                        "departmental_head_count": {"engineering": 2000, "operations": 900, "sales": 600}},
        "rubix.com": {"id": "r1", "name": "Rubix DACH", "primary_domain": "rubix.com", "estimated_num_employees": 1200,
                      "departmental_head_count": {"sales": 700, "operations": 200, "finance": 20},
                      "technology_names": ["SAP", "Salesforce"]},
        "small.com": {"id": "s1", "name": "Small", "primary_domain": "small.com", "estimated_num_employees": 40,
                      "departmental_head_count": {"engineering": 5, "sales": 20}},
    }

    def __init__(self, fail=None, credits_key=True):
        self.calls, self.fail, self.credits_key = [], list(fail or []), credits_key

    def __call__(self, method, url, headers, data, timeout):
        u = urlparse(url)
        q = parse_qs(u.query)
        self.calls.append((method, u.path, q, data))
        if self.fail:
            return self.fail.pop(0), {}, b"boom"
        rh = {"x-hourly-requests-left": "5000", "x-minute-requests-left": "150"}
        if u.path.endswith("/organizations/bulk_enrich"):
            doms = q.get("domains[]", [])
            orgs = [self.DATA[d] for d in doms if d in self.DATA]
            out = {"organizations": orgs, "missing_records": len(doms) - len(orgs)}
            if self.credits_key:
                out["credits_consumed"] = len(orgs)
            return 200, rh, json.dumps(out).encode()
        if u.path.endswith("/organizations/enrich"):
            d = (q.get("domain") or [""])[0]
            return 200, rh, json.dumps({"organization": self.DATA.get(d)}).encode()
        return 404, rh, b"{}"


def acct_run(slug, domains, signals=SIGNALS, test=True, flags="keep"):
    """A run with accounts.csv of the given domains (org id o-<domain>)."""
    run = make_run(slug, sbrief(slug, signals, test))
    rows = [{"org_id": "o-" + d, "domain": d, "name": d.split(".")[0].title(), "country": "Germany"} for d in domains]
    write_csv(run.accounts_csv, rows, schema.ACCOUNT_BASE_COLS)
    return run


# =====================================================================================================
class TestSignalDefinitions(unittest.TestCase):
    def test_valid_signals(self):
        self.assertEqual(sig.validate(SIGNALS), [])
        self.assertEqual(sig.validate(None), [])
        self.assertEqual(briefmod.validate(sbrief("v1", SIGNALS)), [])

    def test_invalid_signals_are_all_reported(self):
        bad = [{"name": "a", "source_field": "engineering", "op": "lte", "value": "many", "strength": "hard"},
               {"name": "a", "source_field": "nonsense", "op": "~", "value": 1, "strength": "maybe"},
               {"name": "t", "kind": "text", "description": "uses SAP", "strength": "hard"},
               {"name": "t2", "kind": "text", "strength": "soft"},
               {"name": "b", "source_field": "sales", "op": "between", "value": [9, 3], "strength": "soft"},
               {"strength": "soft"}]
        errs = " | ".join(sig.validate(bad))
        for needle in ("value must be a number", "duplicate signal name", "source_field 'nonsense'", ".op must be one of",
                       "strength must be 'hard' or 'soft'", "cannot be hard", "needs a description", "[low, high]", "name is required"):
            self.assertIn(needle, errs)
        self.assertTrue(briefmod.validate(sbrief("v2", bad)))  # the brief validator uses the same rules

    def test_op_aliases_and_min_max(self):
        self.assertEqual([sig.norm_op(x) for x in ("<", "<=", ">", ">=", "=", "!=", "max", "min", "between")],
                         ["lt", "lte", "gt", "gte", "eq", "ne", "lte", "gte", "between"])
        self.assertIsNone(sig.norm_op("about"))
        s = sig.canonical([{"name": "e", "source_field": "engineering", "op": "max", "value": 5, "strength": "hard"}])
        self.assertEqual(s[0]["op"], "lte")

    def test_brief_rows_show_signals(self):
        rows = {r["key"]: r for r in briefmod.to_rows(sbrief("v3", SIGNALS))}
        self.assertIn("engineering lte 200", rows["signals.1"]["value"])
        self.assertEqual(rows["signals.1"]["note"], "hard")
        self.assertIn("Runs SAP", rows["signals.3"]["value"])

    def test_pilot_size_in_brief_is_checked(self):
        self.assertTrue(any("pilot.accounts_size" in e for e in briefmod.validate(sbrief("v4", pilot={"accounts_size": 50}))))
        self.assertEqual(briefmod.validate(sbrief("v5", pilot={"accounts_size": 12, "people_size": 20})), [])


class TestSignalEvaluation(unittest.TestCase):
    ZAL = {"status": "matched", "employees": 14000, "departments": {"engineering": 2000, "operations": 900, "sales": 600}}
    RUB = {"status": "matched", "employees": 1200, "departments": {"sales": 700, "operations": 200}}

    def test_field_values(self):
        self.assertEqual(sig.field_value(self.ZAL, "employees"), 14000)
        self.assertEqual(sig.field_value(self.ZAL, "engineering"), 2000)
        self.assertEqual(sig.field_value(self.ZAL, "sales_pct"), 4.3)
        self.assertEqual(sig.field_value(self.RUB, "engineering"), 0)  # Apollo lists departments with people: missing means none
        self.assertEqual(sig.field_value(self.RUB, "sales_pct"), 58.3)
        self.assertIsNone(sig.field_value({"status": "matched", "employees": 50, "departments": {}}, "engineering"))  # no data
        self.assertIsNone(sig.field_value({"status": "matched", "employees": None, "departments": {"sales": 3}}, "sales_pct"))
        self.assertIsNone(sig.field_value({"status": "not_found"}, "employees"))
        self.assertIsNone(sig.field_value(None, "employees"))

    def test_zalando_drops_rubix_fits(self):
        """The two companies named in the call."""
        z = sig.evaluate(SIGNALS, self.ZAL)
        self.assertEqual(sig.drop_reason(z), "signal: engineers 2000 > max 200")
        r = sig.evaluate(SIGNALS, self.RUB)
        self.assertEqual(sig.drop_reason(r), "")
        by = {x["name"]: x for x in r}
        self.assertEqual(by["engineers"]["result"], "pass")
        self.assertEqual(by["sales_share"]["result"], "pass")
        self.assertEqual(by["uses_sap"]["result"], "judge")

    def test_soft_failure_never_drops_and_unknown_never_drops(self):
        soft = [dict(SIGNALS[0], strength="soft")]
        self.assertEqual(sig.drop_reason(sig.evaluate(soft, self.ZAL)), "")
        self.assertEqual(sig.evaluate(soft, self.ZAL)[0]["result"], "fail")
        unk = sig.evaluate(SIGNALS, {"status": "matched", "employees": 100, "departments": {}})
        self.assertEqual(sig.drop_reason(unk), "")
        self.assertEqual([x["result"] for x in unk][:2], ["unknown", "unknown"])
        self.assertEqual(sig.drop_reason(sig.evaluate(SIGNALS, None)), "")

    def test_every_op(self):
        rec = {"status": "matched", "employees": 100, "departments": {"engineering": 10}}
        def one(op, value):
            return sig.evaluate([{"name": "e", "source_field": "engineering", "op": op, "value": value, "strength": "hard"}], rec)[0]
        self.assertEqual([one(o, v)["result"] for o, v in (("lt", 11), ("lt", 10), ("lte", 10), ("gt", 9), ("gte", 11), ("eq", 10), ("ne", 10),
                                                            ("between", [5, 10]), ("between", [11, 20]))],
                         ["pass", "fail", "pass", "pass", "fail", "pass", "fail", "pass", "fail"])
        self.assertEqual(one("gte", 11)["detail"], "e 10 < min 11")
        self.assertEqual(one("between", [11, 20])["detail"], "e 10 outside 11 to 20")
        self.assertEqual(sig.rule_text({"op": "lte", "value": 200, "source_field": "engineering"}), "max 200")
        self.assertEqual(sig.rule_text({"op": "gte", "value": 30, "source_field": "sales_pct"}), "min 30%")

    def test_extra_departments_get_their_own_columns(self):
        s = SIGNALS + [{"name": "legal", "source_field": "legal_pct", "op": "lte", "value": 2, "strength": "soft"}]
        self.assertEqual(sig.extra_departments(s), ["legal"])
        self.assertEqual(sig.extra_departments(SIGNALS), [])
        self.assertTrue(sig.needs_apollo({"signals": SIGNALS}))
        self.assertFalse(sig.needs_apollo({"signals": [SIGNALS[2]]}))
        self.assertFalse(sig.needs_apollo({}))


class TestApolloOrgEnrichment(unittest.TestCase):
    def c(self, tr):
        return apollo.ApolloClient(api_key="k", transport=tr, sleep=lambda s: None)

    def test_bulk_enrich_request_and_parse(self):
        tr = FakeOrgApollo()
        res = self.c(tr).org_bulk_enrich(["zalando.com", "rubix.com", "nobody.com"])
        method, path, q, data = tr.calls[0]
        self.assertEqual((method, path.rsplit("/", 2)[-2:]), ("POST", ["organizations", "bulk_enrich"]))
        self.assertEqual(q["domains[]"], ["zalando.com", "rubix.com", "nobody.com"])
        self.assertEqual(res["credits"], 2.0)
        self.assertEqual(res["missing"], 1)
        z = res["orgs"][0]
        self.assertEqual((z["employees"], z["departments"]["engineering"], z["domain"]), (14000, 2000, "zalando.com"))
        self.assertEqual(res["orgs"][1]["technologies"], ["SAP", "Salesforce"])

    def test_credits_fall_back_to_matched_count(self):
        res = self.c(FakeOrgApollo(credits_key=False)).org_bulk_enrich(["zalando.com", "nobody.com"])
        self.assertEqual(res["credits"], 1.0)

    def test_more_than_ten_domains_refused(self):
        with self.assertRaises(apollo.ApolloError):
            self.c(FakeOrgApollo()).org_bulk_enrich(["d%d.com" % i for i in range(11)])
        with self.assertRaises(apollo.ApolloError):
            self.c(FakeOrgApollo()).org_bulk_enrich([])

    def test_single_enrich_is_a_get(self):
        tr = FakeOrgApollo()
        o = self.c(tr).org_enrich("small.com")
        self.assertEqual(tr.calls[0][0], "GET")
        self.assertEqual(tr.calls[0][2]["domain"], ["small.com"])
        self.assertIsNone(tr.calls[0][3])
        self.assertEqual(o["employees"], 40)
        self.assertIsNone(self.c(FakeOrgApollo()).org_enrich("nobody.com"))

    def test_normalize_handles_missing_numbers(self):
        o = apollo.ApolloClient.normalize_org_enrichment({"id": "x", "primary_domain": "www.X.com",
                                                          "departmental_head_count": {"engineering": "7", "sales": None}})
        self.assertEqual((o["domain"], o["employees"], o["departments"]), ("x.com", None, {"engineering": 7}))

    def test_pairing_by_domain_position_and_single_leftover(self):
        a, b = {"domain": "a.com"}, {"domain": "b.com"}
        self.assertEqual(sig.pair_matches(["b.com", "a.com"], {"orgs": [a, b]}), [b, a])
        odd = {"domain": "redirect.com"}
        self.assertEqual(sig.pair_matches(["x.com", "y.com"], {"orgs": [odd], "aligned": [None, odd]}), [None, odd])
        self.assertEqual(sig.pair_matches(["x.com", "a.com"], {"orgs": [odd, a]}), [odd, a])
        self.assertEqual(sig.pair_matches(["x.com"], {"orgs": []}), [None])


class TestSignalsStage(unittest.TestCase):
    def run_it(self, slug, domains, tr=None, **kw):
        run = acct_run(slug, domains)
        sg = sig.Signals(run)
        tr = tr or FakeOrgApollo()
        rep = sg.run_signals(client(tr, run), progress=None, **kw)
        return run, sg, tr, rep

    def test_enriches_once_logs_credits_and_dedupes_domains(self):
        run, sg, tr, rep = self.run_it("s1", ["zalando.com", "rubix.com", "nobody.com", "zalando.com"])
        self.assertEqual((rep["requested"], rep["matched"], rep["not_found"], rep["credits"], rep["calls"]), (3, 2, 1, 2.0, 1))
        self.assertEqual(run.apollo_usage()["apollo_credits"], 2.0)  # logged in apollo-usage.jsonl
        self.assertEqual(sg.records()["nobody.com"]["status"], "not_found")
        rep2 = sg.run_signals(client(tr, run), progress=None)  # nothing left: no call, no credit
        self.assertEqual((rep2["requested"], rep2["calls"]), (0, 0))
        self.assertEqual(len(tr.calls), 1)

    def test_batches_of_ten(self):
        doms = ["d%d.com" % i for i in range(23)]
        run, sg, tr, rep = self.run_it("s2", doms)
        self.assertEqual([len(c[2]["domains[]"]) for c in tr.calls], [10, 10, 3])

    def test_limit_caps_the_spend(self):
        run, sg, tr, rep = self.run_it("s3", ["zalando.com", "rubix.com", "small.com"], limit=2)
        self.assertEqual(rep["requested"], 2)
        self.assertEqual(rep["skipped_by_limit"], 1)
        self.assertEqual(sg.summary(sg.accounts())["pending"], 1)

    def test_shared_cache_means_another_run_never_pays_twice(self):
        config.cfg()["signals"]["shared_cache"] = True
        try:
            if sig.shared_cache_path().exists():
                sig.shared_cache_path().unlink()
            run, sg, tr, rep = self.run_it("s4", ["zalando.com"])
            run2 = acct_run("s4b", ["zalando.com", "rubix.com"])
            tr2 = FakeOrgApollo()
            rep2 = sig.Signals(run2).run_signals(client(tr2, run2), progress=None)
            self.assertEqual(rep2["from_shared_cache"], 1)
            self.assertEqual(tr2.calls[0][2]["domains[]"], ["rubix.com"])
            self.assertEqual(sig.Signals(run2).records()["zalando.com"]["source"], "shared_cache")
            self.assertEqual(sig.Signals(run2).records()["zalando.com"]["credits"], 0)
            self.assertEqual(run2.apollo_usage()["apollo_credits"], 1.0)  # only rubix was paid for
            # a stale cache entry (older than cache_days) is paid for again
            config.cfg()["signals"]["cache_days"] = 0
            run3 = acct_run("s4c", ["zalando.com"])
            tr3 = FakeOrgApollo()
            sig.Signals(run3).run_signals(client(tr3, run3), progress=None)
            self.assertEqual(len(tr3.calls), 1)
        finally:
            config.cfg()["signals"]["shared_cache"] = False
            config.cfg()["signals"]["cache_days"] = 90

    def test_error_is_retried_and_stops_on_fatal(self):
        run = acct_run("s5", ["zalando.com"])
        sg = sig.Signals(run)
        rep = sg.run_signals(client(FakeOrgApollo(fail=[402]), run), progress=None)
        self.assertEqual(rep["errors"], 1)
        self.assertIn("Apollo error", rep["paused"])
        self.assertEqual(sg.records()["zalando.com"]["status"], "error")
        rep = sg.run_signals(client(FakeOrgApollo(), run), progress=None)  # the error is retried, not final
        self.assertEqual(rep["matched"], 1)

    def test_scope_pilot_only_enriches_the_pilot(self):
        run = acct_run("s6", ["zalando.com", "rubix.com", "small.com"])
        write_json(pilot.Gate(run, pilot.ACCOUNTS).sel_path, {"ids": ["o-rubix.com"], "size": 1})
        sg = sig.Signals(run)
        tr = FakeOrgApollo()
        sg.run_signals(client(tr, run), scope="pilot", progress=None)
        self.assertEqual(tr.calls[0][2]["domains[]"], ["rubix.com"])
        self.assertEqual(sg.estimate(sg.scope_rows("pilot"))["domains_to_enrich"], 0)
        self.assertEqual(sg.estimate(sg.scope_rows())["domains_to_enrich"], 2)

    def test_values_columns_and_sheet_records(self):
        run, sg, tr, rep = self.run_it("s7", ["zalando.com", "rubix.com", "nobody.com"])
        rows = {r["domain"]: r for r in sg.accounts()}
        v = sg.values(rows["zalando.com"])
        self.assertEqual((v["employees"], v["engineering"], v["operations"], v["sales"], v["signals_status"]), (14000, 2000, 900, 600, "enriched"))
        self.assertEqual(sg.values(rows["rubix.com"])["engineering"], 0)
        self.assertEqual(sg.values(rows["nobody.com"])["signals_status"], "not_found")
        recs = sg.sheet_records(sg.accounts(), ["legal"])
        self.assertEqual({r["org_id"] for r in recs}, {"o-zalando.com", "o-rubix.com", "o-nobody.com"})
        self.assertIn("dept_legal", recs[0])

    def test_push_uses_add_columns_then_upsert(self):
        run, sg, tr, rep = self.run_it("s8", ["zalando.com"])

        class SC:
            calls = []
            def add_columns(self, sid, tab, headers):
                self.calls.append(("add_columns", tab, list(headers)))
                return {"added": [], "existing": 0}
            def upsert(self, sid, tab, key, recs):
                self.calls.append(("upsert", tab, key, recs))
                return {"updated": 1, "appended": 0, "unknown_columns": []}
        sc = SC()
        out = sg.push_to_sheet(sg.accounts(), run.brief(), sc)
        self.assertEqual(sc.calls[0][:2], ("add_columns", schema.TAB_ACCOUNTS))
        self.assertIn("engineering", sc.calls[0][2])
        self.assertEqual(sc.calls[1][2], "org_id")
        self.assertEqual(sc.calls[1][3][0]["engineering"], 2000)
        self.assertEqual(out["pushed"], 1)

    def test_stage_check_and_require_ready(self):
        run = acct_run("s9", ["zalando.com", "rubix.com"])
        self.assertEqual(stages.check_signals(run, {})["status"], "pending")
        with self.assertRaises(RuntimeError):
            sig.require_ready(run, run.brief())
        sig.Signals(run).run_signals(client(FakeOrgApollo(), run), progress=None)
        self.assertEqual(stages.check_signals(run, {})["status"], "done")
        sig.require_ready(run, run.brief())
        nosig = acct_run("s9b", ["zalando.com"], signals=[SIGNALS[2]])  # a text signal needs no Apollo data
        self.assertEqual(stages.check_signals(nosig, {})["status"], "done")
        sig.require_ready(nosig, nosig.brief())

    def test_signals_run_refuses_without_numeric_signals(self):
        import subprocess
        run = acct_run("s10", ["zalando.com"], signals=None)
        env = dict(os.environ, APOLLO_API_KEY="test-key")
        p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "..", "bin", "signals_run.py"), "run", str(run.dir)],
                           capture_output=True, text=True, env=env)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no numeric signals", p.stdout + p.stderr)


    def test_signals_run_spends_only_on_the_open_pilot(self):
        """Review fix: without --scope, an open accounts pilot limits signals_run plan/run to the pilot accounts."""
        import subprocess
        run = acct_run("s11", ["a%d.com" % i for i in range(30)])
        write_json(run.ledger_path, {"complete": True, "leaves": {}, "limit": 30})
        pilot.start_accounts(run, run.brief(), 10, from_existing=True)
        env = dict(os.environ, APOLLO_API_KEY="test-key")
        p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "..", "bin", "signals_run.py"), "plan", str(run.dir)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("PILOT accounts only", p.stdout)
        self.assertIn('"domains_to_enrich": 10', p.stdout)


class TestQualifyWithSignals(unittest.TestCase):
    def setUp(self):
        self.run = acct_run("q1_%s" % id(self), ["zalando.com", "rubix.com", "small.com", "nobody.com"])
        sig.Signals(self.run).run_signals(client(FakeOrgApollo(), self.run), progress=None)
        self.q = qmod.Qualify(self.run)
        # the website evidence is not under test
        for d in ("zalando.com", "rubix.com", "small.com", "nobody.com"):
            append_jsonl(self.q.evidence_path, {"domain": d, "status": "live", "title": d, "description": "", "text": "x " * 100})

    def test_hard_signal_drops_with_the_reason_and_keeps_the_row(self):
        n = self.q.resolve_signal_drops(self.q.accounts())
        self.assertEqual(n, 1)
        res = self.q.results()
        z = res["o-zalando.com"]
        self.assertEqual((z["flag"], z["qualified"], z["batch"]), ("drop", False, "auto-signal"))
        self.assertEqual(z["reason"], "signal: engineers 2000 > max 200")
        self.assertNotIn("o-rubix.com", res)  # passed
        self.assertNotIn("o-nobody.com", res)  # unknown data never drops
        self.assertEqual(self.q.resolve_signal_drops(self.q.accounts()), 0)  # idempotent

    def test_batches_skip_dropped_and_carry_signals(self):
        self.q.set_spec({"icp_one_liner": "wholesalers", "qualifies": ["a"], "disqualifies": ["b"]})
        out = self.q.make_batches()
        self.assertEqual(out["signal_drops"], 1)
        ids = [i["id"] for p in out["batches"] for i in json.load(open(p))["rows"]]
        self.assertNotIn("o-zalando.com", ids)
        items = {i["id"]: i for p in out["batches"] for i in json.load(open(p))["rows"]}
        s = items["o-rubix.com"]["signals"]
        self.assertEqual((s["values"]["employees"], s["values"]["engineering"], s["status"]), (1200, 0, "enriched"))
        self.assertEqual({r["name"]: r["result"] for r in s["rules"]}, {"engineers": "pass", "sales_share": "pass", "uses_sap": "judge"})
        self.assertEqual(s["technologies"], ["SAP", "Salesforce"])
        self.assertEqual(items["o-nobody.com"]["signals"]["status"], "not_found")
        self.assertEqual(next(r for r in items["o-nobody.com"]["signals"]["rules"] if r["name"] == "engineers")["result"], "unknown")

    def test_prompt_keeps_the_four_blocks_and_adds_the_signals(self):
        text = self.q.set_spec({"icp_one_liner": "w", "qualifies": ["a"], "disqualifies": ["b"]})  # brief signals injected
        for m in qmod.MANDATORY_MARKERS:
            self.assertIn(m, text)
        self.assertIn("Company signals", text)
        self.assertIn("engineers (HARD): engineering max 200", text)
        self.assertIn("sales_share (SOFT): sales_pct min 30%", text)
        self.assertIn("uses_sap (SOFT): Runs SAP", text)
        self.assertIn("unknown means Apollo has no data", text)
        self.assertEqual(json.load(open(self.q.spec_path))["signals"], SIGNALS)
        plain = qmod.build_prompt({"icp_one_liner": "w", "qualifies": ["a"], "disqualifies": ["b"]})
        self.assertNotIn("Company signals", plain)  # no signals, the prompt is exactly as before
        for m in qmod.MANDATORY_MARKERS:
            self.assertIn(m, plain)

    def test_brief_signals_win_over_an_old_spec_copy(self):
        stale = [dict(SIGNALS[0], value=999)]
        text = self.q.set_spec({"icp_one_liner": "w", "qualifies": ["a"], "disqualifies": ["b"], "signals": stale})
        self.assertIn("engineers (HARD): engineering max 200", text)  # review fix: the brief's threshold, not the stale 999
        self.assertNotIn("max 999", text)
        self.assertEqual(json.load(open(self.q.spec_path))["signals"], SIGNALS)

    def test_ingest_cannot_overwrite_a_signal_drop(self):
        self.q.set_spec({"icp_one_liner": "w", "qualifies": ["a"], "disqualifies": ["b"]})
        write_json(self.q.dir / "batches" / "batch-0099.json", {"batch": "batch-0099", "kind": "score",
                   "rows": [{"id": "o-zalando.com"}, {"id": "o-rubix.com"}]})
        self.q.resolve_signal_drops(self.q.accounts())
        (self.q.dir / "batches" / "batch-0099.result.json").write_text(json.dumps([
            {"id": "o-zalando.com", "qualified": True, "confidence": 0.9, "reason": "looks fine"},
            {"id": "o-rubix.com", "qualified": True, "confidence": 0.9, "reason": "sales heavy"}]))
        rep = self.q.ingest_file(str(self.q.dir / "batches" / "batch-0099.result.json"))
        self.assertEqual(rep["missing"], 0)
        res = self.q.results()
        self.assertEqual(res["o-zalando.com"]["flag"], "drop")
        self.assertEqual(res["o-rubix.com"]["flag"], "keep")

    def test_a_changed_threshold_releases_the_row_for_rescoring(self):
        self.q.resolve_signal_drops(self.q.accounts())
        b = self.run.brief()
        b["signals"][0]["value"] = 5000
        write_json(self.run.brief_path, b)
        self.assertEqual(self.q.resolve_signal_drops(self.q.accounts()), 1)
        self.assertEqual(self.q.results()["o-zalando.com"]["flag"], "error")
        self.assertIn("o-zalando.com", [r["org_id"] for r in self.q.pending_rows(self.q.accounts())])

    def test_soft_only_signals_never_drop(self):
        b = self.run.brief()
        b["signals"] = [dict(SIGNALS[0], strength="soft")]
        write_json(self.run.brief_path, b)
        self.assertEqual(self.q.resolve_signal_drops(self.q.accounts()), 0)

    def test_qualify_refuses_until_signals_are_enriched(self):
        run = acct_run("q2", ["zalando.com"])
        q = qmod.Qualify(run)
        q.set_spec({"icp_one_liner": "w", "qualifies": ["a"], "disqualifies": ["b"]})
        with self.assertRaises(RuntimeError) as cm:
            q.make_batches()
        self.assertIn("signals are not enriched", str(cm.exception))

    def test_sample_excludes_hard_dropped(self):
        self.q.set_spec({"icp_one_liner": "w", "qualifies": ["a"], "disqualifies": ["b"]})
        p = self.q.sample_batch(1, 10)
        ids = [i["id"] for i in json.load(open(p))["rows"]]
        self.assertNotIn("o-zalando.com", ids)
        self.assertIn("signals", json.load(open(p))["rows"][0])

    def test_finalize_writes_signal_columns(self):
        self.q.resolve_signal_drops(self.q.accounts())
        self.q.finalize(push=False)
        rows = {r["domain"]: r for r in read_csv(self.q.qualified_csv)}
        self.assertEqual((rows["zalando.com"]["engineering"], rows["zalando.com"]["employees"], rows["zalando.com"]["flag"]), ("2000", "14000", "drop"))
        self.assertEqual(rows["zalando.com"]["reason"], "signal: engineers 2000 > max 200")
        self.assertEqual(rows["nobody.com"]["signals_status"], "not_found")


# =====================================================================================================
class TestPilotHelpers(unittest.TestCase):
    def test_norm_review(self):
        self.assertEqual([pilot.norm_review(x) for x in ("Approved", " y ", "KEEP", "reject", "No", "not fit", "", None, "maybe")],
                         ["approve", "approve", "approve", "reject", "reject", "reject", "", "", None])

    def test_sizes(self):
        self.assertEqual(pilot.check_size(10), 10)
        self.assertEqual(pilot.check_size(20), 20)
        for bad in (9, 21, "15", True, None):
            with self.assertRaises(pilot.PilotError):
                pilot.check_size(bad)
        self.assertEqual(pilot.default_size({}, pilot.ACCOUNTS), 15)  # config default
        self.assertEqual(pilot.default_size({"pilot": {"people_size": 12}}, pilot.PEOPLE), 12)

    def test_pick_people_spreads_companies_and_tiers_and_is_deterministic(self):
        rows = [{"person_id": "p%d_%d" % (o, i), "org_id": "o%d" % o, "tier": "T1" if i < 2 else "T2"} for o in range(12) for i in range(4)]
        a = pilot.pick_people(rows, 15, "seed")
        self.assertEqual(a, pilot.pick_people(rows, 15, "seed"))
        self.assertEqual(len(a), 15)
        orgs = {r["org_id"] for r in rows if r["person_id"] in a}
        self.assertEqual(len(orgs), 12)  # at least one per company before anyone gets a second
        tiers = [r["tier"] for r in rows if r["person_id"] in a]
        self.assertTrue(5 <= tiers.count("T1") <= 10)
        self.assertEqual(len(pilot.pick_people(rows[:5], 15, "s")), 5)  # fewer people than the pilot size

    def test_gate_enabled_switches(self):
        self.assertTrue(pilot.gate_enabled({}))
        self.assertFalse(pilot.gate_enabled({"pilot": {"enabled": False}}))

    def test_override_rules(self):
        self.assertEqual(pilot.apply_override("keep", None, "r"), ("keep", None, "r"))
        f, q, r = pilot.apply_override("keep", {"review": "reject", "note": "too big"}, "fits")
        self.assertEqual((f, q), ("drop", False))
        self.assertIn("rejected (too big)", r)
        f, q, r = pilot.apply_override("drop", {"review": "approve", "note": ""}, "signal: engineers 2000 > max 200")
        self.assertEqual((f, q), ("keep", True))
        self.assertIn("AI had dropped", r)
        self.assertEqual(pilot.apply_override("dead_site", {"review": "approve"}, "x")[0], "dead_site")  # a dead site stays dead
        self.assertEqual(pilot.apply_override("review", {"review": "approve"}, "x")[0], "review")


def pilot_run(slug, n=12, test=True, signals=SIGNALS, enrich=True):
    """A run with n pilot accounts selected (and optionally enriched with signals and qualified)."""
    doms = ["acct%02d.com" % i for i in range(n)]
    run = acct_run(slug, doms, signals=signals, test=test)
    write_json(run.ledger_path, {"limit": n, "complete": False, "leaves": {}})
    write_json(pilot.Gate(run, pilot.ACCOUNTS).sel_path, {"ids": ["o-" + d for d in doms], "size": n})
    return run, doms


def score_all(run, doms, flag="keep"):
    for d in doms:
        append_jsonl(run.qdir / "results.jsonl", {"org_id": "o-" + d, "domain": d, "name": d, "flag": flag, "qualified": flag != "drop",
                                                  "confidence": 0.9, "reason": "ai says " + flag, "batch": "batch-0001"})


def enrich_all(run):
    for r in read_csv(run.accounts_csv):
        append_jsonl(sig.Signals(run).path, {"domain": r["domain"], "status": "matched", "employees": 100,
                                             "departments": {"engineering": 10, "sales": 50}, "enriched_at": "2026-10-21T10:00:00Z"})


class TestAccountsGateStateMachine(unittest.TestCase):
    def state(self, run):
        return pilot.accounts_state(run)["state"]

    def test_full_walk(self):
        run, doms = pilot_run("g1")
        g = pilot.Gate(run, pilot.ACCOUNTS)
        self.assertEqual(self.state(run), "selected")  # numeric signals in the brief, nothing enriched
        self.assertEqual(pilot.next_action(run, "accounts")["cmds"][0][:2], ("signals_run.py", "run"))
        self.assertIn("--scope", pilot.next_action(run, "accounts")["cmds"][0])
        enrich_all(run)
        self.assertEqual(self.state(run), "enriched")
        na = pilot.next_action(run, "accounts")
        self.assertEqual((na["kind"], na["cmds"]), ("claude", []))
        self.assertIn("/iv-qualify", na["instruction"])
        score_all(run, doms)
        self.assertEqual(self.state(run), "scored")
        self.assertEqual(pilot.next_action(run, "accounts")["cmds"][0][:3], ("pilot_run.py", "accounts", "request-review"))
        g.mark_requested()
        self.assertEqual(self.state(run), "awaiting_review")
        self.assertEqual(pilot.next_action(run, "accounts")["kind"], "user")
        for i, d in enumerate(doms[:-1]):
            g.record("o-" + d, "approve" if i % 3 else "reject", "n", simulated=True)
        self.assertEqual(self.state(run), "awaiting_review")  # one row has no mark yet
        with self.assertRaises(pilot.PilotError) as cm:
            g.approve("go", simulated=True)
        self.assertIn("1 of 12", str(cm.exception))
        g.record("o-" + doms[-1], "approve", "", simulated=True)
        self.assertEqual(self.state(run), "reviewed")
        na = pilot.next_action(run, "accounts")
        self.assertEqual(na["kind"], "user")
        self.assertIn("approve", na["instruction"])
        self.assertFalse(pilot.gate_open_for_full_pull(run))
        a = g.approve("user said go (SIMULATED test)", simulated=True)
        self.assertTrue(a["simulated"])
        self.assertEqual(self.state(run), "approved")
        self.assertTrue(pilot.gate_open_for_full_pull(run))
        self.assertEqual(pilot.next_action(run, "accounts")["kind"], "done")
        # an approval is tied to the marks: change one and the gate is open again
        g.record("o-" + doms[0], "approve", "changed my mind", simulated=True)
        self.assertEqual(self.state(run), "stale")
        self.assertFalse(pilot.gate_open_for_full_pull(run))
        self.assertEqual(stages.check_pilot_accounts(run, {})["status"], "partial")

    def test_approval_needs_a_note_and_real_runs_refuse_simulation(self):
        run, doms = pilot_run("g2", test=False)
        enrich_all(run)
        score_all(run, doms)
        g = pilot.Gate(run, pilot.ACCOUNTS)
        with self.assertRaises(pilot.PilotError):
            g.record("o-" + doms[0], "approve", simulated=True)  # simulated reviews: TEST runs only
        for d in doms:
            g.record("o-" + d, "approve")
        with self.assertRaises(pilot.PilotError):
            g.approve("")
        with self.assertRaises(pilot.PilotError):
            g.approve("go", simulated=True)
        g.mark_requested()
        a = g.approve("Afroz said go")
        self.assertFalse(a["simulated"])
        self.assertEqual(self.state(run), "approved")

    def test_a_simulated_approval_never_completes_a_real_run(self):
        run, doms = pilot_run("g3", test=True)
        enrich_all(run)
        score_all(run, doms)
        g = pilot.Gate(run, pilot.ACCOUNTS)
        g.mark_requested()
        for d in doms:
            g.record("o-" + d, "approve", simulated=True)
        g.approve("sim", simulated=True)
        b = run.brief()
        b["idea"]["test"] = False  # the same files, but now a real brief
        write_json(run.brief_path, b)
        self.assertEqual(self.state(run), "simulated")
        self.assertFalse(pilot.gate_open_for_full_pull(run))

    def test_unknown_review_value_is_refused(self):
        run, doms = pilot_run("g4")
        with self.assertRaises(pilot.PilotError):
            pilot.Gate(run, pilot.ACCOUNTS).record("o-" + doms[0], "maybe")
        with self.assertRaises(pilot.PilotError):
            pilot.Gate(run, pilot.ACCOUNTS).record("o-stranger.com", "approve")

    def test_legacy_skipped_disabled_and_not_started(self):
        # accounts pulled in full before the gate existed: the gate does not apply
        legacy = acct_run("g5", ["a.com"])
        write_json(legacy.ledger_path, {"complete": True, "leaves": {}})
        self.assertEqual(self.state(legacy), "legacy")
        self.assertTrue(pilot.gate_open_for_full_pull(legacy))
        self.assertEqual(stages.check_pilot_accounts(legacy, {})["status"], "done")
        # a limit test pull is NOT legacy: the pilot has not been drawn
        lim = acct_run("g6", ["a.com"])
        write_json(lim.ledger_path, {"limit": 25, "complete": False, "leaves": {}})
        self.assertEqual(self.state(lim), "not_started")
        self.assertEqual(stages.check_pilot_accounts(lim, {})["status"], "pending")
        self.assertEqual(pilot.next_action(lim, "accounts")["cmds"][0], ("pilot_run.py", "accounts", "start", lim.dir.name))
        # nothing at all
        fresh = make_run("g7", sbrief("g7", SIGNALS, True))
        self.assertEqual(self.state(fresh), "not_started")
        self.assertFalse(pilot.gate_open_for_full_pull(fresh))
        # a recorded user skip
        pilot.Gate(fresh, pilot.ACCOUNTS).skip("Afroz: small idea, no pilot")
        self.assertEqual(self.state(fresh), "skipped")
        self.assertTrue(pilot.gate_open_for_full_pull(fresh))
        self.assertEqual(stages.check_pilot_accounts(fresh, {})["status"], "skipped")
        with self.assertRaises(pilot.PilotError):
            pilot.Gate(make_run("g7b", sbrief("g7b")), pilot.ACCOUNTS).skip("")
        # switched off in the brief
        off = make_run("g8", sbrief("g8", SIGNALS, True, pilot={"enabled": False}))
        self.assertEqual(self.state(off), "skipped")

    def test_no_numeric_signals_goes_straight_to_qualify(self):
        run, doms = pilot_run("g9", signals=None)
        self.assertEqual(self.state(run), "enriched")  # nothing to enrich first
        self.assertIn("/iv-qualify", pilot.next_action(run, "accounts")["instruction"])

    def test_sheet_marks_are_merged_and_blank_never_erases_chat(self):
        run, doms = pilot_run("g10")
        g = pilot.Gate(run, pilot.ACCOUNTS)
        g.record("o-" + doms[0], "approve", "chat note")
        rows = [{"org_id": "o-" + doms[0], "pilot_review": "", "pilot_note": ""},  # blank: keep the chat mark
                {"org_id": "o-" + doms[1], "pilot_review": "Rejected", "pilot_note": "too big"},
                {"org_id": "o-" + doms[2], "pilot_review": "perhaps", "pilot_note": ""},
                {"org_id": "o-notpilot", "pilot_review": "approve", "pilot_note": ""}]
        rep = g.merge_sheet_rows(rows)
        self.assertEqual(rep, {"changed": 1, "invalid": ["o-" + doms[2]]})
        rv = g.reviews()
        self.assertEqual((rv["o-" + doms[0]]["review"], rv["o-" + doms[0]]["note"]), ("approve", "chat note"))
        self.assertEqual((rv["o-" + doms[1]]["review"], rv["o-" + doms[1]]["source"], rv["o-" + doms[1]]["note"]), ("reject", "sheet", "too big"))
        self.assertEqual(g.merge_sheet_rows(rows)["changed"], 0)  # idempotent

    def test_seeds_only_for_approved_pilot_accounts_under_a_valid_approval(self):
        run, doms = pilot_run("g11")
        enrich_all(run)
        score_all(run, doms)
        g = pilot.Gate(run, pilot.ACCOUNTS)
        g.mark_requested()
        for i, d in enumerate(doms):
            g.record("o-" + d, "reject" if i < 3 else "approve", "", simulated=True)
        self.assertEqual(pilot.seeds(run), {})  # not approved yet
        g.approve("sim", simulated=True)
        s = pilot.seeds(run)
        self.assertEqual(len(s), len(doms) - 3)
        self.assertEqual(set(s.values()), {"yes (SIMULATED)"})
        csv = read_csv(run.dir / "pilot" / "seeds.csv")
        self.assertEqual(len(csv), len(doms) - 3)
        self.assertNotIn("o-" + doms[0], [r["org_id"] for r in csv])
        g.record("o-" + doms[5], "reject", "", simulated=True)  # stale approval: no seeds
        self.assertEqual(pilot.seeds(run), {})

    def test_review_decides_finalize_and_is_never_a_deletion(self):
        run, doms = pilot_run("g12")
        enrich_all(run)
        for i, d in enumerate(doms):
            score_all(run, [d], "drop" if i == 1 else "keep")
        q = qmod.Qualify(run)
        g = pilot.Gate(run, pilot.ACCOUNTS)
        g.record("o-" + doms[0], "reject", "wrong industry", simulated=True)
        g.record("o-" + doms[1], "approve", "actually a fit", simulated=True)
        g.record("o-" + doms[2], "approve", "", simulated=True)
        q.finalize(push=False)
        rows = {r["org_id"]: r for r in read_csv(q.qualified_csv)}
        self.assertEqual(len(rows), len(doms))  # no row is deleted
        self.assertEqual(rows["o-" + doms[0]]["flag"], "drop")
        self.assertIn("pilot review SIMULATED rejected (wrong industry)", rows["o-" + doms[0]]["reason"])
        self.assertEqual(rows["o-" + doms[1]]["flag"], "keep")  # the human put it back
        self.assertEqual(rows["o-" + doms[2]]["flag"], "keep")
        self.assertEqual((rows["o-" + doms[0]]["pilot"], rows["o-" + doms[0]]["pilot_review"]), ("yes", "reject"))
        self.assertEqual(rows["o-" + doms[3]]["pilot_review"], "")

    def test_summary_patterns(self):
        run, doms = pilot_run("g13", n=10)
        enrich_all(run)
        score_all(run, doms)
        g = pilot.Gate(run, pilot.ACCOUNTS)
        for i, d in enumerate(doms):
            g.record("o-" + d, "reject" if i < 4 else "approve", "too many engineers" if i < 4 else "", simulated=True)
        s = pilot.accounts_summary(run)
        self.assertEqual(s["counts"], {"size": 10, "approve": 6, "reject": 4, "pending": 0})
        self.assertEqual(s["agreement"]["ai_keep_human_reject"], 4)
        self.assertEqual(s["signal_ranges_by_review"]["engineering"]["reject"]["median"], 10)
        self.assertEqual(len(s["rejected"]), 4)
        text = pilot.format_accounts_summary(s)
        self.assertIn("AI keep + REJECTED 4 (AI too loose)", text)
        self.assertIn("too many engineers", text)

    def test_size_is_enforced_when_starting(self):
        run = make_run("g14", sbrief("g14", SIGNALS, True))
        for bad in (5, 25):
            with self.assertRaises(pilot.PilotError):
                pilot.start_accounts(run, run.brief(), bad, from_existing=True)

    def test_start_from_existing_draws_once(self):
        run = acct_run("g15", ["a%d.com" % i for i in range(30)])
        write_json(run.ledger_path, {"complete": True, "leaves": {}})
        ids = pilot.start_accounts(run, run.brief(), 10, from_existing=True)
        self.assertEqual(len(ids), 10)
        self.assertEqual(ids, pilot.Gate(run, pilot.ACCOUNTS).ids())
        with self.assertRaises(pilot.PilotError):
            pilot.start_accounts(run, run.brief(), 10, from_existing=True)  # never re-drawn
        self.assertEqual(self.state_of(run), "selected")

    def state_of(self, run):
        return pilot.accounts_state(run)["state"]

    def test_start_pulls_a_limit_pull_from_apollo(self):
        """start_accounts calls the existing limit pull (no counting, 1 page per filter set) and records the ids."""
        import accounts as accmod
        run = make_run("g16", sbrief("g16", None, True))
        seen = {}

        class FakeAcc(FakeOrgApollo):
            def __call__(self, method, url, headers, data, timeout):
                seen["url"] = url
                body = {"organizations": [{"id": "o%d" % i, "name": "N%d" % i, "primary_domain": "n%d.com" % i} for i in range(12)],
                        "accounts": [], "pagination": {"total_entries": 5000, "total_pages": 50}}
                return 200, {"x-minute-requests-left": "100"}, json.dumps(body).encode()
        ids = pilot.start_accounts(run, run.brief(), 10, client=client(FakeAcc(), run), push=False)
        self.assertEqual(len(ids), 10)
        self.assertEqual(read_json_ledger(run)["limit"], 10)
        self.assertIn("per_page=10", seen["url"])
        self.assertEqual(stages.check_accounts(run, {})["status"], "partial")
        self.assertIn("pilot of 10 accounts only", stages.check_accounts(run, {})["detail"])
        self.assertFalse(pilot.gate_open_for_full_pull(run))


def read_json_ledger(run):
    return json.load(open(run.ledger_path))


class TestPeopleGate(unittest.TestCase):
    def setUp(self):
        self.run, self.b = full_run("pg1_%s" % id(self))
        # full_run enriched everybody before the gate existed: that is the legacy case. Start from a pre-enrichment copy instead.
        tb = stdcopy.deepcopy(self.b)
        tb["idea"]["test"] = True  # simulated reviews are allowed on TEST runs only
        self.pre = make_run("pg2_%s" % id(self), tb)
        write_json(self.pre.ledger_path, {"complete": True, "leaves": {}})
        qualified(self.pre, [("o1", "a.com", "A Ltd", "keep"), ("o2", "b.com", "B Ltd", "keep")])
        (self.pre.qdir / "prompt.md").write_text("x")
        tr = FakePeopleApollo({"o1": [person("p%d" % i, "o1", "COO" if i < 3 else "Quality Manager") for i in range(1, 6)],
                               "o2": [person("q%d" % i, "o2", "Owner") for i in range(1, 4)]})
        pm.run_search(self.pre, self.b, client(tr, self.pre), progress=None)
        from tier import Tier
        t = Tier(self.pre)
        for pid, tt in [("p%d" % i, "T1" if i < 3 else "T2") for i in range(1, 6)] + [("q%d" % i, "T1") for i in range(1, 4)]:
            append_jsonl(t.results_path, {"person_id": pid, "tier": tt, "reason": "r"})
        pm.rebuild(self.pre, self.b)

    def test_legacy_when_enrichment_already_happened(self):
        self.assertEqual(pilot.people_state(self.run)["state"], "legacy")
        self.assertTrue(pilot.gate_open_for_enrich(self.run))

    def test_walk_and_rejected_people_are_never_enriched(self):
        run = self.pre
        self.assertEqual(pilot.people_state(run)["state"], "not_started")
        self.assertFalse(pilot.gate_open_for_enrich(run))
        self.assertEqual(pilot.next_action(run, "people")["cmds"][0], ("pilot_run.py", "people", "start", run.dir.name))
        with self.assertRaises(pilot.PilotError):
            pilot.start_people(run, run.brief(), 5)  # below 10
        sel = [r for r in pm.load_table(run) if r["cap_status"] == "selected"]
        self.assertGreaterEqual(len(sel), 4)
        ids = pilot.start_people(run, run.brief(), 10)
        self.assertEqual(len(ids), len(sel))  # fewer selected people than the pilot size: all of them
        self.assertEqual(pilot.people_state(run)["state"], "scored")
        g = pilot.Gate(run, pilot.PEOPLE)
        self.assertEqual(pilot.next_action(run, "people")["cmds"][0][:3], ("pilot_run.py", "people", "request-review"))
        g.mark_requested()
        self.assertEqual(pilot.people_state(run)["state"], "awaiting_review")
        self.assertEqual(pilot.next_action(run, "people")["kind"], "user")
        for i, pid in enumerate(ids):
            g.record(pid, "reject" if i == 0 else "approve", "wrong title" if i == 0 else "", simulated=True)
        g.approve("sim", simulated=True)
        self.assertEqual(pilot.people_state(run)["state"], "approved")
        self.assertTrue(pilot.gate_open_for_enrich(run))
        rows = pm.rebuild(run, run.brief())
        rej = next(r for r in rows if r["person_id"] == ids[0])
        self.assertEqual((rej["pilot"], rej["pilot_review"], rej["channels"]), ("yes", "reject", ""))
        self.assertIn("pilot_rejected: pilot review rejected (wrong title)", rej["exclusion_reason"])
        todo = [r["person_id"] for r in emod.todo_people(rows)]
        self.assertNotIn(ids[0], todo)  # no credit is spent on a person a human rejected
        self.assertEqual(len(todo), len(ids) - 1)
        tr = FakePeopleApollo()
        rep = emod.run_enrich(run, client(tr, run), progress=None)
        self.assertEqual(rep["requested"], len(ids) - 1)
        rows = pm.load_table(run)
        self.assertEqual(next(r for r in rows if r["person_id"] == ids[0])["enrich_status"], "")
        # the rejected row never blocks the stages that wait for enrichment: everybody else is enriched, so the stage is not "pending"
        pm.rebuild(run, run.brief())
        self.assertIn("%d of %d selected enriched" % (len(ids) - 1, len(ids) - 1),
                      stages.check_enrich_verify(run, {"tier": {"status": "done"}})["detail"])

    def test_pilot_columns_survive_a_rebuild_and_blank_marks_are_not_pushed(self):
        run = self.pre
        ids = pilot.start_people(run, run.brief(), 10)
        pilot.Gate(run, pilot.PEOPLE).record(ids[0], "approve", "good", simulated=True)
        rows = pm.rebuild(run, run.brief())
        got = {r["person_id"]: r for r in rows}
        self.assertEqual((got[ids[0]]["pilot_review"], got[ids[0]]["pilot_note"]), ("approve", "good"))
        self.assertEqual(got[ids[1]]["pilot"], "yes")

        class SC:
            def __init__(self):
                self.recs = []
            def ensure_schema(self, sid, tabs=None):
                return {}
            def upsert(self, sid, tab, key, recs):
                self.recs += [dict(r) for r in recs] if tab == schema.TAB_PEOPLE else []
                return {"updated": 0, "appended": len(recs), "skipped": 0, "unknown_columns": []}
        sc = SC()
        pm.push_to_sheet(run, rows, sc=sc, include_no_people=False, force=True)
        by = {r["person_id"]: r for r in sc.recs}
        self.assertEqual(by[ids[0]]["pilot_review"], "approve")
        self.assertNotIn("pilot_review", by[ids[1]])  # blank locally: not sent, a mark typed in the sheet is kept

    def test_second_draw_refused_and_skip_is_recorded(self):
        run = self.pre
        pilot.start_people(run, run.brief(), 10)
        with self.assertRaises(pilot.PilotError):
            pilot.start_people(run, run.brief(), 10)
        pilot.Gate(run, pilot.PEOPLE).skip("user decided no pilot")
        self.assertEqual(pilot.people_state(run)["state"], "skipped")
        self.assertTrue(pilot.gate_open_for_enrich(run))

    def test_enrich_script_is_blocked_by_the_gate(self):
        import subprocess
        env = dict(os.environ, APOLLO_API_KEY="test-key")
        p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "..", "bin", "enrich_verify.py"), "enrich", str(self.pre.dir)],
                           capture_output=True, text=True, env=env)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("people pilot gate", p.stdout + p.stderr)
        dry = subprocess.run([sys.executable, "-I", os.path.join(HERE, "..", "bin", "enrich_verify.py"), "enrich", str(self.pre.dir), "--dry-run"],
                             capture_output=True, text=True, env=env)
        self.assertEqual(dry.returncode, 0, dry.stderr)  # an estimate is always allowed

    def test_accounts_pull_script_is_blocked_by_the_gate(self):
        import subprocess
        run = make_run("pg3_%s" % id(self), sbrief("pg3", None, True))
        env = dict(os.environ, APOLLO_API_KEY="test-key")
        p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "..", "bin", "accounts_pull.py"), str(run.dir)],
                           capture_output=True, text=True, env=env)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("blocked by the pilot gate", p.stdout + p.stderr)


class TestOrchestratorGates(unittest.TestCase):
    def test_registry_places_the_gates(self):
        n = stages.names()
        self.assertLess(n.index("brief"), n.index("pilot_accounts"))
        self.assertLess(n.index("pilot_accounts"), n.index("accounts"))  # no full pull before the pilot gate
        self.assertLess(n.index("accounts"), n.index("signals"))
        self.assertLess(n.index("signals"), n.index("qualify"))
        self.assertLess(n.index("tier"), n.index("pilot_people"))
        self.assertLess(n.index("pilot_people"), n.index("enrich_verify"))  # no enrichment credit before the people gate
        self.assertIn("pilot_accounts", stages.required_names())

    def test_drive_stops_at_the_accounts_review_and_never_pulls_in_full(self):
        run, doms = pilot_run("og1")
        enrich_all(run)
        score_all(run, doms)
        pilot.Gate(run, pilot.ACCOUNTS).mark_requested()
        ran = []
        res = orchestrate.drive(run, execute=True, runner=lambda a: (ran.append(a) or (0, "ok")), log=lambda *_: None)
        self.assertEqual((res["state"], res["stage"], res["needs"]), ("stopped", "pilot_accounts", "user"))
        self.assertIn("human review", res["instruction"])
        self.assertEqual(ran, [])
        self.assertFalse(any("accounts_pull" in " ".join(a) for a in ran))

    def test_drive_runs_the_pilot_steps_then_stops_for_claude(self):
        run = make_run("og2", sbrief("og2", SIGNALS, True))
        ran = []
        res = orchestrate.drive(run, execute=False, log=lambda *_: None)
        self.assertEqual((res["state"], res["stage"]), ("dry", "pilot_accounts"))
        write_json(pilot.Gate(run, pilot.ACCOUNTS).sel_path, {"ids": ["o-a.com"], "size": 1})
        write_csv(run.accounts_csv, [{"org_id": "o-a.com", "domain": "a.com", "name": "A"}], schema.ACCOUNT_BASE_COLS)
        write_json(run.ledger_path, {"limit": 1, "complete": False, "leaves": {}})
        cmds = orchestrate.auto_commands("pilot_accounts", run, "partial")
        self.assertTrue(any("signals_run.py" in " ".join(c) and "pilot" in c for c in cmds))
        enrich_all(run)
        res = orchestrate.drive(run, execute=True, runner=lambda a: (ran.append(a) or (0, "")), log=lambda *_: None)
        self.assertEqual((res["state"], res["stage"], res["needs"]), ("stopped", "pilot_accounts", "claude"))
        self.assertIn("/iv-qualify", res["instruction"])

    def test_projection_labels_the_gate_stops(self):
        run, doms = pilot_run("og3")
        enrich_all(run)
        score_all(run, doms)
        pilot.Gate(run, pilot.ACCOUNTS).mark_requested()
        by = {r["stage"]: r for r in orchestrate.projection(run)}
        self.assertEqual(by["pilot_accounts"]["kind"], "user")
        self.assertTrue(by["pilot_accounts"]["action"].startswith("STOP for the user"))
        self.assertTrue(by["accounts"]["action"].startswith("AUTO"))  # the full pull is queued AFTER the gate

    def test_people_gate_stops_before_enrichment(self):
        t = TestPeopleGate("test_legacy_when_enrichment_already_happened")
        t.setUp()
        run = t.pre
        write_json(run.sheet_path, {"sheet_id": "S1", "url": "x"})
        ids = pilot.start_people(run, run.brief(), 10)
        pilot.Gate(run, pilot.PEOPLE).mark_requested()
        st = {s: {"status": "done", "detail": ""} for s in stages.names()}
        st["pilot_people"] = stages.check_pilot_people(run, {"tier": {"status": "done"}})
        st["enrich_verify"] = {"status": "pending", "detail": "nobody enriched"}
        orig = type(run).stage_status
        type(run).stage_status = lambda self: st
        try:
            ran = []
            res = orchestrate.drive(run, execute=True, runner=lambda a: (ran.append(a) or (0, "")), log=lambda *_: None)
        finally:
            type(run).stage_status = orig
        self.assertEqual((res["state"], res["stage"], res["needs"]), ("stopped", "pilot_people", "user"))
        self.assertEqual(ran, [])

    def test_estimate_for_signals(self):
        run = acct_run("og5", ["a.com", "b.com"])
        self.assertIn("2 companies to enrich = up to 2 Apollo credits", orchestrate.estimate(run, "signals"))

    def test_summary_shows_signals_and_gates(self):
        run, doms = pilot_run("og6")
        enrich_all(run)
        text = run.write_summary()
        body = open(run.summary_path).read()
        self.assertIn("## Signals", body)
        self.assertIn("## Pilot gates", body)
        self.assertIn("accounts: pilot of", body)


# =====================================================================================================
class TestKeywordExclusions(unittest.TestCase):
    def hit(self, **fields):
        return [c for c, _ in exclusions.keyword_reasons(dict({"headline": "", "title": "", "current_title": ""}, **fields))]

    def test_the_phrases_from_the_call(self):
        cases = {"garden_leave": "On garden leave until March", "retired": "Retired CFO", "career_break": "Career break | ex-banker",
                 "open_to_work": "Open to Work | Supply chain", "between_roles": "Between roles, advisor"}
        for cat, text in cases.items():
            self.assertIn(cat, self.hit(headline=text), text)
        self.assertIn("open_to_work", self.hit(headline="Head of Ops #OpenToWork"))
        self.assertIn("retired", self.hit(title="Retired"))
        self.assertIn("garden_leave", self.hit(current_title="Gardening leave"))

    def test_working_people_are_not_excluded(self):
        for text in ("Founder, ex-Google, building supply chain software", "CTO at Acme | Looking for talented engineers",
                     "Operating partner, formerly at Bain", "We are hiring: open positions in sales", "Head of Retirement Products at Aviva Life"):
            self.assertEqual(self.hit(headline=text), [], text)

    def test_former_and_ex_only_at_the_start(self):
        self.assertIn("former", self.hit(title="Former CTO"))
        self.assertIn("former", self.hit(title="Ex-CEO"))
        self.assertIn("former", self.hit(current_title="Former Head of Operations"))
        self.assertEqual(self.hit(headline="CEO at Foo (ex-Google)"), [])
        # review fix: a headline that STARTS with ex- or former is usually a working person's pedigree
        self.assertEqual(self.hit(headline="Ex-Google | CEO at Acme"), [])
        self.assertEqual(self.hit(headline="Former McKinsey, now COO at Acme"), [])

    def test_in_transition_only_as_a_status(self):
        self.assertIn("between_roles", self.hit(headline="In transition | Supply chain leader"))
        self.assertIn("between_roles", self.hit(headline="COO, currently in transition"))
        self.assertEqual(self.hit(headline="Helping wholesalers in transition to digital"), [])

    def test_seeking_and_looking_for_phrases(self):
        self.assertIn("seeking", self.hit(headline="Seeking new opportunities in logistics"))
        self.assertIn("looking_for", self.hit(headline="Looking for my next role in ops"))
        self.assertIn("looking_for", self.hit(headline="Looking for a new challenge"))

    def test_custom_lists_come_from_config(self):
        groups = {"mine": {"fields": ["headline"], "keywords": ["on sabbatical", "re:^ex-\\w"]}}
        self.assertEqual(exclusions.keyword_reasons({"headline": "On Sabbatical"}, groups)[0][0], "mine")
        self.assertEqual(exclusions.keyword_reasons({"title": "on sabbatical"}, groups), [])  # field not listed
        self.assertEqual(exclusions.keyword_reasons({"headline": "Ex-Google PM"}, groups)[0][0], "mine")

    def test_defaults_are_in_config_json(self):
        g = config.get("exclusions.groups")
        for name in ("garden_leave", "retired", "career_break", "open_to_work", "between_roles", "seeking", "looking_for", "former"):
            self.assertIn(name, g)
        self.assertIn("#opentowork", g["open_to_work"]["keywords"])


class TestStructuredExclusions(unittest.TestCase):
    HIST_NONE = [{"org": "Old Co", "title": "COO", "current": False, "start": "2018-01-01", "end": "2025-12-31"}]
    HIST_OK = [{"org": "Rubix DACH GmbH", "title": "COO", "current": True, "start": "2019-01-01", "end": ""}]

    def test_apollo_no_current_position(self):
        r = exclusions.apollo_reasons(self.HIST_NONE, "Rubix")
        self.assertEqual([c for c, _ in r], ["apollo_no_current_position"])
        self.assertEqual(exclusions.apollo_reasons(self.HIST_OK, "Rubix"), [])
        self.assertEqual(exclusions.apollo_reasons([], "Rubix"), [])  # no data never excludes
        self.assertEqual(exclusions.apollo_reasons(None, "Rubix"), [])
        # review fix: an entry with no end date and no current flag is incomplete data, never an ended job
        undated = [{"org": "Rubix DACH GmbH", "title": "COO", "current": False, "start": "2019-01-01", "end": ""}]
        self.assertEqual(exclusions.apollo_reasons(undated, "Rubix"), [])

    def test_apollo_role_at_the_target_ended(self):
        hist = [{"org": "Rubix DACH GmbH", "title": "COO", "current": False, "start": "2019-01-01", "end": "2026-03-15"},
                {"org": "NewCo", "title": "COO", "current": True, "start": "2026-04-01", "end": ""}]
        r = exclusions.apollo_reasons(hist, "Rubix")
        self.assertEqual([c for c, _ in r], ["apollo_role_ended"])
        self.assertIn("2026-03-15", r[0][1])
        still = [dict(hist[0], current=True, end="")] + hist[1:]
        self.assertEqual(exclusions.apollo_reasons(still, "Rubix"), [])
        self.assertEqual(exclusions.apollo_reasons(hist, "Unrelated Ltd"), [])  # a different company is not the target

    def test_company_name_match_ignores_legal_suffixes(self):
        self.assertTrue(exclusions.same_company("Rubix DACH GmbH", "Rubix"))
        self.assertTrue(exclusions.same_company("The ACME Group Ltd", "Acme"))
        self.assertFalse(exclusions.same_company("Rubix", "Zalando"))
        self.assertFalse(exclusions.same_company("", "Rubix"))

    def test_linkedin_checker_columns(self):
        r = exclusions.linkedin_reasons({"current_jobs_count": "0", "jobs_count": "6", "latest_job_start": "2019-02"})
        self.assertEqual([c for c, _ in r], ["linkedin_no_current_position"])
        self.assertEqual(exclusions.linkedin_reasons({"current_jobs_count": "1", "jobs_count": "6"}), [])
        self.assertEqual(exclusions.linkedin_reasons({"current_jobs_count": "0", "jobs_count": "0"}), [])  # an empty profile is not an ended role
        self.assertEqual(exclusions.linkedin_reasons({"current_jobs_count": "", "jobs_count": ""}), [])
        self.assertEqual(exclusions.linkedin_reasons({}), [])
        self.assertEqual(exclusions.linkedin_reasons(None), [])

    def test_evaluate_combines_sources_and_formats_the_reason(self):
        ev = exclusions.evaluate({"title": "COO", "company": "Rubix"}, {"headline": "Open to work", "employment_history": self.HIST_NONE},
                                 {"headline": "Retired", "current_jobs_count": "0", "jobs_count": "3"})
        self.assertEqual(ev["categories"], ["open_to_work", "retired", "apollo_no_current_position", "linkedin_no_current_position"])
        self.assertTrue(ev["reason"].startswith("open_to_work: headline says 'Open to work'; retired: headline says 'Retired'"))
        clean = exclusions.evaluate({"title": "COO", "company": "Rubix"}, {"headline": "COO at Rubix", "employment_history": self.HIST_OK}, {})
        self.assertEqual(clean, {"reason": "", "categories": []})

    def test_sources_and_the_whole_feature_can_be_switched_off(self):
        e = {"headline": "Open to work", "employment_history": self.HIST_NONE}
        off = {"enabled": False}
        self.assertEqual(exclusions.evaluate({"title": "COO", "company": "R"}, e, {}, off)["reason"], "")
        no_apollo = {"enabled": True, "use_apollo_employment": False, "use_linkedin_checker": True, "linkedin_no_current_position": True}
        self.assertEqual(exclusions.evaluate({"title": "COO", "company": "R"}, e, {}, no_apollo)["reason"], "")  # headline was Apollo's

    def test_category_counts(self):
        rows = [{"exclusion_reason": "open_to_work: x; apollo_no_current_position: y"}, {"exclusion_reason": "retired: z"},
                {"exclusion_reason": ""}, {}]
        self.assertEqual(exclusions.category_counts(rows), {"open_to_work": 1, "apollo_no_current_position": 1, "retired": 1, "total": 2})


class TestExclusionsInThePipeline(unittest.TestCase):
    def build(self, slug="ex1"):
        run, b = full_run("%s_%s" % (slug, id(self)))
        return run, b

    def test_apollo_employment_is_stored_at_enrichment(self):
        m = apollo.ApolloClient.normalize_match({"id": "p1", "headline": "Retired COO", "organization": {"name": "A"},
                                                 "employment_history": [{"organization_name": "A", "title": "COO", "current": False,
                                                                         "start_date": "2010-01-01", "end_date": "2020-01-01", "id": "x", "key": "k"}]})
        self.assertEqual(m["headline"], "Retired COO")
        self.assertEqual(m["employment_history"], [{"org": "A", "title": "COO", "current": False, "start": "2010-01-01", "end": "2020-01-01"}])

    def test_enrich_record_carries_headline_and_history(self):
        run = make_run("ex2_%s" % id(self), BRIEF)

        class Tr(FakePeopleApollo):
            def __call__(self, method, url, headers, data, timeout):
                st, rh, raw = super().__call__(method, url, headers, data, timeout)
                if url.split("?")[0].endswith("/people/bulk_match"):
                    out = json.loads(raw)
                    for m in out["matches"]:
                        if m:
                            m["headline"] = "Open to work"
                            m["employment_history"] = [{"organization_name": "A Ltd", "current": False, "end_date": "2026-01-01", "title": "COO"}]
                    raw = json.dumps(out).encode()
                return st, rh, raw
        write_json(run.ledger_path, {"complete": True, "leaves": {}})
        qualified(run, [("o1", "a.com", "A Ltd", "keep")])
        (run.qdir / "prompt.md").write_text("x")
        pm.run_search(run, BRIEF, client(FakePeopleApollo({"o1": [person("p1", "o1", "COO")]}), run), progress=None)
        from tier import Tier
        append_jsonl(Tier(run).results_path, {"person_id": "p1", "tier": "T1", "reason": "r"})
        pm.rebuild(run, BRIEF)
        emod.run_enrich(run, client(Tr(), run), progress=None)
        rec = read_jsonl(pm.Files(run).enrich_results)[-1]
        self.assertEqual(rec["headline"], "Open to work")
        self.assertEqual(rec["employment_history"][0]["end"], "2026-01-01")
        rows = pm.rebuild(run, BRIEF)
        r = rows[0]
        self.assertEqual(r["channels"], "")  # excluded: no channel
        self.assertIn("open_to_work", r["exclusion_reason"])
        self.assertIn("apollo_no_current_position", r["exclusion_reason"])
        self.assertEqual(len(rows), 1)  # the row is kept

    def test_linkedin_checker_output_excludes_after_activity(self):
        run, b = self.build("ex3")
        rows = pm.rebuild(run, b)
        sel = [r for r in rows if r["cap_status"] == "selected"]
        victim = sel[0]
        self.assertTrue(victim["linkedin_url"])
        for r in sel:
            append_jsonl(pm.Files(run).activity_cache, {"linkedin_key": pm.profile_key(r["linkedin_url"]), "linkedin_url": r["linkedin_url"],
                         "activity_status": "Active", "checked_at": "2026-10-21T00:00:00Z", "final": True,
                         "headline": "On a career break" if r is victim else "COO at A", "current_jobs_count": "0" if r is victim else "1",
                         "jobs_count": "4", "current_title": "", "current_company": "", "latest_job_start": "2019-01"})
        rows = pm.rebuild(run, b)
        by = {r["person_id"]: r for r in rows}
        v = by[victim["person_id"]]
        self.assertEqual((v["channels"], v["linkedin_active"]), ("", "yes"))  # active on LinkedIn, but not in a job
        self.assertIn("career_break", v["exclusion_reason"])
        self.assertIn("linkedin_no_current_position", v["exclusion_reason"])
        others = [r for r in rows if r["cap_status"] == "selected" and r is not v and r["person_id"] != victim["person_id"]]
        self.assertTrue(all(r["exclusion_reason"] == "" for r in others))
        self.assertIn("linkedin", " ".join(r["channels"] for r in others))

    def test_activity_collect_keeps_the_checker_employment_columns(self):
        run, b = self.build("ex4")

        class Ch:
            leads_tab = "t"
            def read_leads(self):
                return [{"linkedin_url": "http://www.linkedin.com/in/p1", "activity_status": "Active", "headline": "Retired",
                         "current_jobs_count": "0", "jobs_count": "2", "latest_job_start": "2020-01", "current_title": "x", "current_company": "y"}]
        amod.collect(run, Ch(), ["http://www.linkedin.com/in/p1"])
        rec = [r for r in read_jsonl(pm.Files(run).activity_cache) if r["linkedin_key"].endswith("/p1")][-1]
        self.assertEqual((rec["headline"], rec["current_jobs_count"], rec["jobs_count"], rec["latest_job_start"]), ("Retired", "0", "2", "2020-01"))

    def test_excluded_people_are_not_sent_to_the_activity_checker_or_phones(self):
        run, b = self.build("ex5")
        rows = pm.rebuild(run, b)
        sel = [r for r in rows if r["cap_status"] == "selected" and r["linkedin_url"]]
        sel[0]["exclusion_reason"] = "retired: x"
        todo = amod.todo_rows(sel, {})
        self.assertNotIn(sel[0]["linkedin_url"], [t["linkedin_url"] for t in todo])
        self.assertEqual(len(todo), len(sel) - 1)

    def test_channels_for_and_ready_tabs(self):
        p = {"cap_status": "selected", "tier": "T1", "linkedin_url": "u", "linkedin_active": "yes", "email_verdict": "valid", "phone": "1"}
        self.assertEqual(pm.channels_for(p), ["linkedin", "email", "call"])
        self.assertEqual(pm.channels_for(dict(p, exclusion_reason="retired: x")), [])
        import ready as rdy
        recs = rdy.records([dict(p, person_id="p", first_name="A", last_name="B", title="T", company="C", country="UK", domain="d", email="e",
                                 tier_reason="", channels="")], "Idea")
        self.assertTrue(all(v == [] for v in recs.values()))  # an excluded person is on no Ready tab (withdrawn on the next build)

    def test_summary_and_run_log_show_counts_once(self):
        run, b = self.build("ex6")
        rows = pm.rebuild(run, b)
        sel = [r for r in rows if r["cap_status"] == "selected"]
        e = read_jsonl(pm.Files(run).enrich_results)
        for rec in e[-2:]:
            append_jsonl(pm.Files(run).enrich_results, dict(rec, headline="Retired CFO", status="matched"))
        rows = pm.rebuild(run, b)
        c = exclusions.category_counts(rows)
        self.assertEqual(c["total"], 2)
        line = pm.log_exclusions(run, rows)
        self.assertIn("2 people excluded", line["detail"])
        self.assertIsNone(pm.log_exclusions(run, rows))  # same numbers: no second line
        run.write_summary()
        body = open(run.summary_path).read()
        self.assertIn("Exclusions, employment and pilot rejects (channel none, rows kept): 2 (retired 2)", body)
        self.assertEqual(len([x for x in read_jsonl(run.runlog) if x["stage"] == "exclusions"]), 1)

    def test_exclusion_column_is_in_the_people_schema(self):
        for c in ("exclusion_reason", "pilot", "pilot_review", "pilot_note"):
            self.assertIn(c, schema.PEOPLE_COLS)
        for c in ("employees", "engineering", "operations", "sales", "pilot", "pilot_review", "pilot_note", "is_seed"):
            self.assertIn(c, schema.ACCOUNT_COLS)
        self.assertEqual(schema.ACCOUNT_COLS[:len(schema.ACCOUNT_BASE_COLS + schema.QUALIFY_COLS)], schema.ACCOUNT_BASE_COLS + schema.QUALIFY_COLS)


class TestPilotScopeAndBackfill(unittest.TestCase):
    def test_qualify_works_on_the_pilot_only_until_the_gate_is_open(self):
        run = acct_run("sc1_%s" % id(self), ["a%d.com" % i for i in range(14)], signals=None)
        write_json(run.ledger_path, {"limit": 10, "complete": False, "leaves": {}})
        write_json(pilot.Gate(run, pilot.ACCOUNTS).sel_path, {"ids": ["o-a%d.com" % i for i in range(10)], "size": 10})
        q = qmod.Qualify(run)
        self.assertEqual(len(q.accounts()), 10)  # the 4 others are not touched before the review
        self.assertEqual(pilot.scope_ids(run), {"o-a%d.com" % i for i in range(10)})
        g = pilot.Gate(run, pilot.ACCOUNTS)
        g.skip("user decision")
        self.assertEqual(len(q.accounts()), 14)
        self.assertIsNone(pilot.scope_ids(run))

    def test_no_pilot_no_restriction(self):
        run = acct_run("sc2_%s" % id(self), ["a.com", "b.com"], signals=None)
        self.assertIsNone(pilot.scope_ids(run))
        self.assertEqual(len(qmod.Qualify(run).accounts()), 2)

    def test_accounts_stage_detail_follows_the_gate(self):
        run, doms = pilot_run("sc3_%s" % id(self), n=10, signals=None)
        append_jsonl(run.dir / "accounts.stream.jsonl", {"org_id": "x"})
        self.assertIn("waits for the pilot gate", stages.check_accounts(run, {})["detail"])
        pilot.Gate(run, pilot.ACCOUNTS).skip("user decision")
        self.assertIn("approved, the full pull has not run yet", stages.check_accounts(run, {})["detail"])

    def test_backfill_copies_the_checker_employment_columns_for_profiles_checked_earlier(self):
        run, b = full_run("sc4_%s" % id(self))
        rows = [r for r in pm.rebuild(run, b) if r["linkedin_url"]]
        r0 = rows[0]
        append_jsonl(pm.Files(run).activity_cache, {"linkedin_key": pm.profile_key(r0["linkedin_url"]), "linkedin_url": r0["linkedin_url"],
                                                    "activity_status": "Active", "checked_at": "x", "final": True})

        class Ch:
            def read_leads(self):
                return [{"linkedin_url": r0["linkedin_url"], "headline": "Retired", "current_jobs_count": 0, "jobs_count": 3},
                        {"linkedin_url": "https://www.linkedin.com/in/unknown", "headline": "x"}]
        rep = amod.backfill_employment(run, Ch())
        self.assertEqual(rep, {"profiles_in_tab": 1, "updated": 1, "unchanged": 0})
        self.assertEqual(amod.backfill_employment(run, Ch())["unchanged"], 1)  # idempotent
        row = next(r for r in pm.rebuild(run, b) if r["person_id"] == r0["person_id"])
        self.assertIn("retired", row["exclusion_reason"])
        self.assertIn("linkedin_no_current_position", row["exclusion_reason"])


class TestNoEmDashesInPhase4(unittest.TestCase):
    def test_new_files_have_no_em_dashes(self):
        root = str(config.IDEA_LAUNCH_DIR)
        files = ["lib/signals.py", "lib/pilot.py", "lib/exclusions.py", "bin/signals_run.py", "bin/pilot_run.py", "config.json",
                 "tests/run_tests_phase4.py"]
        for f in files:
            self.assertNotIn("\u2014", open(os.path.join(root, f), encoding="utf-8").read(), f)
