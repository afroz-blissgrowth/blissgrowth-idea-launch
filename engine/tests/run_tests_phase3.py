"""Phase 3 offline tests (no network, no credits, nothing created anywhere). Run together with Phases 1 and 2:
  python3 -I tests/run_tests.py
Imported by run_tests.py (which sets the temp lists dir first)."""
import copy as stdcopy
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import config  # noqa: E402

import copydraft  # noqa: E402
import copylib  # noqa: E402
import copyrules  # noqa: E402
import heyreach  # noqa: E402
import ideapage  # noqa: E402
import launch as lmod  # noqa: E402
import orchestrate  # noqa: E402
import schema  # noqa: E402
import stages  # noqa: E402
from run_tests_phase2 import BRIEF, make_run  # noqa: E402
from util import read_json, write_csv, write_json  # noqa: E402

REAL_SEQ = json.load(open(os.path.join(HERE, "fixtures", "sequence_real.json"), encoding="utf-8"))


# ---- fixtures ---------------------------------------------------------------------------------------
def item(channel, tier, step, variant, body, subject="", sender=None, **kw):
    d = {"channel": channel, "tier": tier, "step": step, "variant": variant, "body": body,
         "sender": sender or ("associate" if channel == "inmail" else "founder")}
    if subject:
        d["subject"] = subject
    d.update(kw)
    return d


def good_items():
    out = []
    for v, t in zip(("V1", "V2", "V3"), ("Hi {FIRST_NAME}, you know product rules across markets better than most. Would you be open to sharing a view?",
                                       "Hi {FIRST_NAME}, we are exploring how product rules are tracked across markets. May I ask you one thing?",
                                       "")):
        out.append(item("li_invite", "all", 1, v if t else "blank", t))
    for tier, tag in (("T1", "operations leaders"), ("T2", "compliance specialists")):
        for step in (1, 2, 3):
            for v in ("V1", "V2", "V3"):
                out.append(item("li_followup", tier, step, v,
                                "Hi {FIRST_NAME}, thanks for connecting. We are exploring a system that checks every product against the rules of "
                                "each market it is sold in, and we are speaking with %s about it. Step %d version %s. "
                                "Is this a problem you see at %s, or is it handled well?" % (tag, step, v, "{COMPANY}"),
                                fallback="Thanks for connecting. We are exploring a system that checks every product against the rules of each "
                                         "market it is sold in. Is this a problem you see, or is it handled well? Step %d %s %s." % (step, v, tag)))
    for v in ("V1", "V2", "V3"):
        out.append(item("inmail", "T1", 1, v,
                        "Hi {FIRST_NAME}, I work in the office of Jay and Meelan, founders of Yieldify and Reachdesk. They are exploring a system "
                        "that checks every product against the rules of each market. Version %s. Would you share how your team handles this today?" % v,
                        subject="Your view on product rules (%s)" % v))
    return out


def ready_run(slug, test=False, tiers=(("T1", "United Kingdom"), ("T1", "United States"), ("T2", "Germany"))):
    b = stdcopy.deepcopy(BRIEF)
    b["idea"]["test"] = test
    b["idea"]["name"] = "Test Idea"
    b["idea"]["slug"] = slug
    run = make_run(slug, b)
    rows = []
    for i, (tier, country) in enumerate(tiers):
        rows.append({"person_id": "p%d" % i, "tier": tier, "first_name": "A%d" % i, "last_name": "B", "title": "COO", "company": "Co%d" % i,
                     "linkedin_url": "https://www.linkedin.com/in/p%d" % i, "linkedin_active": "yes", "email": "p%d@co.com" % i,
                     "country": country, "domain": "co.com", "status": "ready"})
    d = run.dir / "ready"
    d.mkdir(exist_ok=True)
    write_csv(d / "linkedin.csv", rows, schema.TABS[schema.TAB_READY_LI])
    calls = [{"person_id": "p0", "first_name": "A0", "last_name": "B", "title": "COO", "company": "Co0", "phone": "+44 1", "tier": "T1",
              "country": "United Kingdom", "linkedin_url": "u", "email": "p0@co.com", "idea": "Test Idea", "call_notes": "n", "status": "ready"}]
    write_csv(d / "calls.csv", calls, schema.TABS[schema.TAB_READY_CALLS])
    return run


class FakeSheet:
    def __init__(self):
        self.upserts, self.created, self.shared = [], [], []

    def ensure_schema(self, sid, tabs=None):
        return {}

    def upsert(self, sid, tab, key, recs):
        self.upserts.append((sid, tab, key, [dict(r) for r in recs]))
        return {}

    def create(self, title, tabs=None):
        self.created.append((title, tabs))
        return {"spreadsheetId": "CALL1", "url": "http://sheet/CALL1"}

    def share(self, sid, domain=None, emails=None, role="writer", notify=False):
        self.shared.append((sid, domain, emails, role))
        return {"ok": True}


def approved_copy(run, simulated=False):
    """Draft, review and approve the good items, write copy.json (no sheet)."""
    cd = copydraft.CopyDraft(run)
    rep = cd.ingest(good_items())
    assert rep["blocked"] == 0 and not rep["rejected"], rep
    cd.log_round(1, 0, "ok", simulated)
    cd.approve("tester approved", simulated)
    cd.write(push=True, sc=FakeSheet())
    return cd


# ---- rules ------------------------------------------------------------------------------------------
def rules(body, channel="li_followup", step=1, **kw):
    it = {"channel": channel, "tier": "T1", "step": step, "variant": "V1", "body": body}
    it.update(kw)
    r = copyrules.check(it, kw.pop("ctx", {"idea_name": "BlissWholesaler", "idea_slug": "blisswholesaler"}))
    return {e["rule"] for e in r["errors"]}, {w["rule"] for w in r["warnings"]}


class TestCopyRules(unittest.TestCase):
    def test_pay_without_a_pay_word_or_currency(self):  # added in the Phase 3 review
        self.assertIn("pay_number", rules("We would offer $300 for your time. Would you be open to it?")[0])
        self.assertIn("pay_number", rules("We are paying advisors $500. Would you be open to it?")[0])
        self.assertIn("pay_number", rules("It is 250 per hour. Would you be open to it?")[0])
        self.assertIn("pay_number", rules("A $100 gift card as thanks. Would you be open to it?")[0])
        self.assertNotIn("pay_number", rules("We spoke to 40 operators in the UK. Does this match what you see?")[0])

    def test_em_dash_and_en_dash(self):
        self.assertIn("em_dash", rules("Hi {FIRST_NAME} \u2014 does this match?")[0])
        self.assertIn("em_dash", rules("Hi {FIRST_NAME} \u2013 does this match?")[0])
        self.assertNotIn("em_dash", rules("Hi {FIRST_NAME}, does this match?")[0])

    def test_links_blocked_in_first_messages_only(self):
        self.assertIn("link", rules("See https://x.com now", "li_followup", 1)[0])
        self.assertIn("link", rules("see calendly.com/jay", "li_invite", 1)[0])
        self.assertIn("link", rules("see example.co/x", "inmail", 1, subject="s")[0])
        e, w = rules("Book here: https://calendly.com/jay/x", "li_followup", 3)
        self.assertNotIn("link", e)
        self.assertIn("link", w)

    def test_filler_is_an_error(self):
        for phrase in ("quick chat", "just checking in", "touching base", "Quick call?", "hope this finds you well", "following up"):
            self.assertIn("filler", rules("Hi {FIRST_NAME}, " + phrase + ".")[0], phrase)
        self.assertIn("spam_phrase", rules("Hi {FIRST_NAME}, let us circle back.")[0])

    def test_internal_idea_names_never_appear(self):
        self.assertIn("internal_idea_name", rules("We are building BlissSLM for you.")[0])
        self.assertIn("internal_idea_name", rules("We are building BlissWholesaler.")[0])
        self.assertIn("internal_idea_name", rules("Our BlissNewThing project")[0])
        e, _ = rules("Blissgrowth is a venture studio. Does this match your view?")
        self.assertNotIn("internal_idea_name", e)
        self.assertNotIn("spelling", e)

    def test_blissgrowth_spelling(self):
        self.assertIn("spelling", rules("We are Bliss growth, a studio.")[0])
        self.assertIn("spelling", rules("We are BlissGrowth, a studio.")[0])
        self.assertNotIn("spelling", rules("We are Blissgrowth, a studio.")[0])

    def test_time_commitment_and_pay(self):
        for t in ("Could we do 30 min this week?", "a 15-minute call", "an hour of your time", "a brief call", "a few minutes"):
            self.assertIn("time_commitment", rules(t)[0], t)
        self.assertIn("pay_number", rules("We pay $200 per hour for advice")[0])
        self.assertIn("pay_number", rules("a fee of £500")[0])
        self.assertNotIn("pay_number", rules("Reachdesk (valued at $225M) is where I started")[0])

    def test_funding_amounts(self):
        self.assertIn("funding_amount", rules("We raised $5m in a seed round")[0])
        e, _ = rules("Yieldify (Google backed and sold to Publicis) and Reachdesk (valued at $225M). Does this fit?")
        self.assertEqual(e, set())

    def test_cos_lists_ported(self):
        self.assertIn("spam_phrase", rules("we should circle back soon")[0])
        self.assertIn("spam_promo", rules("This is a special offer")[0])
        self.assertIn("spam_phishing", rules("please verify identity")[0])
        self.assertIn("silence_closeout", rules("If I don't hear back, I will leave you alone.")[0])
        self.assertIn("exclamations", rules("Great!! Really!!")[0])
        self.assertEqual(len(copyrules.BANNED_WORDS), 32)

    def test_single_words_warn_on_linkedin_error_on_email(self):
        e, w = rules("Could I get your view on new rules now?")
        self.assertNotIn("spam_word", e)
        self.assertIn("spam_word", w)
        e2, _ = rules("Could I get your view on new rules now?", "email", 1)
        self.assertIn("spam_word", e2)

    def test_placeholders_and_fallback(self):
        e, _ = rules("Hi {FIRSTNAME}, hello?")
        self.assertIn("placeholder", e)
        e, _ = rules("Hi {FIRST_NAME}, how is {COMPANY} handling this?")
        self.assertIn("fallback_needed", e)
        e, _ = rules("Hi {FIRST_NAME}, how is {COMPANY} handling this?", fallback="Hi {FIRST_NAME}, how are you handling this?")
        self.assertNotIn("fallback_needed", e)
        e, _ = rules("Hi {FIRST_NAME}, how is {COMPANY}?", fallback="How is {COMPANY}?")
        self.assertIn("fallback_vars", e)

    def test_limits(self):
        e, _ = rules("x" * 301, "li_invite")
        self.assertIn("too_long", e)
        e, _ = rules("x" * 1901, "inmail", subject="s")
        self.assertIn("too_long", e)
        e, _ = rules("hello there?", "inmail", subject="")
        self.assertIn("subject", e)
        e, _ = rules("", "li_followup")
        self.assertIn("empty", e)
        e, _ = rules("", "li_invite", variant="blank")
        self.assertEqual(e, set())

    def test_warnings_for_tone_length_caps_question(self):
        _, w = rules("Book a demo of our platform. PRICING is low.")
        self.assertIn("sales_tone", w)
        self.assertIn("all_caps", w)
        self.assertIn("no_question", w)
        self.assertIn("length", w)

    def test_good_items_pass(self):
        ctx = {"idea_name": "Test Idea", "idea_slug": "x"}
        for it in good_items():
            r = copyrules.check(it, ctx)
            self.assertEqual(r["errors"], [], (it["body"], r["errors"]))


# ---- copy library -------------------------------------------------------------------------------------
class FakeHR:
    def __init__(self):
        self.camps = [
            {"id": 1, "name": "BlissWholesaler - Advisory [T1] [COO] [USA] - Jay & Meelan (Punith)", "status": "IN_PROGRESS",
             "creationTime": "2026-10-20T03:15:20Z", "progressStats": {"totalUsers": 90}, "linkedInUserListName": "L"},
            {"id": 2, "name": "draft one", "status": "DRAFT", "creationTime": "2026-10-20T03:15:20Z", "progressStats": {}},
            {"id": 3, "name": "broken", "status": "PAUSED", "creationTime": "2026-10-20T03:15:20Z", "progressStats": {}}]

    def campaigns(self):
        return self.camps

    def sequence(self, cid):
        if cid == 3:
            raise heyreach.HeyReachError("boom")
        return REAL_SEQ

    def stats(self, cid):
        return {"connectionsSent": 100, "connectionsAccepted": 14, "connectionAcceptanceRate": 0.14, "messagesSent": 20,
                "totalMessageReplies": 5, "messageReplyRate": 0.25}


class TestCopyLibrary(unittest.TestCase):
    def test_flatten_and_structure_of_a_real_sequence(self):
        steps = copylib.flatten(REAL_SEQ)
        types = [s["type"] for s in steps]
        self.assertEqual(types[0], "CHECK_IS_CONNECTION")
        self.assertIn("INMAIL", types)
        self.assertEqual(sum(1 for t in types if t == "MESSAGE"), 4)
        self.assertEqual(copylib.describe_tree(REAL_SEQ), "CHECK(connected: end | new: INVITE(blank)(accepted: LIKE > MSG x4 | not: INMAIL))")

    def test_templating(self):
        t = copylib.templatize("Hi {FIRST_NAME}, we are building an AI company that automates compliance. BlissSLM at https://x.com/a. Fine.")
        self.assertIn("building {IDEA_PLAIN}", t)
        self.assertNotIn("BlissSLM", t)
        self.assertIn("{IDEA_NAME}", t)
        self.assertIn("{LINK}", t)
        self.assertIn("{FIRST_NAME}", t)
        self.assertIn("Blissgrowth", copylib.templatize("Blissgrowth studio"))

    def test_parse_name_and_classify(self):
        m = copylib.parse_name("BlissWholesaler - Advisory [T1] [COO] [UK, EU] - Jay & Meelan (Punith)")
        self.assertEqual((m["idea"], m["sender"]), ("BlissWholesaler", "Jay & Meelan"))
        self.assertIn("UK", m["regions"])
        self.assertIn("EU", m["regions"])
        self.assertIn("COO", m["persona"])
        self.assertIn("advisor ask", copylib.classify("I'd love for you to be an advisor", 0, 4))
        self.assertIn("opinion question", copylib.classify("Do you agree?", 1, 4))
        self.assertTrue(copylib.classify("", 0, 1, blank=True).startswith("Blank invite"))

    def test_build_writes_one_file_per_campaign_and_skips_drafts(self):
        import tempfile
        out = tempfile.mkdtemp(prefix="lib-")
        res = copylib.build(FakeHR(), out, log=lambda *_: None)
        self.assertEqual(res["campaigns"], 1)
        reasons = {s["name"]: s["why"] for s in res["skipped"]}
        self.assertIn("draft", reasons["draft one"])
        self.assertIn("sequence error", reasons["broken"])
        files = os.listdir(os.path.join(out, "campaigns"))
        self.assertEqual(sorted(f.rsplit(".", 1)[1] for f in files), ["json", "md"])
        idx = json.load(open(os.path.join(out, "index.json")))
        self.assertEqual(idx["campaigns"][0]["idea"], "BlissWholesaler")
        md = open(os.path.join(out, "campaigns", [f for f in files if f.endswith(".md")][0])).read()
        self.assertIn("{IDEA_PLAIN}", md)
        self.assertNotIn("\u2014", md)
        self.assertEqual(copylib.dedash("a \u2014 b \u2013 c"), "a - b - c")
        self.assertNotIn("\u2014", json.dumps(idx, ensure_ascii=False))
        self.assertIn("Rules today", md)
        self.assertIn("Copy library index", open(os.path.join(out, "index.md")).read())

    def test_shipped_library_has_index_and_per_campaign_files(self):
        lib = config.IDEA_LAUNCH_DIR / "copy-library"
        if not (lib / "index.json").exists():
            self.skipTest("library not built on this machine")
        idx = json.load(open(lib / "index.json"))
        for c in idx["campaigns"]:
            self.assertTrue((lib / c["file"]).exists(), c["file"])
        self.assertIn("Copy library index", (lib / "index.md").read_text())


# ---- HeyReach client -------------------------------------------------------------------------------------
class FakeTransport:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, url, headers, data, timeout):
        self.calls.append((method, url, headers, data))
        st, body = self.answers.pop(0)
        return st, {"retry-after": "0"}, json.dumps(body).encode()


class TestHeyReachClient(unittest.TestCase):
    def test_key_sent_in_header_and_never_in_errors(self):
        tr = FakeTransport([(500, {"error": "x"})])
        h = heyreach.HeyReach(key="SECRETKEY123", transport=tr, sleep=lambda s: None, min_interval_s=0)
        with self.assertRaises(heyreach.HeyReachError) as cm:
            h.campaign(5)
        self.assertNotIn("SECRETKEY123", str(cm.exception))
        self.assertEqual(tr.calls[0][2]["X-API-KEY"], "SECRETKEY123")
        self.assertIn("campaignId=5", tr.calls[0][1])

    def test_pagination_and_429_retry(self):
        tr = FakeTransport([(429, {}), (200, {"totalCount": 3, "items": [{"id": 1}, {"id": 2}]}), (200, {"totalCount": 3, "items": [{"id": 3}]})])
        h = heyreach.HeyReach(key="k", transport=tr, sleep=lambda s: None, min_interval_s=0)
        self.assertEqual([c["id"] for c in h.campaigns()], [1, 2, 3])

    def test_writes_are_not_retried(self):
        tr = FakeTransport([(500, {"e": 1}), (200, {"id": 9})])
        h = heyreach.HeyReach(key="k", transport=tr, sleep=lambda s: None, min_interval_s=0)
        with self.assertRaises(heyreach.HeyReachError):
            h.create_list("x")
        self.assertEqual(len(tr.calls), 1)

    def test_no_start_resume_pause_delete_anywhere(self):
        src = open(os.path.join(HERE, "..", "lib", "heyreach.py"), encoding="utf-8").read()
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        for forbidden in ("Start", "Resume", "Pause", "Delete", "Stop", "campaign/start", "def start", "def resume", "def pause", "def delete"):
            self.assertNotIn(forbidden, code, forbidden)
        self.assertEqual([m for m in dir(heyreach.HeyReach) if re.search("start|resume|pause|delete|stop", m, re.I)], [])
        # and nothing in launch.py calls a client method outside the allowed set
        lsrc = open(os.path.join(HERE, "..", "lib", "launch.py"), encoding="utf-8").read()
        used = set(re.findall(r"client\.(\w+)\(", lsrc))
        self.assertEqual(used, {"find_list", "create_list", "add_leads", "find_campaign", "create_campaign", "update_sequence", "campaign"})

    def test_add_leads_batch_bounds(self):
        h = heyreach.HeyReach(key="k", transport=FakeTransport([]), sleep=lambda s: None, min_interval_s=0)
        with self.assertRaises(heyreach.HeyReachError):
            h.add_leads(1, [])
        with self.assertRaises(heyreach.HeyReachError):
            h.add_leads(1, [{}] * 101)


# ---- per-run copy ----------------------------------------------------------------------------------------
class TestCopyDraft(unittest.TestCase):
    def test_shape_validation_rejects_bad_items(self):
        run = ready_run("cd1")
        cd = copydraft.CopyDraft(run)
        bad = [item("li_followup", "T3", 1, "V1", "x"), item("li_followup", "T1", 0, "V1", "x"), item("li_followup", "T1", 1, "Vx", "x"),
               item("inmail", "T1", 1, "V1", "x", sender="founder"), item("li_followup", "T1", 1, "V1", "x", sender="associate"),
               item("li_followup", "T1", 1, "V1", "x", subject="s"), item("pdf", "T1", 1, "V1", "x")]
        rep = cd.ingest(bad)
        self.assertEqual(rep["ok"] + rep["blocked"], 0)
        self.assertEqual(len(rep["rejected"]), len(bad))

    def test_rule_errors_block_but_are_stored_and_visible(self):
        run = ready_run("cd2")
        cd = copydraft.CopyDraft(run)
        rep = cd.ingest([item("li_followup", "T1", 1, "V1", "Hi {FIRST_NAME}, quick chat about BlissSLM?")])
        self.assertEqual((rep["ok"], rep["blocked"]), (0, 1))
        self.assertEqual(cd.items()[0]["status"], "blocked")
        self.assertIn("BLOCKED", cd.render())
        self.assertTrue(cd.completeness()["blocked"])

    def test_completeness_and_last_record_wins(self):
        run = ready_run("cd3")
        cd = copydraft.CopyDraft(run)
        self.assertEqual(cd.tiers_present(), {"T1": 2, "T2": 1})
        c = cd.completeness()
        self.assertFalse(c["ok"])
        self.assertTrue(any("li_invite T1" in m for m in c["missing"]))
        cd.ingest(good_items())
        self.assertTrue(cd.completeness()["ok"], cd.completeness())
        # replace one item: the later record wins
        cd.ingest([item("li_followup", "T1", 1, "V1", "Hi {FIRST_NAME}, version two of this text. Does this match what you see?",)])
        self.assertTrue([i["body"] for i in cd.items() if i["id"] == "li_followup|T1|1|V1"][0].startswith("Hi {FIRST_NAME}, version two"))
        # too few variants
        cd.withdraw("li_followup|T2|2|V3")
        self.assertTrue(any("li_followup T2 step 2" in m for m in cd.completeness()["thin"]))

    def test_inmail_only_for_configured_tiers(self):
        run = ready_run("cd4")
        slots = copydraft.CopyDraft(run).required_slots()
        self.assertIn(("inmail", "T1", 1), slots)
        self.assertNotIn(("inmail", "T2", 1), slots)

    def test_approval_needs_a_clean_review_of_exactly_these_items(self):
        run = ready_run("cd5")
        cd = copydraft.CopyDraft(run)
        cd.ingest(good_items())
        with self.assertRaises(copydraft.CopyError):
            cd.approve("me")  # no tuning round yet
        cd.log_round(1, 2, "user changed two things")
        with self.assertRaises(copydraft.CopyError):
            cd.approve("me")  # round had corrections
        cd.log_round(2, 0, "clean")
        with self.assertRaises(copydraft.CopyError):
            cd.approve("")  # note required
        a = cd.approve("Afroz approved on chat")
        self.assertFalse(a["simulated"])
        self.assertTrue(cd.approval_valid())
        # editing after approval makes it stale
        cd.ingest([item("li_followup", "T1", 1, "V1", "Hi {FIRST_NAME}, changed after approval. Is this still how you see it?")])
        self.assertFalse(cd.approval_valid())
        self.assertTrue(cd.status()["stale_approval"])

    def test_cannot_approve_with_blockers_or_gaps(self):
        run = ready_run("cd6")
        cd = copydraft.CopyDraft(run)
        cd.ingest(good_items()[:5])
        cd.log_round(1, 0)
        with self.assertRaises(copydraft.CopyError):
            cd.approve("x")

    def test_write_copy_json_and_sheet_rows(self):
        run = ready_run("cd7")
        cd = copydraft.CopyDraft(run)
        cd.ingest(good_items())
        fs = FakeSheet()
        rep = cd.write(push=True, sc=fs)
        self.assertEqual(rep["approved"], False)
        rows = fs.upserts[0][3]
        self.assertTrue(all(r["status"] == "draft" for r in rows))
        for col in ("channel", "tier", "step", "variant", "subject", "body", "status", "notes", "copy_id", "sender", "words"):
            self.assertIn(col, rows[0])
            self.assertIn(col, schema.TABS[schema.TAB_COPY])
        cd.log_round(1, 0, simulated=True)
        cd.approve("SIM", simulated=True)
        fs2 = FakeSheet()
        cd.write(push=True, sc=fs2)
        self.assertTrue(all(r["status"] == "approved (SIMULATED)" for r in fs2.upserts[0][3]))
        fin = read_json(run.dir / "copy.json")
        self.assertTrue(fin["approved"] and fin["simulated"])
        # second write sends nothing new
        fs3 = FakeSheet()
        cd.write(push=True, sc=fs3)
        self.assertEqual(fs3.upserts, [])

    def test_context_has_what_the_drafter_needs(self):
        run = ready_run("cd8")
        ctx = copydraft.CopyDraft(run).context()
        self.assertIn("li_followup|T1|2", ctx["required_slots"])
        self.assertIn("test idea", ctx["rules"]["never_names"])
        self.assertIn("founder", ctx["voices"])

    def test_stage_copy_lifecycle(self):
        run = ready_run("cd9")
        # copy waits for the ready stage: here only check the checker directly
        done = {"ready": {"status": "done"}}
        self.assertEqual(stages.check_copy(run, done)["status"], "pending")
        cd = copydraft.CopyDraft(run)
        cd.ingest(good_items()[:4])
        self.assertEqual(stages.check_copy(run, done)["status"], "partial")
        cd.ingest(good_items())
        self.assertIn("approval", stages.check_copy(run, done)["detail"])
        cd.log_round(1, 0)
        cd.approve("real user")
        self.assertIn("run copy_run.py write", stages.check_copy(run, done)["detail"])
        cd.write(push=False)
        self.assertIn("8 Copy tab not pushed", stages.check_copy(run, done)["detail"])  # the run has a sheet, the push marker is missing
        cd.write(push=True, sc=FakeSheet())
        self.assertEqual(stages.check_copy(run, done)["status"], "done")


# ---- idea page -------------------------------------------------------------------------------------------
def page_fields(**over):
    f = {"Idea": "Test Idea", "Campaign prefix": "BlissTestIdea", "Calendly (Jay)": "https://calendly.com/d/aaa/testidea",
         "Calendly (Meelan)": "https://calendly.com/d/bbb/testidea", "Pitch": "A system that checks every product against each market's rules.",
         "Who we're targeting": "A) Operations leaders at distributors.\nB) Owners.", "Idea specifics": "Early stage, advisor role. Never give amounts."}
    f.update(over)
    return f


class TestIdeaPage(unittest.TestCase):
    def test_validation(self):
        ip = ideapage.IdeaPage(ready_run("ip1"))
        self.assertEqual(ip.validate(page_fields())[0], [])
        self.assertTrue(ip.validate(page_fields(Pitch=""))[0])
        self.assertTrue(any("dash" in e for e in ip.validate(page_fields(Pitch="a \u2014 b"))[0]))
        self.assertTrue(any("funding" in e for e in ip.validate(page_fields(**{"Idea specifics": "We raised $5m in a seed round"}))[0]))
        self.assertTrue(any("calendly" in e for e in ip.validate(page_fields(**{"Calendly (Jay)": "http://x.com"}))[0]))
        self.assertTrue(any("unknown" in e for e in ip.validate(page_fields(Notes="x"))[0]))
        self.assertTrue(any("limit" in e for e in ip.validate(page_fields(Pitch="x" * 2001))[0]))
        errs, warns = ip.validate(page_fields(**{"Calendly (Jay)": ""}))
        self.assertEqual(errs, [])
        self.assertTrue(any("Jay" in w for w in warns))
        self.assertTrue(any("Blissgrowth" in e for e in ip.validate(page_fields(Pitch="Bliss growth studio"))[0]))
        self.assertTrue(any("reply agent ignores" in e for e in ip.validate(page_fields(**{"Campaign prefix": "ProductRules"}))[0]))

    def test_starter_comes_from_the_brief(self):
        st = ideapage.IdeaPage(ready_run("ip2")).starter()
        self.assertEqual(st["Idea"], "Test Idea")
        self.assertIn("budget holder", st["Who we're targeting"])

    def test_payload_needs_confirmation_and_text_change_unconfirms(self):
        ip = ideapage.IdeaPage(ready_run("ip3"))
        ip.set_fields(page_fields())
        with self.assertRaises(ideapage.IdeaPageError):
            ip.payload()
        with self.assertRaises(ideapage.IdeaPageError):
            ip.confirm("")
        ip.confirm("Afroz read and confirmed")
        pl = ip.payload()
        self.assertEqual(pl["tool"], "mcp__claude_ai_Notion__notion-create-pages")
        self.assertEqual(pl["arguments"]["parent"]["data_source_id"], "3d6bd3e8-f4a2-4ea6-a266-4ce299131652")
        props = pl["arguments"]["pages"][0]["properties"]
        self.assertEqual(set(props), set(page_fields()))
        self.assertIn("string_is", pl["before"])
        ip.set_fields(page_fields(Pitch="Changed text."))
        with self.assertRaises(ideapage.IdeaPageError):
            ip.payload()  # confirmation was for the old text

    def test_test_payload_is_clearly_marked(self):
        ip = ideapage.IdeaPage(ready_run("ip4"))
        ip.set_fields(page_fields())
        ip.confirm("sim", simulated=True)
        props = ip.payload(test=True)["arguments"]["pages"][0]["properties"]
        self.assertTrue(props["Idea"].startswith("TEST DELETE ME"))
        self.assertTrue(props["Campaign prefix"].startswith("TEST-DELETE-ME-"))

    def test_never_created_twice(self):
        run = ready_run("ip5")
        ip = ideapage.IdeaPage(run)
        ip.set_fields(page_fields())
        ip.confirm("ok")
        r = ip.save_record("https://app.notion.com/p/Test-Idea-3fe7b03862a781279744f65aacb7b011")
        self.assertEqual(r["page_id"], "3fe7b03862a781279744f65aacb7b011")
        self.assertEqual(ideapage.page_id_from_url("https://app.notion.com/p/4007b03862a781dd8d2ff1a5053fe8f2?pvs=204"),
                         "4007b03862a781dd8d2ff1a5053fe8f2")
        with self.assertRaises(ideapage.IdeaPageError):
            ip.payload()
        with self.assertRaises(ideapage.IdeaPageError):
            ip.save_record("https://app.notion.com/p/other")
        with self.assertRaises(ideapage.IdeaPageError):
            ideapage.IdeaPage(run).save_record("not a url")

    def test_stage_lifecycle_and_skip(self):
        run = ready_run("ip6")
        done = {"ready": {"status": "done"}}
        ip = ideapage.IdeaPage(run)
        self.assertEqual(stages.check_idea_page(run, done)["status"], "pending")
        ip.set_fields(page_fields())
        self.assertEqual(stages.check_idea_page(run, done)["status"], "partial")
        ip.confirm("ok")
        self.assertIn("Notion MCP", stages.check_idea_page(run, done)["detail"])
        ip.save_record("https://app.notion.com/p/x-aaaa", test=True)
        st = stages.check_idea_page(run, done)
        self.assertEqual(st["status"], "partial")  # review fix: a TEST page never completes a real (non-test) run
        self.assertIn("TEST", st["detail"])
        b = run.brief()
        b["idea"]["test"] = True
        write_json(run.brief_path, b)
        st = stages.check_idea_page(run, done)
        self.assertEqual(st["status"], "done")
        self.assertIn("TEST", st["detail"])
        run2 = ready_run("ip7")
        ideapage.IdeaPage(run2).skip("page exists already")
        self.assertEqual(stages.check_idea_page(run2, done)["status"], "skipped")

    def test_sync_status_reads_rows_only(self):
        run = ready_run("ip8")
        ip = ideapage.IdeaPage(run)
        self.assertIsNone(ip.sync_status()["synced"])
        ip.set_fields(page_fields())
        ip.confirm("ok")
        ip.save_record("https://app.notion.com/p/x-3fe7b03862a781279744f65aacb7b011")
        rows = [{"notion_page_id": "3fe7b038-62a7-8127-9744-f65aacb7b011", "campaign_prefix": "BlissSLM"}]
        self.assertTrue(ip.sync_status(lambda: rows)["synced"])
        self.assertFalse(ip.sync_status(lambda: [])["synced"])


# ---- launch ----------------------------------------------------------------------------------------------
class FakeHRWrite:
    """Records every call. Has only the methods the real client has (no start, resume, pause, delete)."""
    def __init__(self, existing_lists=(), existing_campaigns=(), status="DRAFT", fail_on=None):
        self.calls, self.lists, self.camps = [], list(existing_lists), list(existing_campaigns)
        self.status, self.fail_on, self.n = status, fail_on, 100

    def _c(self, name, *a):
        self.calls.append((name,) + a)
        if self.fail_on == name:
            self.fail_on = None
            raise heyreach.HeyReachError("simulated failure in " + name)

    def find_list(self, name):
        self._c("find_list", name)
        return [x for x in self.lists if x["name"] == name]

    def create_list(self, name):
        self._c("create_list", name)
        self.n += 1
        self.lists.append({"id": self.n, "name": name})
        return {"id": self.n}

    def add_leads(self, list_id, leads):
        self._c("add_leads", list_id, len(leads))
        return {}

    def find_campaign(self, name):
        self._c("find_campaign", name)
        return [x for x in self.camps if x["name"] == name]

    def create_campaign(self, name, list_id, account_ids, **flags):
        self._c("create_campaign", name, list_id, tuple(account_ids))
        self.n += 1
        self.camps.append({"id": self.n, "name": name})
        return {"id": self.n}

    def update_sequence(self, cid, seq):
        self._c("update_sequence", cid)
        return {}

    def campaign(self, cid):
        self._c("campaign", cid)
        return {"id": cid, "status": self.status}


def launch_ready(slug, **kw):
    run = ready_run(slug, **kw)
    approved_copy(run)
    config.cfg()["launch"]["senders"] = {"founders": {"jay": 11, "meelan": 12}, "associate": 13}
    ideapage.IdeaPage(run).skip("tests: no idea page")
    return run


class TestLaunch(unittest.TestCase):
    def setUp(self):
        config.cfg()["launch"]["prefix_must_start_with"] = ""  # test runs are named "Test Idea"

    def tearDown(self):
        config.cfg()["launch"]["prefix_must_start_with"] = "bliss"
        config.cfg()["launch"]["senders"] = {"founders": {"jay": None, "meelan": None}, "associate": None}
        config.cfg()["launch"]["mansi_email"] = ""
        config.cfg()["launch"]["lead_batch"] = 100

    def test_review_prefix_from_idea_page_and_reply_agent_rule(self):  # added in the Phase 3 review
        run = launch_ready("l20")
        write_json(run.dir / "idea-page.json", {"page_url": "https://x", "prefix": "BlissReviewIdea", "test": False})
        p = lmod.plan(run, "2026-10-21")
        self.assertTrue(all(g["list_name"].startswith("BlissReviewIdea - ") for g in p["groups"]))
        config.cfg()["launch"]["prefix_must_start_with"] = "bliss"
        self.assertEqual(lmod.plan(run, "2026-10-21")["blockers"], [])
        write_json(run.dir / "idea-page.json", {"page_url": "https://x", "prefix": "ReviewIdea", "test": False})
        self.assertTrue(any("reply agent ignores" in b for b in lmod.plan(run, "2026-10-21")["blockers"]))
        write_json(run.dir / "idea-page.json", {"page_url": "https://x", "prefix": "TEST-DELETE-ME-X", "test": True})
        self.assertEqual(lmod.prefix_of(run.brief(), run), "Test Idea")  # a TEST page prefix is ignored

    def test_review_test_page_does_not_complete_a_real_run(self):  # added in the Phase 3 review
        run = ready_run("l23")
        write_json(run.dir / "idea-page.json", {"page_url": "https://x", "prefix": "TEST-DELETE-ME-X", "test": True})
        self.assertEqual(stages.check_idea_page(run, {})["status"], "partial")

    def test_review_idea_page_gate(self):  # added in the Phase 3 review
        run = launch_ready("l21")
        (run.dir / "idea-page" / "skipped.json").unlink()
        ln = lmod.Launch(run)
        ln.make_plan("2026-10-21")
        ln.approve("ok")
        self.assertTrue(any("idea page" in g for g in ln.gates(lmod.plan(run, "2026-10-21"))))
        write_json(run.dir / "idea-page.json", {"page_url": "https://x", "prefix": "Test Idea", "test": False})
        self.assertEqual(ln.gates(lmod.plan(run, "2026-10-21")), [])

    def test_review_approve_refuses_a_stale_plan_file(self):  # added in the Phase 3 review
        run = launch_ready("l22")
        ln = lmod.Launch(run)
        ln.make_plan("2026-10-21")
        rows = lmod.read_ready(run, "linkedin")[:2]
        write_csv(run.dir / "ready" / "linkedin.csv", rows, schema.TABS[schema.TAB_READY_LI])
        with self.assertRaises(lmod.LaunchError) as cm:
            ln.approve("ok")
        self.assertIn("out of date", str(cm.exception))

    def test_regions_and_grouping_and_names(self):
        self.assertEqual([lmod.region_of(c) for c in ("United States", "United Kingdom", "Germany", "", "Japan")],
                         ["USA", "UK", "EU", "EU", "EU"])
        run = launch_ready("l1")
        p = lmod.plan(run, "2026-10-21")
        names = sorted(g["list_name"] for g in p["groups"])
        self.assertEqual(names, ["Test Idea - T1 - UK - 2026-10-21", "Test Idea - T1 - USA - 2026-10-21", "Test Idea - T2 - EU - 2026-10-21"])
        camps = {c["name"] for g in p["groups"] for c in g["campaigns"]}
        self.assertIn("Test Idea - T1 - UK - 2026-10-21 - InMail", camps)  # InMail for T1 only
        self.assertNotIn("Test Idea - T2 - EU - 2026-10-21 - InMail", camps)
        self.assertEqual(p["leads_total"], 3)
        self.assertEqual(p["blockers"], [])

    def test_sequences_validate_and_carry_variants(self):
        items = [dict(i, step=i["step"]) for i in copydraft_items()]
        seq = lmod.build_connect_sequence(items, "T1")
        self.assertEqual(lmod.validate_sequence(seq), [])
        self.assertEqual(seq["nodeType"], "CHECK_IS_CONNECTION")
        req = seq["unconditionalNode"]
        self.assertEqual(req["nodeType"], "CONNECTION_REQUEST")
        self.assertEqual(len(req["payload"]["messages"]), 3)
        self.assertIn("", req["payload"]["messages"])  # the blank invite is a variant
        self.assertEqual(req["payload"]["toBeWithdrawnAfterDays"], 14)
        self.assertEqual(req["unconditionalNode"]["nodeType"], "END")
        node, n_msg = req["conditionalNode"], 0
        self.assertEqual(node["nodeType"], "LIKE_POST")
        node = node["unconditionalNode"]
        while node["nodeType"] == "MESSAGE":
            n_msg += 1
            self.assertEqual(len(node["payload"]["messages"]), 3)
            self.assertEqual(node["conditionalNode"]["nodeType"], "END")
            self.assertTrue(node["payload"]["fallbackMessage"])
            node = node["unconditionalNode"]
        self.assertEqual((n_msg, node["nodeType"]), (3, "END"))
        im = lmod.build_inmail_sequence(items, "T1")
        self.assertEqual(lmod.validate_sequence(im), [])
        self.assertEqual(im["unconditionalNode"]["nodeType"], "INMAIL")
        self.assertEqual(len(im["unconditionalNode"]["payload"]["messages"]), 3)
        self.assertTrue(im["unconditionalNode"]["payload"]["messages"][0]["subject"])

    def test_tier_specific_copy_beats_all(self):
        items = copydraft_items()
        t1 = lmod.build_connect_sequence(items, "T1")
        t2 = lmod.build_connect_sequence(items, "T2")
        m1 = t1["unconditionalNode"]["conditionalNode"]["unconditionalNode"]["payload"]["messages"][0]
        m2 = t2["unconditionalNode"]["conditionalNode"]["unconditionalNode"]["payload"]["messages"][0]
        self.assertIn("operations leaders", m1)
        self.assertIn("compliance specialists", m2)

    def test_validator_accepts_real_sequence_and_catches_problems(self):
        self.assertEqual(lmod.validate_sequence(REAL_SEQ), [])
        self.assertTrue(lmod.validate_sequence({}))
        bad = {"nodeType": "MESSAGE", "actionDelay": 0, "actionDelayUnit": "HOUR", "payload": {"messages": ["hi"]}}
        probs = " ".join(lmod.validate_sequence(bad))
        self.assertIn("connected", probs)
        self.assertIn("conditional END", probs)
        seq = stdcopy.deepcopy(REAL_SEQ)
        req = seq["unconditionalNode"]
        req["payload"]["messages"] = ["x" * 301]
        self.assertIn("over 300", " ".join(lmod.validate_sequence(seq)))
        seq = stdcopy.deepcopy(REAL_SEQ)
        like = seq["unconditionalNode"]["conditionalNode"]
        like["unconditionalNode"]["actionDelay"] = 1
        self.assertIn("at least 3 hours", " ".join(lmod.validate_sequence(seq)))
        seq = stdcopy.deepcopy(REAL_SEQ)
        msg = seq["unconditionalNode"]["conditionalNode"]["unconditionalNode"]
        msg["payload"]["messages"] = ["Hi {COMPANY}"]
        msg["payload"]["fallbackMessage"] = ""
        self.assertIn("fallbackMessage", " ".join(lmod.validate_sequence(seq)))
        seq = stdcopy.deepcopy(REAL_SEQ)
        seq["unconditionalNode"]["conditionalNode"] = None
        self.assertIn("both branches", " ".join(lmod.validate_sequence(seq)))

    def test_auto_fallback(self):
        self.assertEqual(lmod.auto_fallback("Hi {FIRST_NAME}, do you agree, {FIRST_NAME}?"), "Hi there, do you agree?")

    def test_plan_hash_changes_with_copy_and_gates(self):
        run = launch_ready("l2")
        ln = lmod.Launch(run)
        p = ln.make_plan("2026-10-21")
        g = ln.gates(p)
        self.assertTrue(any("no launch approval" in x for x in g))
        ln.approve("Afroz approved")
        self.assertEqual(ln.gates(ln.make_plan("2026-10-21")), [])
        h1 = p["plan_hash"]
        cd = copydraft.CopyDraft(run)
        cd.ingest([item("li_followup", "T1", 1, "V1", "Hi {FIRST_NAME}, a different first message. Does this match what you see in your work?",
                        fallback="A different first message. Does this match what you see in your work?")])
        cd.log_round(2, 0)
        cd.approve("again")
        cd.write(push=True, sc=FakeSheet())
        p2 = ln.make_plan("2026-10-21")
        self.assertNotEqual(p2["plan_hash"], h1)
        self.assertTrue(any("changed since it was approved" in x for x in ln.gates(p2)))

    def test_refusals(self):
        # TEST brief
        run = launch_ready("l3", test=True)
        ln = lmod.Launch(run)
        ln.make_plan("2026-10-21")
        ln.approve("ok")
        with self.assertRaises(lmod.LaunchError) as cm:
            ln.execute(FakeHRWrite())
        self.assertIn("TEST brief", str(cm.exception))
        # simulated copy approval
        run = ready_run("l4")
        approved_copy(run, simulated=True)
        config.cfg()["launch"]["senders"] = {"founders": {"jay": 1}, "associate": 2}
        ln = lmod.Launch(run)
        ln.make_plan("2026-10-21")
        ln.approve("sim", simulated=True)
        why = " ".join(ln.gates(lmod.plan(run, "2026-10-21")))
        self.assertIn("copy approval is SIMULATED", why)
        self.assertIn("launch approval is SIMULATED", why)
        # missing senders
        config.cfg()["launch"]["senders"] = {"founders": {"jay": None, "meelan": None}, "associate": None}
        run = ready_run("l5")
        approved_copy(run)
        ln = lmod.Launch(run)
        ln.make_plan("2026-10-21")
        ln.approve("ok")
        why = " ".join(ln.gates(lmod.plan(run, "2026-10-21")))
        self.assertIn("founders has no HeyReach account id", why)
        self.assertIn("launch.senders.associate is null", why)

    def test_cannot_approve_without_plan_or_with_blockers(self):
        run = launch_ready("l6")
        ln = lmod.Launch(run)
        with self.assertRaises(lmod.LaunchError):
            ln.approve("x")
        p = ln.make_plan("2026-10-21")
        p["blockers"] = ["x"]
        write_json(ln.plan_path, p)
        with self.assertRaises(lmod.LaunchError):
            ln.approve("x")

    def test_execute_creates_drafts_only_and_is_idempotent(self):
        run = launch_ready("l7")
        config.cfg()["launch"]["lead_batch"] = 1
        ln = lmod.Launch(run)
        ln.make_plan("2026-10-21")
        ln.approve("Afroz approved the plan")
        hr = FakeHRWrite()
        st = ln.execute(hr, log=lambda *_: None) if False else ln.execute(hr, log=lambda *_: None)
        names = [c[0] for c in hr.calls]
        self.assertEqual(names.count("create_list"), 3)
        self.assertEqual(names.count("create_campaign"), 5)  # 3 connect + InMail for T1 UK and T1 US (T2 has none)
        self.assertEqual(names.count("update_sequence"), 5)
        self.assertEqual(names.count("add_leads"), 3)  # batch size 1, one lead per group
        self.assertTrue(st["executed"])
        self.assertEqual(set(names) - {"find_list", "create_list", "add_leads", "find_campaign", "create_campaign", "update_sequence", "campaign"}, set())
        accounts = {c[1]: c[3] for c in hr.calls if c[0] == "create_campaign"}
        self.assertIn((13,), accounts.values())  # the associate sends the InMails
        self.assertIn((11, 12), accounts.values())  # Jay and Meelan send the connect campaigns
        # second run creates nothing
        hr2 = FakeHRWrite(existing_lists=hr.lists, existing_campaigns=hr.camps)
        ln.execute(hr2, log=lambda *_: None)
        self.assertEqual([c[0] for c in hr2.calls if c[0].startswith(("create", "add", "update"))], [])

    def test_resumes_after_a_failure_without_duplicates(self):
        run = launch_ready("l8")
        ln = lmod.Launch(run)
        ln.make_plan("2026-10-21")
        ln.approve("ok")
        hr = FakeHRWrite(fail_on="update_sequence")
        with self.assertRaises(heyreach.HeyReachError):
            ln.execute(hr, log=lambda *_: None)
        first_lists = len(hr.lists)
        ln.execute(hr, log=lambda *_: None)
        self.assertEqual(len(hr.lists), 3)
        self.assertGreaterEqual(first_lists, 1)
        self.assertEqual(len({c["name"] for c in hr.camps}), len(hr.camps))  # no duplicate campaign names
        self.assertEqual(len(hr.camps), 5)

    def test_non_draft_status_stops_everything(self):
        run = launch_ready("l9")
        ln = lmod.Launch(run)
        ln.make_plan("2026-10-21")
        ln.approve("ok")
        with self.assertRaises(lmod.LaunchError) as cm:
            ln.execute(FakeHRWrite(status="IN_PROGRESS"), log=lambda *_: None)
        self.assertIn("expected DRAFT", str(cm.exception))

    def test_existing_list_or_campaign_is_never_touched(self):
        run = launch_ready("l10")
        ln = lmod.Launch(run)
        ln.make_plan("2026-10-21")
        ln.approve("ok")
        hr = FakeHRWrite(existing_lists=[{"id": 5, "name": "Test Idea - T1 - UK - 2026-10-21"}])
        with self.assertRaises(lmod.LaunchError) as cm:
            ln.execute(hr, log=lambda *_: None)
        self.assertIn("already exists", str(cm.exception))
        self.assertNotIn("create_list", [c[0] for c in hr.calls])
        hr = FakeHRWrite(existing_campaigns=[{"id": 6, "name": "Test Idea - T1 - UK - 2026-10-21"}])
        with self.assertRaises(lmod.LaunchError):
            lmod.Launch(launch_ready("l11")).execute(hr, log=lambda *_: None)  # not approved: refused before any call
        self.assertEqual(hr.calls, [])

    def test_lead_payload(self):
        lp = lmod.lead_payload({"person_id": "p1", "first_name": "A", "last_name": "B", "linkedin_url": "u", "company": "C", "title": "COO",
                                "country": "UK", "tier": "T1", "email": ""})
        self.assertEqual(lp["profileUrl"], "u")
        self.assertNotIn("emailAddress", lp)
        self.assertEqual({f["name"] for f in lp["customUserFields"]}, {"tier", "person_id"})

    def test_callsheet_dry_run_missing_email_and_execute(self):
        run = launch_ready("l12")
        ln = lmod.Launch(run)
        rep = ln.callsheet(dry_run=True)
        self.assertIn("launch.mansi_email is null", rep["note"])
        config.cfg()["launch"]["mansi_email"] = "mansi@blissgrowth.com"
        rep = ln.callsheet(dry_run=True)
        self.assertEqual(rep["rows"], 1)
        self.assertIn("dry run", rep["note"])
        self.assertIn("call_status", rep["headers"])
        self.assertNotIn("status", rep["headers"])
        fs = FakeSheet()
        rep = ln.callsheet(sc=fs, dry_run=False)
        self.assertEqual(len(fs.created), 1)
        self.assertEqual(fs.shared, [("CALL1", None, ["mansi@blissgrowth.com"], "writer")])  # only Mansi, not the domain
        self.assertEqual(fs.upserts[0][3][0]["person_id"], "p0")
        self.assertNotIn("call_status", fs.upserts[0][3][0])  # her columns are never overwritten
        fs2 = FakeSheet()
        ln.callsheet(sc=fs2, dry_run=False)
        self.assertEqual((fs2.created, fs2.shared, fs2.upserts), ([], [], []))

    def test_callsheet_refuses_test_runs(self):
        run = launch_ready("l13", test=True)
        config.cfg()["launch"]["mansi_email"] = "mansi@blissgrowth.com"
        with self.assertRaises(lmod.LaunchError):
            lmod.Launch(run).callsheet(sc=FakeSheet(), dry_run=False)

    def test_launch_is_after_ready_not_part_of_it(self):
        run = launch_ready("l14")
        st = stages.check_launch(run, {"copy": {"status": "done"}, "idea_page": {"status": "done"}})
        self.assertEqual(st["status"], "pending")
        ln = lmod.Launch(run)
        ln.make_plan("2026-10-21")
        self.assertIn("waiting for the user's approval", stages.check_launch(run, {})["detail"])
        ln.approve("ok")
        self.assertIn("not executed", stages.check_launch(run, {})["detail"])
        ln.execute(FakeHRWrite(), log=lambda *_: None)
        self.assertIn("call sheet for Mansi not created", stages.check_launch(run, {})["detail"])
        self.assertIn("nothing started", stages.check_launch(run, {})["detail"])


def copydraft_items():
    ctx = {"idea_name": "Test Idea", "idea_slug": "x"}
    out = []
    for it in good_items():
        it = dict(it, step=int(it["step"]), id=copyrules.item_id(it))
        it["errors"] = copyrules.check(it, ctx)["errors"]
        out.append(it)
    return out


# ---- orchestrator ----------------------------------------------------------------------------------------
class TestOrchestrator(unittest.TestCase):
    def test_activity_resumes_after_a_timeout(self):  # added in the Phase 3 review
        run = ready_run("o9")
        self.assertNotIn("--resume", orchestrate.auto_commands("activity", run, "partial")[0])
        write_json(run.dir / "activity" / "state.json", {"activated_by_us": True})
        self.assertIn("--resume", orchestrate.auto_commands("activity", run, "partial")[0])

    def test_projection_marks_done_auto_and_stops(self):
        run = ready_run("o1")
        recs = orchestrate.projection(run)
        by = {r["stage"]: r for r in recs}
        self.assertEqual(by["brief"]["action"], "done")
        self.assertTrue(by["accounts"]["action"].startswith("AUTO"))
        self.assertTrue(by["qualify"]["action"].startswith("STOP for Claude"))
        self.assertTrue(by["launch"]["post_ready"])
        self.assertIn("accounts", orchestrate.render(recs))

    def test_drive_stops_at_the_first_decision(self):
        run = ready_run("o2")
        ran = []
        # nothing pulled yet: the first incomplete stage is the accounts PILOT gate (auto: pull the pilot), never the full pull
        res = orchestrate.drive(run, execute=False, log=lambda *_: None)
        self.assertEqual(res["state"], "dry")
        self.assertEqual(res["stage"], "pilot_accounts")
        res = orchestrate.drive(run, execute=True, runner=lambda argv: (ran.append(argv) or (0, "ok")), log=lambda *_: None)
        self.assertEqual(res["state"], "stalled")  # the fake runner changed nothing, so the driver does not loop
        self.assertTrue(any("pilot_run.py" in " ".join(a) for a in ran))
        self.assertFalse(any("accounts_pull.py" in " ".join(a) for a in ran))

    def test_drive_stops_for_user_and_claude(self):
        run = ready_run("o3")
        # brief missing -> stop for the user
        (run.dir / "brief.json").unlink()
        res = orchestrate.drive(run, execute=True, runner=lambda a: (0, ""), log=lambda *_: None)
        self.assertEqual((res["state"], res["stage"], res["needs"]), ("stopped", "brief", "user"))

    def test_drive_failure_is_reported(self):
        run = ready_run("o4")
        res = orchestrate.drive(run, execute=True, runner=lambda a: (3, "boom\nlast line"), log=lambda *_: None)
        self.assertEqual(res["state"], "failed")
        self.assertIn("last line", res["instruction"])

    def test_launch_gate_requires_user_approval(self):
        # a run whose stages before launch are all complete
        import types
        run = launch_ready("o5")
        fake = {s: {"status": "done", "detail": ""} for s in stages.names()}
        fake["launch"] = {"status": "pending", "detail": "not planned yet"}
        orig = type(run).stage_status
        type(run).stage_status = lambda self: fake
        try:
            ran = []

            def runner(a):
                ran.append(a)
                lmod.Launch(run).make_plan("2026-10-21")  # what launch_run.py plan does
                fake["launch"] = {"status": "partial", "detail": "plan written, waiting for the user's approval"}
                return 0, "planned"
            res = orchestrate.drive(run, execute=True, runner=runner, log=lambda *_: None)
            self.assertEqual(res["stage"], "launch")
            self.assertTrue(any("launch_run.py" in " ".join(a) and "plan" in a for a in ran))
            self.assertFalse(any("execute" in a for a in ran))  # never executes without an approval
            self.assertEqual(res["needs"], "user")
        finally:
            type(run).stage_status = orig

    def test_cost_estimates_never_gate(self):
        run = ready_run("o6")
        self.assertIn("Apollo credits", orchestrate.estimate(run, "accounts"))
        self.assertEqual(orchestrate.estimate(run, "unknown-stage"), "")

    def test_phones_in_enrich_flag_is_off_and_noted(self):
        self.assertIs(config.get("phones.phones_in_enrich"), False)
        self.assertIn("TODO", config.get("phones._phones_in_enrich_todo"))


class TestNoEmDashesInPhase3Files(unittest.TestCase):
    def test_files_have_no_em_dashes(self):
        root = str(config.IDEA_LAUNCH_DIR)
        skip = {"copy-library", "workflows", "vendor", "__pycache__", "fixtures"}
        bad = []
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in skip]
            for f in files:
                if f.endswith((".py", ".md", ".json")) and f not in ("REVIEW-PHASE1.md", "REVIEW-PHASE2.md", "config.local.json"):
                    t = open(os.path.join(d, f), encoding="utf-8").read()
                    if "\u2014" in t:
                        bad.append(f)
        self.assertEqual(bad, [])
