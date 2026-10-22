#!/usr/bin/env python3
"""Offline unit tests (no network, no credits). Run:  python3 -I tests/run_tests.py"""
import json
import os
import sys
import tempfile
import unittest
import warnings

warnings.simplefilter("ignore", ResourceWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
# Hermetic: fake credentials so the suite passes on a clean clone (no .env, no config.local.json).
os.environ.setdefault("BLISSGROWTH_N8N_INSTANCE_URL", "https://n8n.invalid")
os.environ.setdefault("BLISSGROWTH_N8N_API_KEY", "test-n8n-key")
os.environ.setdefault("HEYREACH_API_KEY", "test-heyreach-key")
import config  # noqa: E402

config.cfg().setdefault("sheets_bridge", {}).setdefault("secret", "test-secret")

TMP = tempfile.mkdtemp(prefix="il-test-")
config.cfg()["run"]["lists_dir"] = TMP  # absolute path wins over the repo root
config.cfg()["apollo"]["min_interval_s"] = 0
os.environ["APOLLO_API_KEY"] = "test-key"

import apollo  # noqa: E402
import brief as briefmod  # noqa: E402
import qualify as qmod  # noqa: E402
import schema  # noqa: E402
import sheet as sheetmod  # noqa: E402
import volume  # noqa: E402
from run import Run  # noqa: E402
from util import norm_domain, read_jsonl, write_csv, write_json  # noqa: E402


def good_brief(**over):
    b = {"idea": {"name": "Test Idea", "slug": "test-idea", "test": True},
         "apollo": {"base": {"organization_locations": ["United Kingdom", "Germany"],
                             "organization_num_employees_ranges": ["25,1000"]},
                    "filter_sets": [{"label": "a", "q_organization_keyword_tags": ["wholesaler", "importer"]}]},
         "people": {"T1": {"titles": ["COO"]}, "T2": {"titles": ["Head of Compliance"]}}}
    b.update(over)
    return b


class FakeApollo:
    """Transport that answers org searches from a table of totals and records calls."""
    def __init__(self, totals_by_loc=None, fail_first=None):
        self.calls, self.fail_first, self.totals = [], list(fail_first or []), totals_by_loc or {}

    def __call__(self, method, url, headers, data, timeout):
        self.calls.append(url)
        if self.fail_first:
            st = self.fail_first.pop(0)
            return st, {}, json.dumps({"error_details": {"retry_after_seconds": 1}}).encode()
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(url).query)
        locs = q.get("organization_locations[]", [])
        rng = q.get("organization_num_employees_ranges[]", [])
        total = sum(self.totals.get(l, 10) for l in locs) or 10
        if rng == ["25,512"] or rng == ["513,1000"]:
            total //= 2
        per = int(q.get("per_page", ["100"])[0])
        page = int(q.get("page", ["1"])[0])
        n = max(0, min(per, total - (page - 1) * per))
        orgs = [{"id": "o%d-%d" % (page, i), "name": "Org", "primary_domain": "d%d-%d.com" % (page, i)} for i in range(n)]
        body = {"organizations": orgs[: n - 1] if n > 1 else orgs, "accounts": [dict(orgs[-1], organization_id="crm-%d-%d" % (page, n))] if n > 1 else [],
                "pagination": {"page": page, "per_page": per, "total_entries": total, "total_pages": -(-total // per)}}
        return 200, {"x-minute-requests-left": "150"}, json.dumps(body).encode()


class TestBrief(unittest.TestCase):
    def test_valid_and_invalid(self):
        self.assertEqual(briefmod.validate(good_brief()), [])
        bad = good_brief()
        bad["apollo"]["base"]["bogus_key"] = ["x"]
        bad["apollo"]["filter_sets"][0]["organization_num_employees_ranges"] = ["abc"]
        errs = " ".join(briefmod.validate(bad))
        self.assertIn("bogus_key", errs)
        self.assertIn("25,1000", errs)

    def test_hard_filters_required(self):
        b = good_brief()
        b["apollo"]["base"] = {}
        errs = " ".join(briefmod.validate(b))
        self.assertIn("organization_locations", errs)
        self.assertIn("organization_num_employees_ranges", errs)

    def test_params_encoding(self):
        p = briefmod.to_params({"organization_locations": ["UK", "DE"], "revenue_range": {"min": 5}, "q_organization_name": "x"}, 2, 100)
        self.assertIn(("organization_locations[]", "DE"), p)
        self.assertIn(("revenue_range[min]", "5"), p)
        self.assertIn(("page", "2"), p)

    def test_merge_set_overrides_base(self):
        m = briefmod.merge_filters({"organization_locations": ["UK"]}, {"label": "x", "organization_locations": ["DE"]})
        self.assertEqual(m, {"organization_locations": ["DE"]})

    def test_domain(self):
        self.assertEqual(norm_domain("https://www.Example.com/a?b"), "example.com")
        self.assertEqual(norm_domain("junk"), "")
        self.assertEqual(briefmod.excluded_domains({"exclusions": {"domains": ["www.WWW1.com"]}}), {"www1.com"})


class TestApollo(unittest.TestCase):
    def client(self, fake, sleeps=None):
        return apollo.ApolloClient(transport=fake, sleep=(sleeps.append if sleeps is not None else lambda s: None))

    def test_normalize_account_vs_org(self):
        org = apollo.ApolloClient.normalize_org({"id": "ORG", "name": "A", "website_url": "http://www.a.com"})
        acc = apollo.ApolloClient.normalize_org({"id": "ACCT", "organization_id": "ORG2", "name": "B", "domain": "b.com", "country": "UK"})
        self.assertEqual((org["org_id"], org["domain"], org["apollo_crm"]), ("ORG", "a.com", ""))
        self.assertEqual((acc["org_id"], acc["apollo_crm"], acc["country"]), ("ORG2", "yes", "UK"))

    def test_reads_both_arrays(self):
        res = self.client(FakeApollo()).org_page({"organization_locations": ["UK"]}, 1, 10)
        self.assertEqual(res["n_records"], 10)
        self.assertEqual(sum(1 for o in res["orgs"] if o["apollo_crm"]), 1)

    def test_split_order(self):
        f = {"organization_locations": ["UK", "DE"], "organization_num_employees_ranges": ["25,1000"]}
        parts = apollo.ApolloClient.split_filters(f)
        self.assertEqual([p["organization_locations"] for p in parts], [["UK"], ["DE"]])
        parts = apollo.ApolloClient.split_filters(parts[0])
        self.assertEqual([p["organization_num_employees_ranges"] for p in parts], [["25,512"], ["513,1000"]])
        self.assertIsNone(apollo.ApolloClient.split_filters({"organization_locations": ["UK"], "organization_num_employees_ranges": ["5,5"]}))

    def test_plan_shards_over_cap(self):
        fake = FakeApollo({"UK": 80000, "DE": 30000})
        leaves = self.client(fake).plan({"organization_locations": ["UK", "DE"], "organization_num_employees_ranges": ["25,1000"]})
        self.assertEqual(sorted(l["total"] for l in leaves), [30000, 40000, 40000])
        self.assertFalse(any(l["truncated"] for l in leaves))

    def test_plan_unsplittable_is_truncated(self):
        fake = FakeApollo({"UK": 90000})
        leaves = self.client(fake).plan({"organization_locations": ["UK"], "organization_num_employees_ranges": ["5,5"]})
        self.assertTrue(leaves[0]["truncated"])

    def test_retry_429_then_500_then_ok(self):
        sleeps = []
        fake = FakeApollo(fail_first=[429, 500])
        c = self.client(fake, sleeps)
        res = c.org_page({"organization_locations": ["UK"]}, 1, 5)
        self.assertEqual(res["n_records"], 5)
        self.assertEqual(c.totals["retries"], 2)
        self.assertEqual(sleeps[0], 1)  # honoured retry_after_seconds

    def test_hard_errors_do_not_retry(self):
        fake = FakeApollo(fail_first=[422])
        with self.assertRaises(apollo.ApolloError):
            self.client(fake).org_page({"organization_locations": ["UK"]}, 1, 5)
        self.assertEqual(len(fake.calls), 1)

    def test_iter_leaf_pages_and_limit(self):
        fake = FakeApollo({"UK": 250})
        c = self.client(fake)
        rows = list(c.iter_leaf({"organization_locations": ["UK"]}, 250))
        self.assertEqual(len(rows), 250)
        self.assertEqual(c.totals["credits"], 3)
        rows = list(self.client(FakeApollo({"UK": 250})).iter_leaf({"organization_locations": ["UK"]}, 250, limit=120))
        self.assertEqual(len(rows), 120)

    def test_usage_log_and_big_query_uses_body(self):
        log = os.path.join(TMP, "usage.jsonl")
        c = apollo.ApolloClient(transport=FakeApollo(), sleep=lambda s: None, usage_log=log)
        c.org_page({"organization_locations": ["UK"]}, 1, 5)
        self.assertEqual(read_jsonl(log)[0]["credits"], 1)
        seen = {}

        def tr(method, url, headers, data, timeout):
            seen["url"], seen["data"] = url, data
            return 200, {}, b'{"people":[],"total_entries":0}'
        c2 = apollo.ApolloClient(transport=tr, sleep=lambda s: None)
        c2.people_page(["CEO"], domains=["d%d.com" % i for i in range(800)])
        self.assertNotIn("?", seen["url"])
        self.assertEqual(len(json.loads(seen["data"])["q_organization_domains_list"]), 800)


class TestRun(unittest.TestCase):
    def test_state_summary_and_derivation(self):
        run = Run.create("run-test", "2026-01-01")
        self.assertTrue(run.dir.name.endswith("2026-01-01-run-test"))
        write_json(run.brief_path, good_brief())
        self.assertEqual(run.stage_status()["brief"]["status"], "partial")  # no sheet yet
        write_json(run.sheet_path, {"sheet_id": "S1", "url": "http://x"})
        self.assertEqual(run.stage_status()["brief"]["status"], "done")
        first = run.write_summary()
        self.assertTrue(first.startswith("NOT READY"))
        self.assertTrue(run.summary_path.read_text().startswith("NOT READY"))
        self.assertEqual(Run.resolve("run-test").dir, run.dir)

    def test_corrupt_state_recovers(self):
        run = Run.create("corrupt", "2026-01-02")
        run.state_path.write_text("{not json")
        st = run.load_state()
        self.assertTrue((run.dir / "state.json.bad").exists())
        self.assertIn("usage", st)

    def test_ready_requires_everything(self):
        run = Run.create("ready", "2026-01-03")
        b = good_brief()
        b["idea"]["test"] = False
        write_json(run.brief_path, b)
        write_json(run.sheet_path, {"sheet_id": "S1", "url": "http://x"})
        write_json(run.ledger_path, {"complete": True, "leaves": {}})
        cols = schema.ACCOUNT_BASE_COLS
        write_csv(run.accounts_csv, [{"org_id": "a", "domain": "a.com", "name": "A"}, {"org_id": "b", "domain": "b.com", "name": "B"}], cols)
        (run.qdir).mkdir(exist_ok=True)
        (run.qdir / "prompt.md").write_text("x")
        self.assertTrue(run.write_summary().startswith("NOT READY"))
        from util import append_jsonl
        append_jsonl(run.qdir / "results.jsonl", {"org_id": "a", "flag": "keep"})
        self.assertTrue(run.write_summary().startswith("NOT READY"))
        append_jsonl(run.qdir / "results.jsonl", {"org_id": "b", "flag": "drop"})
        self.assertTrue(run.write_summary().startswith("NOT READY"))  # scored but not finalized
        write_csv(run.qdir / "qualified.csv", [], cols)
        first = run.write_summary()
        self.assertTrue(first.startswith("NOT READY") and "people is pending" in first)  # Phase 2 stages are required

    def test_resolve_exact_slug(self):
        a = Run.create("zz-test", "2026-01-05")
        with self.assertRaises(Exception):
            Run.resolve("test")  # must not pick up "...-zz-test"
        self.assertEqual(Run.resolve("zz-test").dir, a.dir)

    def test_set_spec_after_lock_unlocks(self):
        run = Run.create("relock", "2026-01-06")
        q = qmod.Qualify(run)
        q.set_spec(SPEC)
        q.lock(2)
        self.assertTrue(q.is_locked())
        q.set_spec(dict(SPEC, extra_rules=["new edge case"]))
        self.assertFalse(q.is_locked())

    def test_lock(self):
        run = Run.create("lock", "2026-01-04")
        with run.lock():
            from run import RunError
            with self.assertRaises(RunError):
                with run.lock():
                    pass
        with run.lock():
            pass


class TestSheet(unittest.TestCase):
    def test_payloads_and_errors(self):
        sent = []

        def tr(method, url, headers, data, timeout):
            sent.append((headers, json.loads(data)))
            return 200, {}, json.dumps({"ok": True, "appended": 2, "updated": 1, "skipped": 0, "values": [["a"]]}).encode()
        c = sheetmod.SheetClient(url="http://bridge", secret="s3", transport=tr, sleep=lambda s: None)
        c.cfg = dict(c.cfg, append_chunk=2)
        self.assertEqual(c.append("SID", "2 Accounts", [[1], [2], [3], [4], [5]]), 6)  # 3 chunks of the stub's 2
        self.assertEqual(len(sent), 3)
        self.assertEqual(sent[0][0]["X-Idea-Launch-Secret"], "s3")
        c.create("T")
        self.assertEqual([t["title"] for t in sent[-1][1]["tabs"]], schema.TAB_ORDER)
        self.assertEqual(c.read_records("SID", "t"), [])

    def test_403_and_not_ok(self):
        c = sheetmod.SheetClient(url="u", secret="s", transport=lambda *a: (403, {}, b""), sleep=lambda s: None)
        with self.assertRaises(sheetmod.SheetError):
            c.read("a", "b")
        c = sheetmod.SheetClient(url="u", secret="s", transport=lambda *a: (200, {}, b'{"ok":false,"error":"boom"}'), sleep=lambda s: None)
        with self.assertRaisesRegex(sheetmod.SheetError, "boom"):
            c.append("a", "b", [[1]])

    def test_append_not_retried_on_network_error(self):
        n = []

        def tr(*a):
            n.append(1)
            raise OSError("down")
        c = sheetmod.SheetClient(url="u", secret="s", transport=tr, sleep=lambda s: None)
        with self.assertRaises(sheetmod.SheetError):
            c.append("a", "b", [[1]])
        self.assertEqual(len(n), 1)
        with self.assertRaises(sheetmod.SheetError):
            c.read("a", "b")
        self.assertEqual(len(n), 4)  # 1 + read tried 3 times

    def test_schema_consistent(self):
        self.assertEqual(len(schema.TABS), 9)
        for c in schema.QUALIFY_COLS + schema.ACCOUNT_BASE_COLS:
            self.assertIn(c, schema.ACCOUNT_COLS)
        self.assertEqual(sheetmod.col_letter(0), "A")
        self.assertEqual(sheetmod.col_letter(26), "AA")


SPEC = {"icp_one_liner": "UK/EU wholesalers", "qualifies": ["wholesaler of consumer goods"], "disqualifies": ["software vendor"],
        "countries": ["United Kingdom"]}


class TestQualify(unittest.TestCase):
    def setUp(self):
        self.run = Run.create("q-%s" % self.id().split(".")[-1], "2026-02-01")
        write_json(self.run.brief_path, good_brief())
        rows = [{"org_id": "o%d" % i, "domain": "d%d.com" % i, "name": "Co %d" % i, "country": "UK"} for i in range(6)]
        rows.append({"org_id": "o6", "domain": "", "name": "No site"})
        write_csv(self.run.accounts_csv, rows, schema.ACCOUNT_BASE_COLS)
        self.q = qmod.Qualify(self.run)

    def test_prompt_has_mandatory_blocks(self):
        text = qmod.build_prompt(SPEC)
        for m in qmod.MANDATORY_MARKERS:
            self.assertIn(m, text)
        self.assertIn("United Kingdom", text)
        self.assertNotIn(chr(0x2014), text)  # no em dashes
        with self.assertRaises(ValueError):
            qmod.check_prompt(text.replace("MANDATORY BLOCK 3", "x"))
        with self.assertRaises(ValueError):
            qmod.build_prompt({"icp_one_liner": "x"})

    def test_classify_page(self):
        long = "<html><title>Acme Wholesale</title><body>" + "We import and wholesale consumer goods across Europe. " * 10 + "</body></html>"
        self.assertEqual(qmod.classify_page(200, long, 3000)["status"], "live")
        self.assertEqual(qmod.classify_page(200, "<html><body>This domain is for sale</body></html>", 3000)["status"], "parked")
        self.assertEqual(qmod.classify_page(200, "<body>hi</body>", 3000)["status"], "parked")
        spa = '<html><head><title>Acme</title><meta name="description" content="Acme is a wholesale distributor of household goods in the UK"></head><body><div id=root></div></body></html>'
        r = qmod.classify_page(200, spa, 3000)
        self.assertEqual(r["status"], "live")  # JS-only site with a real meta description is not parked
        self.assertEqual(qmod.classify_page(404, "", 3000)["status"], "dead")
        self.assertEqual(qmod.classify_page(403, "", 3000)["status"], "blocked")

    def test_fetch_live_fallbacks(self):
        calls = []

        def tr(method, url, headers, data, timeout):
            calls.append(url)
            if url.startswith("https://x.com"):
                raise OSError("tls")
            return 200, {"content-type": "text/html; charset=utf-8"}, ("<title>t</title>" + "word " * 100).encode()
        r = qmod.fetch_live("x.com", transport=tr)
        self.assertEqual(r["status"], "live")
        self.assertTrue(calls[1].startswith("http://x.com"))
        self.assertEqual(qmod.fetch_live("y.com", transport=lambda *a: (_ for _ in ()).throw(OSError()))["status"], "dead")

    def test_fetch_many_deadline(self):
        import time as _t
        got = {}

        def slow(d, timeout=0, chars=0):
            if d == "hang.com":
                _t.sleep(5)
            return {"status": "live"}
        qmod.fetch_many(["a.com", "hang.com"], lambda d, r: got.__setitem__(d, r), concurrency=2, deadline=1, fetcher=slow)
        self.assertEqual(got["a.com"]["status"], "live")
        self.assertEqual(got["hang.com"]["status"], "error")

    def test_parse_and_validate(self):
        data = qmod.parse_result_text('Here you go:\n```json\n[{"id":"a","qualified":"true","confidence":0.8,"reason":"ok"}]\n```')
        c, p = qmod.validate_item(data[0], {"a"})
        self.assertEqual((c["qualified"], p), (True, None))
        for bad in ({"id": "a", "qualified": "maybe", "confidence": 1, "reason": "x"},
                    {"id": "a", "qualified": True, "confidence": 1.5, "reason": "x"},
                    {"id": "a", "qualified": True, "confidence": 0.5, "reason": ""}):
            self.assertIsNotNone(qmod.validate_item(bad, {"a"})[1])
        self.assertIsNone(qmod.validate_item({"id": "zz"}, {"a"})[0])
        with self.assertRaises(ValueError):
            qmod.parse_result_text("no json")

    def test_decide(self):
        self.assertEqual(qmod.decide(True, 0.9, 0.6), "keep")
        self.assertEqual(qmod.decide(True, 0.5, 0.6), "review")
        self.assertEqual(qmod.decide(False, 0.99, 0.6), "drop")
        self.assertEqual(qmod.decide(None, 0, 0.6), "error")

    def test_end_to_end_batches_ingest_retry(self):
        self.q.set_spec(SPEC)
        live = {"status": "live", "title": "T", "description": "d", "text": "we wholesale goods " * 20}
        fetched = {"d0.com": live, "d1.com": live, "d2.com": live, "d3.com": live, "d4.com": {"status": "dead", "http": 0},
                   "d5.com": {"status": "parked"}}
        from util import append_jsonl
        for d, r in fetched.items():
            append_jsonl(self.q.evidence_path, dict(r, domain=d))
        res = self.q.make_batches(size=2)
        self.assertEqual(len(res["batches"]), 2)  # o0..o3 live; dead, parked, no-site resolved without the model
        flags = {k: v["flag"] for k, v in self.q.results().items()}
        self.assertEqual(flags, {"o4": "dead_site", "o5": "parked_site", "o6": "dead_site"})
        # subagent answers batch 1 fully (one valid, one invalid) and batch 2 not at all
        b1 = json.load(open(res["batches"][0]))
        ids = [r["id"] for r in b1["rows"]]
        out = [{"id": ids[0], "qualified": True, "confidence": 0.9, "reason": "fits"},
               {"id": ids[1], "qualified": "dunno", "confidence": 0.9, "reason": "?"}]
        open(b1["result_file"], "w").write(json.dumps(out))
        rep = self.q.ingest_file(b1["result_file"])
        self.assertEqual((rep["ok"], rep["invalid"]), (1, 1))
        self.assertEqual(self.q.results()[ids[1]]["flag"], "error")
        st = self.q.status()
        self.assertEqual(st["flags"]["keep"], 1)
        self.assertEqual(st["flags"]["unscored"], 2)
        # retry pass: the error row and the two unscored rows are pending again; in-flight batch 2 is skipped
        res2 = self.q.make_batches(size=5)
        self.assertEqual(res2["pending"], 3)
        self.assertEqual(res2["skipped_in_flight"], 2)
        self.assertEqual(sum(len(json.load(open(p))["rows"]) for p in res2["batches"]), 1)
        # never deletes rows
        fin = self.q.finalize(push=False)
        self.assertEqual(fin["rows"], 7)
        from util import read_csv
        self.assertEqual(len(read_csv(self.q.qualified_csv)), 7)

    def test_tuning_streak_and_sample(self):
        self.q.set_spec(SPEC)
        self.assertEqual(self.q.log_round(1, 2), 0)
        self.assertEqual(self.q.log_round(2, 0), 1)
        self.assertEqual(self.q.log_round(3, 0), 2)
        self.assertEqual(self.q.log_round(4, 1), 0)
        from util import append_jsonl
        live = {"status": "live", "title": "T", "description": "d", "text": "x" * 200}
        for i in range(6):
            append_jsonl(self.q.evidence_path, dict(live, domain="d%d.com" % i))
        p = self.q.sample_batch(1, n=3)
        b1 = json.load(open(p))
        self.assertEqual(len(b1["rows"]), 3)
        b2 = json.load(open(self.q.sample_batch(2, n=3)))
        self.assertFalse({r["id"] for r in b1["rows"]} & {r["id"] for r in b2["rows"]})  # new companies each round


class TestVolume(unittest.TestCase):
    def test_sizing(self):
        s = volume.sizing(good_brief())
        self.assertGreater(s["accounts_for_email_max"], s["accounts_for_email_min"])
        b = good_brief(volume={"assumptions": {"qualify_pass_rate": 1.0, "people_found_rate": 1.0, "avg_people_per_account": 1.0, "email_valid_rate": 1.0}})
        self.assertEqual(volume.sizing(b)["accounts_for_email_min"], 2000)


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    import run_tests_phase2  # noqa: F401  (registers the Phase 2 test cases in this same run)
    import run_tests_phase3  # noqa: F401  (Phase 3: copy, idea page, launch, orchestrator)
    import run_tests_phase4  # noqa: F401  (Phase 4: signals, pilot gates, employment exclusions)
    suite = unittest.TestSuite()
    for mod in (sys.modules["__main__"], run_tests_phase2, run_tests_phase3, run_tests_phase4):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(mod))
    res = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)
