// ===== lib_v2: incremental-state helpers for the v2 checker =====
// build_workflow_v2.py appends this AFTER lib.js in every v2 Code node. It does
// not touch the verdict logic: lib.js evaluate() runs unchanged. The only
// thing it swaps is where evaluate() reads its inputs from. lib.js reads
// node outputs through safe(name); here safe() is redefined (the later
// function declaration wins) so that, inside a batch, it serves a mix of
//   - this run's scrape results (real actor items), and
//   - results of stages finished in an EARLIER run, rebuilt from the compact
//     sheet columns (profile fields and dates).
// That is what lets a run skip stages already done and still reach the same
// verdict.

function rawSafe(name) {
  try { return $(name).all().map(i => i.json); } catch (e) { return []; }
}

let V2_SOURCES = null;
function safe(name) {
  return V2_SOURCES ? (V2_SOURCES[name] || []) : rawSafe(name);
}

// Worker node names per stage. `lib` holds the node names lib.js expects.
const V2_STAGES = {
  profile: { build: 'Build Profiles', run: 'Run Profiles', items: 'Get Profiles',
    lib: { build: 'Build Profile Batches', scrape: 'Scrape Profiles' } },
  posts: { build: 'Build Posts', run: 'Run Posts', items: 'Get Posts',
    lib: { build: 'Build Posts Batches', scrape: 'Scrape Posts' } },
  comments: { build: 'Build Comments', run: 'Run Comments', items: 'Get Comments',
    lib: { build: 'Build Comments Batches', scrape: 'Scrape Comments' } },
  reactions: { build: 'Build Reactions', run: 'Run Reactions', items: 'Get Reactions',
    lib: { build: 'Build Reactions Batches', scrape: 'Scrape Reactions' } },
};

function cfgV2() {
  const b = rawSafe('Batch In');
  return (b[0] && b[0]._cfg) || {};
}

function batchRows() {
  return rawSafe('Batch In').map(r => {
    const o = {};
    for (const [k, v] of Object.entries(r)) if (k !== '_cfg' && k !== 'row_number') o[k] = v;
    return o;
  });
}

function truthy(v) { return v === true || /^(true|yes|1)$/i.test(String(v ?? '').trim()); }
function num(v) { const n = Number(String(v ?? '').replace(/,/g, '')); return isFinite(n) ? n : 0; }

// Sheet dates come back as 'YYYY-MM-DD' strings (written RAW) or, if a
// human retyped a cell, as a Sheets serial number.
function dayMs(v) {
  if (v === '' || v === null || v === undefined) return null;
  if (typeof v === 'number') return v < 100000 ? Date.UTC(1899, 11, 30) + v * DAY : v;
  const t = Date.parse(String(v));
  return isNaN(t) ? null : t;
}
function dayIso(v) { return iso(dayMs(v)); }

function stagesOf(row) {
  return new Set(String(row.stages_run || '').split(',').map(s => s.trim()).filter(Boolean));
}

// Rebuild a profile-scraper-shaped object from stored columns so lib.js
// profileFields() yields the same values (dates at day precision).
function syntheticProfile(row) {
  const media = (has, d) => {
    if (!truthy(has)) return '';
    const ms = dayMs(d);
    return ms ? 'https://media.licdn.com/stored/0/' + ms + '/x' : 'https://media.licdn.com/stored';
  };
  const jobs = num(row.jobs_count);
  const cur = Math.min(num(row.current_jobs_count), jobs);
  const ls = dayMs(row.latest_job_start);
  const exp = [];
  for (let i = 0; i < jobs; i++) {
    const e = i < cur ? {} : { endDate: { year: 2000, month: 1 } };
    if (i === 0) {
      e.position = row.current_title || '';
      e.companyName = row.current_company || '';
      e.companyLinkedinUrl = row.current_company_linkedin_url || '';
      if (cur > 0 && ls) { const d = new Date(ls); e.startDate = { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1 }; }
    }
    exp.push(e);
  }
  return {
    linkedinUrl: row.linkedin_url,
    firstName: row.first_name || '',
    lastName: row.last_name || '',
    headline: String(row.headline || '') || (truthy(row.has_headline) ? 'stored' : ''),
    about: truthy(row.has_about) ? 'stored' : '',
    location: { linkedinText: row.location || '', parsed: { country: row.country || '' } },
    connectionsCount: num(row.connections),
    followerCount: num(row.followers),
    profilePicture: media(row.has_photo, row.photo_changed_at),
    coverPicture: media(row.has_cover, row.cover_changed_at),
    experience: exp,
    memorialized: false,
  };
}

// What happened to a stage in THIS run of the batch.
function stageRun(stage) {
  const n = V2_STAGES[stage];
  const build = rawSafe(n.build)[0];
  if (!build || build.skip || !build.body) return { ran: false, ok: true, attempted: new Set() };
  const attempted = new Set();
  try {
    const body = JSON.parse(build.body);
    for (const u of (body.queries || body.urls || body.profiles || [])) attempted.add(key(u));
  } catch (e) {}
  const run = rawSafe(n.run)[0] || {};
  const runOk = !run.error && (!run.status || run.status === 'SUCCEEDED');
  const ok = runOk && !stageFailed(n.items);
  return { ran: true, ok, attempted, run };
}

// Inputs for lib.js evaluate(): stored results of earlier runs + this run.
function v2Sources() {
  V2_SOURCES = null;
  const rows = batchRows();
  const st = {};
  for (const s of Object.keys(V2_STAGES)) st[s] = stageRun(s);
  const doneStored = s => rows.filter(r => stagesOf(r).has(s));
  const doneKeys = s => {
    const d = new Set(doneStored(s).map(r => key(r.linkedin_url)));
    if (st[s].ran && st[s].ok) for (const k of st[s].attempted) d.add(k);
    return d;
  };
  const keyBody = keys => [{ body: JSON.stringify({ urls: [...keys] }) }];
  const failItem = s => (st[s].ran && !st[s].ok ? [{ error: s + ' run failed' }] : []);

  const src = { 'Read Leads': rows };
  src['Scrape Profiles'] = rawSafe(V2_STAGES.profile.items)
    .concat(doneStored('profile').map(syntheticProfile));
  src['Build Profile Batches'] = st.profile.ran ? keyBody(st.profile.attempted) : [];

  src['Build Posts Batches'] = keyBody(doneKeys('posts'));
  src['Scrape Posts'] = rawSafe(V2_STAGES.posts.items)
    .concat(doneStored('posts').filter(r => r.last_post_at)
      .map(r => ({ inputUrl: r.linkedin_url, postedAtISO: dayIso(r.last_post_at), url: r.last_post_url || '' })))
    .concat(failItem('posts'));

  src['Build Comments Batches'] = keyBody(doneKeys('comments'));
  src['Scrape Comments'] = rawSafe(V2_STAGES.comments.items)
    .concat(doneStored('comments').filter(r => r.last_comment_at)
      .map(r => ({ query: { profile: r.linkedin_url }, createdAt: dayIso(r.last_comment_at) })))
    .concat(failItem('comments'));

  src['Build Reactions Batches'] = keyBody(doneKeys('reactions'));
  src['Scrape Reactions'] = rawSafe(V2_STAGES.reactions.items)
    .concat(doneStored('reactions').filter(r => r.last_reaction_at)
      .map(r => ({ query: { profile: r.linkedin_url }, createdAt: dayIso(r.last_reaction_at) })))
    .concat(failItem('reactions'));

  return { src, st, rows, doneKeys };
}

// Run lib.js evaluate(stage) against the v2 sources.
function evaluateV2(stage) {
  const ctx = v2Sources();
  V2_SOURCES = ctx.src;
  try { return { recs: evaluate(stage), ctx }; } finally { V2_SOURCES = null; }
}

// Keep only the compact sheet columns.
function project(rec, extra) {
  const cfg = cfgV2();
  const out = {};
  for (const c of cfg.COLUMNS || []) if (rec[c] !== undefined) out[c] = rec[c];
  return Object.assign(out, extra || {});
}

// Checkpoint rows for one stage. After the profile stage an A/B Active is
// held back (status blank) until its posts stage has run, as in v1.
function checkpoint(stage, libStage) {
  const cfg = cfgV2();
  const { recs, ctx } = evaluateV2(libStage);
  const postsDone = ctx.doneKeys('posts');
  const out = recs.map(r => {
    const row = project(r, { batch_ref: cfg.batch_ref || '' });
    if (stage === 'profile' && r.activity_status === 'Active' && !postsDone.has(key(r.linkedin_url))) {
      row.activity_status = ''; row.active_via = ''; row.activity_reason = '';
    }
    return { json: row };
  });
  if (!out.length) {
    const first = ctx.rows[0];
    return first ? [{ json: { linkedin_url: first.linkedin_url } }] : [];
  }
  return out;
}

// Body for the next stage, or {skip:true}.
function stageBody(urls, bodyFn) {
  if (!urls.length) return [{ json: { skip: true } }];
  return [{ json: { skip: false, count: urls.length, body: JSON.stringify(bodyFn(urls.map(enc))) } }];
}

function runLog(stage) {
  const cfg = cfgV2();
  const n = V2_STAGES[stage];
  const run = rawSafe(n.run)[0] || {};
  const build = rawSafe(n.build)[0] || {};
  return [{ json: {
    logged_at: new Date().toISOString(),
    batch_ref: cfg.batch_ref || '',
    stage,
    actor: run.actId || '',
    apify_run_id: run.id || '',
    dataset_id: run.defaultDatasetId || '',
    status: run.status || (run.error ? 'ERROR: ' + String(run.error.message || run.error).slice(0, 200) : ''),
    lead_count: build.count || 0,
    usage_usd: run.usageTotalUsd ?? '',
  } }];
}
// ===== end lib_v2 =====
