// ===== Shared activity-checker library =====
// build_workflow.py prepends this file to every Code node, so the rules live in
// one place. Thresholds sit in CONFIG; retuning them needs no re-scrape.
const CONFIG = {
  SHELL_MIN_CONN: 50,
  FLOOR_CONN: 300,
  FLOOR_FOLLOWERS: 2000,
  FLOOR_SECTIONS: 3,
  B_CONN: 1000,
  B_JOBS: 3,
  A_DAYS: 60,
  B_DAYS: 183,
  C_DAYS: 30,
  MAX_ATTEMPTS: 3,
  PROFILE_BATCH: 100,
  POSTS_BATCH: 50,
  COMMENTS_BATCH: 40,
  REACTIONS_BATCH: 40,
};

const DAY = 86400000;
const NOW = Date.now();
const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };

// Slug-based key: lowercase, decoded, no query string or trailing slash.
function key(u) {
  let s = String(u || '').trim().split('?')[0].replace(/\/+$/, '');
  try { s = decodeURIComponent(s); } catch (e) {}
  s = s.toLowerCase();
  const m = s.match(/linkedin\.com\/in\/([^\/]+)/);
  return m ? m[1] : s;
}

// Percent-encode the vanity slug: unencoded non-ASCII URLs silently vanish
// from actor output (102 of Turchi's 699 leads were lost this way).
function enc(u) {
  const s = String(u || '').trim();
  const i = s.indexOf('/in/');
  if (i < 0) return s;
  let slug = s.slice(i + 4).split('?')[0].replace(/\/+$/, '');
  try { slug = decodeURIComponent(slug); } catch (e) {}
  return 'https://www.linkedin.com/in/' + encodeURIComponent(slug) + '/';
}

// $('Node').all() throws when the node did not run in this execution.
function safe(name) {
  try { return $(name).all().map(i => i.json); } catch (e) { return []; }
}

// A failed Apify run (onError: continue) yields an item carrying `error`.
// Per-profile notices such as "No posts found" carry the input URL and are a
// normal empty result, not a failure.
function stageFailed(name) {
  return safe(name).some(i => i && i.error && !i.url && !i.createdAt && !i.id
    && !i.inputUrl && !i.query && !i.profile);
}

function batchKeys(name) {
  const out = new Set();
  for (const b of safe(name)) {
    if (!b || b.skip || !b.body) continue;
    try {
      const body = JSON.parse(b.body);
      for (const u of (body.queries || body.urls || body.profiles || [])) out.add(key(u));
    } catch (e) {}
  }
  return out;
}

function chunk(arr, n) {
  const out = [];
  for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n));
  return out;
}

// LinkedIn embeds a 13-digit epoch (ms) in media URLs: the upload time.
function mediaTs(url) {
  if (!url) return null;
  const s = String(url);
  const m = s.match(/\/(\d{13})[\/?]/) || s.match(/\/0\/(\d{13})/);
  return m ? Number(m[1]) : null;
}

function parseStart(sd) {
  if (!sd || typeof sd !== 'object' || !sd.year) return null;
  const year = parseInt(String(sd.year).slice(0, 4), 10);
  if (!year) return null;
  let month = 1;
  const raw = sd.month;
  if (raw !== null && raw !== undefined && raw !== '') {
    month = Number(raw) || MONTHS[String(raw).slice(0, 3).toLowerCase()] || 1;
  }
  return Date.UTC(year, Math.min(Math.max(month, 1), 12) - 1, 1);
}

function toMs(v) {
  if (!v) return null;
  if (typeof v === 'number') return v > 1e12 ? v : v * 1000;
  if (typeof v === 'object') return toMs(v.date || v.timestamp || v.iso);
  const t = Date.parse(String(v));
  return isNaN(t) ? null : t;
}

function iso(ms) { return ms ? new Date(ms).toISOString().slice(0, 10) : ''; }
function nice(ms) {
  if (!ms) return '';
  const d = new Date(ms);
  return d.getUTCDate() + ' ' + ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getUTCMonth()] + ' ' + d.getUTCFullYear();
}
function within(ms, days) { return !!ms && NOW - ms <= days * DAY; }
function maxMs(list) { const v = list.filter(Boolean); return v.length ? Math.max(...v) : null; }

function isCurrent(e) {
  const ed = e.endDate ?? e.end ?? null;
  if (!ed) return true;
  if (typeof ed === 'object') return !(ed.year || ed.month);
  return /present/i.test(String(ed));
}

function pic(v) {
  if (!v) return '';
  if (typeof v === 'object') return v.url || '';
  return String(v);
}

// Map one profile-scraper item to sheet columns.
function profileFields(p) {
  const conns = Number(p.connectionsCount ?? p.connections ?? 0) || 0;
  const folls = Number(p.followerCount ?? p.followers ?? 0) || 0;
  const photo = pic(p.profilePicture) || pic(p.photo);
  const cover = pic(p.coverPicture);
  const exp = Array.isArray(p.experience) ? p.experience : [];
  const cur = exp.filter(isCurrent);
  const about = String(p.about || p.summary || '').trim();
  const headline = String(p.headline || '').trim();
  const loc = p.location || {};
  const sections = {
    photo: !!photo, cover: !!cover, about: about.length > 0,
    headline: headline.length > 0, jobs2: exp.length >= 2,
  };
  const latestJobStart = maxMs(cur.map(e => parseStart(e.startDate ?? e.start)));
  const first = cur[0] || {};
  return {
    first_name: p.firstName || '',
    last_name: p.lastName || '',
    headline,
    about: about.slice(0, 2000),
    location: typeof loc === 'string' ? loc : (loc.linkedinText || (loc.parsed && loc.parsed.text) || ''),
    country: typeof loc === 'object' ? ((loc.parsed && (loc.parsed.country || loc.parsed.countryFull)) || loc.countryCode || '') : '',
    current_title: first.position || first.title || '',
    current_company: first.companyName || first.company || '',
    current_company_linkedin_url: first.companyLinkedinUrl || first.companyUrl || '',
    connections: conns,
    followers: folls,
    has_photo: sections.photo,
    has_cover: sections.cover,
    has_about: sections.about,
    has_headline: sections.headline,
    jobs_count: exp.length,
    current_jobs_count: cur.length,
    sections_filled: Object.values(sections).filter(Boolean).length,
    experience_json: JSON.stringify(exp.slice(0, 8).map(e => ({
      title: e.position || e.title || '',
      company: e.companyName || e.company || '',
      company_url: e.companyLinkedinUrl || e.companyUrl || '',
      start: iso(parseStart(e.startDate ?? e.start)),
      current: isCurrent(e),
    }))),
    photo_changed_at: iso(mediaTs(photo)),
    cover_changed_at: iso(mediaTs(cover)),
    latest_job_start: iso(latestJobStart),
    _memorialized: !!p.memorialized,
    _photo_ms: mediaTs(photo),
    _cover_ms: mediaTs(cover),
    _job_ms: latestJobStart,
  };
}

// Index scraper output by profile key.
function indexProfiles() {
  const out = {};
  for (const p of safe('Scrape Profiles')) {
    if (!p || p.error) continue;
    const k = key(p.linkedinUrl || p.publicIdentifier || (p.originalQuery && p.originalQuery.query) || p.url || '');
    if (k) out[k] = p;
    const q = p.originalQuery && p.originalQuery.query;
    if (q) out[key(q)] = p;
  }
  return out;
}

function indexDated(nodeName, keyFn, dateFn, extraFn) {
  const out = {};
  for (const it of safe(nodeName)) {
    if (!it || it.error) continue;
    const k = keyFn(it);
    const ms = dateFn(it);
    if (!k || !ms) continue;
    if (!out[k] || ms > out[k].ms) out[k] = { ms, ...(extraFn ? extraFn(it) : {}) };
  }
  return out;
}

function pendingRows() {
  const seen = new Set();
  return safe('Read Leads').filter(r => {
    const u = String(r.linkedin_url || '');
    if (!u.includes('linkedin.com/in/')) return false;
    if (String(r.activity_status || '').trim()) return false;
    if ((Number(r.scrape_attempts) || 0) >= CONFIG.MAX_ATTEMPTS) return false;
    const k = key(u);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

// Core verdict. stage: 1 after posts, 2 after comments, 3 after reactions (final).
function evaluate(stage) {
  const profiles = indexProfiles();
  const profileKeys = batchKeys('Build Profile Batches');
  const postKeys = batchKeys('Build Posts Batches');
  const commentKeys = stage >= 2 ? batchKeys('Build Comments Batches') : new Set();
  const reactionKeys = stage >= 3 ? batchKeys('Build Reactions Batches') : new Set();

  const posts = indexDated('Scrape Posts',
    it => key(it.inputUrl || (it.query && it.query.url) || ''),
    it => toMs(it.postedAtISO || it.publishedAt || (it.postedAt && (it.postedAt.date || it.postedAt)) || it.createdAt),
    it => ({ url: it.url || '', text: String(it.text || it.commentary || '').slice(0, 500) }));
  const comments = stage >= 2 ? indexDated('Scrape Comments',
    it => key((it.query && it.query.profile) || ''),
    it => toMs(it.createdAt),
    it => ({ url: it.linkedinUrl || '', text: String(it.commentary || '').slice(0, 500) })) : {};
  const reactions = stage >= 3 ? indexDated('Scrape Reactions',
    it => key((it.query && it.query.profile) || ''),
    it => toMs(it.createdAt),
    it => ({ url: (it.post && (it.post.linkedinUrl || it.post.url)) || '' })) : {};

  const postsFailed = stageFailed('Scrape Posts');
  const commentsFailed = stage >= 2 && stageFailed('Scrape Comments');
  const reactionsFailed = stage >= 3 && stageFailed('Scrape Reactions');

  const out = [];
  for (const row of pendingRows()) {
    const k = key(row.linkedin_url);
    const rec = { linkedin_url: row.linkedin_url };
    const attempts = Number(row.scrape_attempts) || 0;
    const p = profiles[k];

    if (!p) {
      Object.assign(rec, {
        activity_status: '', active_via: '', activity_reason: '',
        scrape_error: profileKeys.has(k) ? 'profile not returned by scraper' : 'profile not scraped',
        scrape_attempts: attempts + 1,
        activity_checked_at: iso(NOW),
        _decided: true,
      });
      out.push(rec);
      continue;
    }

    const f = profileFields(p);
    for (const [kk, v] of Object.entries(f)) if (!kk.startsWith('_')) rec[kk] = v;
    rec.scrape_error = '';
    rec.scrape_attempts = attempts + 1;
    rec.activity_checked_at = iso(NOW);

    const po = posts[k], co = comments[k], re = reactions[k];
    rec.last_post_at = po ? iso(po.ms) : '';
    rec.last_post_url = po ? po.url : '';
    rec.last_post_text = po ? po.text : '';
    rec.last_comment_at = co ? iso(co.ms) : '';
    rec.last_comment_text = co ? co.text : '';
    rec.last_reaction_at = re ? iso(re.ms) : '';
    rec.stages_run = ['profile',
      postKeys.has(k) ? 'posts' : null,
      commentKeys.has(k) ? 'comments' : null,
      reactionKeys.has(k) ? 'reactions' : null].filter(Boolean).join(',');

    // Shell
    const shell = [];
    if (f._memorialized) shell.push('memorialized account');
    if (f.connections < CONFIG.SHELL_MIN_CONN) shell.push(f.connections + ' connections');
    if (!f.has_photo && !f.has_headline) shell.push('no photo and no headline');
    if (f.jobs_count === 0) shell.push('no experience');
    if (shell.length) {
      Object.assign(rec, { activity_status: 'Shell', active_via: '', activity_reason: 'Shell: ' + shell.join(', '), _decided: true });
      out.push(rec);
      continue;
    }

    // Quality floor
    const floorFails = [];
    if (!(f.connections >= CONFIG.FLOOR_CONN || f.followers >= CONFIG.FLOOR_FOLLOWERS))
      floorFails.push(f.connections + ' connections, ' + f.followers + ' followers');
    if (f.sections_filled < CONFIG.FLOOR_SECTIONS) floorFails.push(f.sections_filled + '/5 sections');
    if (f.current_jobs_count < 1) floorFails.push('no current job');
    if (floorFails.length) {
      Object.assign(rec, { activity_status: 'Inactive', active_via: '', activity_reason: 'Floor failed: ' + floorFails.join(', '), _decided: true });
      out.push(rec);
      continue;
    }

    // Paths
    const changes = [[f._job_ms, 'job change'], [f._photo_ms, 'photo change'], [f._cover_ms, 'cover change']].filter(x => x[0]);
    const lastChange = changes.length ? changes.reduce((a, b) => (b[0] > a[0] ? b : a)) : null;
    const via = [], why = [];
    const recentA = changes.filter(c => within(c[0], CONFIG.A_DAYS));
    if (recentA.length) { via.push('A'); why.push(...recentA.map(c => c[1] + ' ' + nice(c[0]))); }
    if (f.sections_filled === 5 && f.jobs_count >= CONFIG.B_JOBS && f.connections >= CONFIG.B_CONN
        && lastChange && within(lastChange[0], CONFIG.B_DAYS)) {
      via.push('B');
      why.push('strong profile (' + f.connections + ' connections, ' + f.jobs_count + ' jobs), ' + lastChange[1] + ' ' + nice(lastChange[0]));
    }
    const acts = [[po && po.ms, 'posted'], [co && co.ms, 'commented'], [re && re.ms, 'reacted']].filter(x => within(x[0], CONFIG.C_DAYS));
    if (acts.length) { via.push('C'); why.push(...acts.map(a => a[1] + ' ' + nice(a[0]))); }

    if (via.length) {
      Object.assign(rec, { activity_status: 'Active', active_via: via.join(','), activity_reason: why.join('; '), _decided: true });
    } else if (stage >= 3) {
      const failed = [postsFailed && 'posts', commentsFailed && 'comments', reactionsFailed && 'reactions'].filter(Boolean);
      if (failed.length) {
        Object.assign(rec, { activity_status: '', active_via: '', activity_reason: '', scrape_error: failed.join(', ') + ' scrape failed, will retry', _decided: true });
      } else {
        Object.assign(rec, {
          activity_status: 'Inactive', active_via: '',
          activity_reason: 'No post, comment or reaction in ' + CONFIG.C_DAYS + ' days' +
            (lastChange ? '; last change ' + lastChange[1] + ' ' + nice(lastChange[0]) : '; no dated profile change'),
          _decided: true,
        });
      }
    } else {
      Object.assign(rec, { activity_status: '', active_via: '', activity_reason: '', _decided: false });
    }
    out.push(rec);
  }
  return out;
}

// Undecided, floor-passing leads still in play after a stage.
function undecidedUrls(verdictNode) {
  return safe(verdictNode).filter(r => r && r._decided === false).map(r => r.linkedin_url);
}

function batches(urls, size, bodyFn) {
  if (!urls.length) return [{ json: { skip: true } }];
  return chunk(urls, size).map(c => ({ json: { skip: false, count: c.length, body: JSON.stringify(bodyFn(c.map(enc))) } }));
}
// ===== end library =====
