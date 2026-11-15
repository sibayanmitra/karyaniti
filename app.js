/* ─────────────────────────────────────────────────────────
   Karyaniti — front-end controller
   - Live clock + corpus health
   - Marquee ticker of recent searches
   - SSE pipeline against /api/research with offline demo fallback
   - Result rendering
   ───────────────────────────────────────────────────────── */

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* ───────── Live clock ───────── */
function tickClock(){
  const d = new Date();
  const opts = { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false };
  $('clock').textContent = 'IST ' + d.toLocaleTimeString('en-IN', opts);
}
tickClock(); setInterval(tickClock, 1000 * 30);

/* ───────── Health check ───────── */
async function checkHealth(){
  try{
    const r = await fetch('/api/health');
    const d = await r.json();
    const ok = d.ik_token === 'set' && d.or_key === 'set';
    $('hDot').className = 'dot ' + (ok ? 'ok' : 'err');
    $('hStat').textContent = ok ? 'corpus live' : 'keys missing';
    appState.live = ok;
  }catch{
    $('hDot').className = 'dot';
    $('hStat').textContent = 'demo mode';
    appState.live = false;
  }
}

/* ───────── Ticker ───────── */
const tickerSeed = [
  '“Article 226 alternative remedy”',
  '“Section 65B electronic evidence”',
  '“anticipatory bail conditions”',
  '“natural justice exception urgency”',
  '“private body public function writ”',
  '“partnership firm death of partner”',
  '“promissory estoppel against state”',
  '“basic structure doctrine”',
  '“doctrine of pith and substance”',
  '“PIL locus standi”',
  '“Article 14 reasonable classification”',
  '“Section 482 CrPC inherent power”',
];
function buildTicker(){
  const t = $('tickerTrack');
  const make = () => tickerSeed.map(q =>
    `<span><span class="glyph">§</span>${esc(q)}</span>`
  ).join('');
  // duplicate so the marquee can loop seamlessly
  t.innerHTML = make() + make();
}
buildTicker();

/* ───────── App state ───────── */
const appState = {
  live: false,
  busy: false,
  startTs: 0,
  elapsedTimer: 0,
  trace: [],
  data: { holdings: [], note: '', stats: {}, premise_warn: null },
};

function setState(state){
  $('statePill').dataset.state = state;
  $('statePill').textContent = state;
}

function startElapsed(){
  appState.startTs = performance.now();
  clearInterval(appState.elapsedTimer);
  appState.elapsedTimer = setInterval(() => {
    const s = (performance.now() - appState.startTs) / 1000;
    $('elapsed').textContent = s.toFixed(1) + 's';
  }, 100);
}
function stopElapsed(){
  clearInterval(appState.elapsedTimer);
  const s = (performance.now() - appState.startTs) / 1000;
  $('elapsed').textContent = s.toFixed(1) + 's';
}

/* ───────── Trace ───────── */
let traceFresh = true;
function tlog(msg, cls = ''){
  const tr = $('trace');
  if (traceFresh){ tr.innerHTML = ''; traceFresh = false; }
  const el = document.createElement('div');
  el.className = 't-line ' + cls;
  el.textContent = msg;
  tr.appendChild(el);
  tr.scrollTop = tr.scrollHeight;
  appState.trace.push({msg, cls});
  $('traceCount').textContent = appState.trace.length + ' events';
}
function clearTrace(){
  appState.trace = [];
  $('trace').innerHTML = '<div class="t-line t-dim">Waiting for query…</div>';
  $('traceCount').textContent = '0 events';
  traceFresh = true;
}

/* ───────── Examples → query (legacy — historyList replaces this) ───────── */
const _exList = $('exampleList');
if (_exList) {
  _exList.addEventListener('click', e => {
    const b = e.target.closest('button[data-q]');
    if (!b) return;
    qEl.value = b.dataset.q;
    qEl.focus();
    run();
  });
}

/* ───────── Textarea auto-size ───────── */
const qEl = $('q');
function autoSizeTextarea(){
  qEl.style.height = 'auto';
  qEl.style.height = Math.min(qEl.scrollHeight, 180) + 'px';
}
qEl.addEventListener('input', autoSizeTextarea);
qEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); }
  if (e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); run(); }
});

/* ───────── Run ───────── */
$('run').addEventListener('click', run);

async function run(){
  const q = qEl.value.trim();
  if (!q){ qEl.focus(); return; }
  if (appState.busy) return;

  appState.busy = true;
  appState.lastQuery = q;
  appState.data = { holdings: [], note: '', stats: {}, premise_warn: null };
  clearTrace();
  $('results').innerHTML = '';
  $('run').classList.add('busy');
  $('run').disabled = true;
  setState('running');
  startElapsed();

  // Live SSE only — no demo fallback. If live fails, show the error.
  if (appState.live){
    try{
      await runLive(q);
    } catch(err){
      tlog('pipeline error: ' + err.message, 't-err');
      tlog('No results. The live pipeline failed mid-stream. Please retry.', 't-err');
      appState.data.note = 'Pipeline error: ' + err.message + '. No fabricated data is being shown. Please retry the query.';
      renderResults();
    }
  } else {
    tlog('Local server not running. Start it with: python main.py', 't-err');
    appState.data.note = 'Server not running at localhost:8765. Start the backend before querying.';
    renderResults();
  }

  appState.busy = false;
  $('run').classList.remove('busy');
  $('run').disabled = false;
  stopElapsed();
}

/* ───────── Live SSE ───────── */
async function runLive(q){
  const body = {
    query: q,
    doctypes: $('scope').value,
    mode: $('mode').value,
  };
  const resp = await fetch('/api/research', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(body)
});
  if (!resp.ok) throw new Error('HTTP ' + resp.status);

  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  while (true){
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream:true });
    const lines = buf.split('\n');
    buf = lines.pop() || '';
    for (const line of lines){
      if (!line.startsWith('data: ')) continue;
      try{ handleEvent(JSON.parse(line.slice(6).trim())); }catch{}
    }
  }
}

function handleEvent(e){
  const t = e.type;
  if (t === 'complete'){
    appState.data.note = e.note || '';
    appState.data.holdings = e.holdings || [];
    appState.data.stats = e.stats || {};
    appState.data.premise_warn = e.premise_warn || null;
    render();
    setState('done');
    tlog(e.message || 'done', 't-ok');
    saveHistory(appState.lastQuery || qEl.value.trim(), appState.data);
    return;
  }
  if (t === 'error'){ tlog(e.message, 't-err'); setState('error'); return; }
  if (t === 'premise_warn'){ tlog(e.message, 't-warn'); if (e.detail) tlog('  ' + e.detail, 't-dim'); return; }
  if (t === 'judge_verdict'){ tlog(e.message || '', e.passed ? 't-ok' : 't-err'); return; }
  if (t === 'warning'){ tlog(e.message, 't-warn'); return; }
  if (t === 'council_start' || t === 'judging' || t === 'synthesising'){ tlog(e.message, 't-judge'); return; }
  if (t === 'searching' || t === 'fetching' || t === 'thinking'){ tlog(e.message, 't-step'); return; }
  if (t === 'found' || t === 'extracted' || t === 'l1_done' || t === 'adversary_done' || t === 'skeptic_done' || t === 'outsider_done' || t === 'premise_ok'){ tlog(e.message, 't-ok'); return; }
  if (e.message) tlog(e.message);
}

/* ───────── Offline demo (so the design is alive without a server) ───────── */
const DEMO_BANK = [
  // (mode, holdings, note)
];

const demoCases = [
  {
    name: 'Anvar P.V. v. P.K. Basheer',
    citation: '(2014) 10 SCC 473',
    court: 'Supreme Court of India',
    para: 22,
    is_ratio: true,
    prop: 'An electronic record by way of secondary evidence shall not be admitted in evidence unless the requirements under Section 65B of the Evidence Act are satisfied.',
    verbatim: 'Any documentary evidence by way of an electronic record under the Evidence Act, in view of Sections 59 and 65A, can be proved only in accordance with the procedure prescribed under Section 65B.',
    para_text: 'Any documentary evidence by way of an electronic record under the Evidence Act, in view of Sections 59 and 65A, can be proved only in accordance with the procedure prescribed under Section 65B. Section 65B deals with the admissibility of the electronic record. The purpose of these provisions is to sanctify secondary evidence in electronic form, generated by a computer.',
    ik: 'https://indiankanoon.org/doc/187283766/',
    audit: { L1:true, L3:true, L4ok:true, adv:'SUPPORTED', sf:false, conf:0.94 },
    pass: true,
    judge_reason: 'Verbatim anchor present; rule articulated unambiguously in para 22.'
  },
  {
    name: 'Arjun Panditrao Khotkar v. Kailash Kushanrao Gorantyal',
    citation: '(2020) 7 SCC 1',
    court: 'Supreme Court of India',
    para: 61,
    is_ratio: true,
    prop: 'A certificate under Section 65B(4) is a condition precedent to the admissibility of evidence by way of electronic record. Anvar P.V. is the law of the land, and Shafhi Mohammad stands overruled.',
    verbatim: 'The certificate required under Section 65B(4) is a condition precedent to the admissibility of evidence by way of electronic record.',
    para_text: 'The certificate required under Section 65B(4) is a condition precedent to the admissibility of evidence by way of electronic record, as correctly held in Anvar P.V. and incorrectly “clarified” in Shafhi Mohammad. Oral evidence in the place of such certificate cannot possibly suffice as Section 65B(4) is a mandatory requirement of the law.',
    ik: 'https://indiankanoon.org/doc/55307762/',
    audit: { L1:true, L3:true, L4ok:true, adv:'SUPPORTED', sf:false, conf:0.91 },
    pass: true,
    judge_reason: 'Three-judge bench; explicit overruling of contrary authority. Verbatim grounding clean.'
  },
  {
    name: 'Tomaso Bruno v. State of U.P.',
    citation: '(2015) 7 SCC 178',
    court: 'Supreme Court of India',
    para: 24,
    is_ratio: false,
    prop: 'Electronic records can be admitted as primary evidence even without a Section 65B certificate where the original device is produced.',
    verbatim: '',
    para_text: 'In a given case the question may arise whether the electronic record is admissible as primary evidence under Section 62 of the Evidence Act. We do not, however, propose to express any final view in this matter.',
    ik: 'https://indiankanoon.org/doc/57927831/',
    audit: { L1:false, L3:false, L4ok:false, adv:'NOT_SUPPORTED', sf:true, conf:0.18 },
    pass: false,
    judge_reason: 'No verbatim anchor; per incuriam observation later disapproved in Arjun Panditrao Khotkar.'
  },
];

const demoNote = `1. Restated question
   Whether a certificate under Section 65B(4) of the Evidence Act, 1872 is a condition precedent for the admission of electronic records as secondary evidence in Indian courts.

2. Authorities
   • Anvar P.V. v. P.K. Basheer, (2014) 10 SCC 473 — Para 22. The court held that documentary evidence in electronic form can be proved only by adherence to the Section 65B procedure; secondary electronic evidence without the certificate is inadmissible.
   • Arjun Panditrao Khotkar v. Kailash Kushanrao Gorantyal, (2020) 7 SCC 1 — Para 61. A three-judge bench reaffirms Anvar P.V., declares Shafhi Mohammad to be incorrect law, and holds the Section 65B(4) certificate to be a mandatory condition precedent.

3. Treatment status
   The treatment graph above is unverified by Karyaniti. Counsel must independently verify the citator entry on SCC Online or Manupatra before relying on these holdings in court.

4. Summary
   The position of law, post Arjun Panditrao Khotkar, is settled: a Section 65B(4) certificate is mandatory and a condition precedent for admissibility of secondary electronic evidence. Tomaso Bruno's contrary observation does not survive the 2020 ruling.`;

async function runDemo(q){
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const beat = (msg, cls, ms=300) => { tlog(msg, cls); return wait(ms); };

  await beat('checking query for false premises…', 't-step', 350);
  await beat('no false premise detected', 't-ok', 280);
  await beat('searching Indian Kanoon corpus (' + $('scope').selectedOptions[0].text + ')…', 't-step', 600);
  await beat('found 4 candidate judgments', 't-ok', 250);

  for (const c of demoCases){
    await beat('fetching: ' + c.name + '…', 't-step', 480);
    await beat('extracted ' + (8 + Math.floor(Math.random()*6)) + ' paragraphs · ' + (2 + Math.floor(Math.random()*3)) + ' holding-type', 't-ok', 220);
    await beat('council: extracting holdings from ' + c.name.slice(0,32) + '…', 't-judge', 520);
    await beat('  L1 verbatim: ' + (c.audit.L1 ? 'verified' : 'NOT FOUND'), c.audit.L1 ? 't-ok' : 't-err', 240);
    await beat('  adversary verdict: ' + c.audit.adv, c.audit.adv==='SUPPORTED' ? 't-ok' : 't-err', 240);
    await beat('  judge: ' + (c.pass ? '✓ PASS' : '✗ FAIL') + ' — ' + c.prop.slice(0, 64) + '…',
               c.pass ? 't-ok' : 't-err', 320);
  }

  await beat('synthesising research note from ' + demoCases.filter(c=>c.pass).length + ' verified holdings…', 't-judge', 700);

  appState.data.note = demoNote;
  appState.data.holdings = demoCases.map(c => ({
    case_name: c.name, citation: c.citation, court: c.court,
    para_num: c.para, is_ratio: c.is_ratio,
    prop: c.prop, verbatim: c.verbatim, para_text: c.para_text,
    pass: c.pass, judge_conf: c.audit.conf, judge_reason: c.judge_reason,
    L1: c.audit.L1, L3: c.audit.L3, L4ok: c.audit.L4ok,
    adv_verdict: c.audit.adv, sf: c.audit.sf,
    ik_url: c.ik,
  }));
  appState.data.stats = {
    docs: demoCases.length,
    passed: demoCases.filter(c=>c.pass).length,
    total: demoCases.length,
    elapsed: ((performance.now() - appState.startTs)/1000).toFixed(1),
  };

  render();
  setState('done');
  tlog('done · ' + appState.data.stats.passed + '/' + appState.data.stats.total + ' passed · demo data', 't-ok');
}

/* ───────── Render ───────── */
function render(){
  const { note, holdings, stats, premise_warn } = appState.data;
  const passed = holdings.filter(h => h.pass);
  const failed = holdings.filter(h => !h.pass);

  let h = '';

  // stats strip
  h += `<div class="r-section">
    <div class="r-head"><span class="num">03 /</span> <span class="lbl">Result</span> <span class="count">${stats.passed||0} of ${stats.total||0} holdings cleared the council</span></div>
    <div class="stat-strip">
      <div><span class="stat-val">${stats.docs ?? '—'}</span><span class="stat-lbl">Cases retrieved</span></div>
      <div><span class="stat-val">${(stats.passed ?? 0)}/${(stats.total ?? 0)}</span><span class="stat-lbl">Holdings · pass / total</span></div>
      <div><span class="stat-val">${stats.elapsed ?? '—'}<span style="font-size:18px;color:var(--ink-3);margin-left:4px">s</span></span><span class="stat-lbl">Pipeline duration</span></div>
    </div>`;

  if (premise_warn?.has_false_premise){
    h += `<div class="premise-warn"><strong>False premise flagged</strong>${esc(premise_warn.assumed_fact)}<br><span style="opacity:.75">${esc(premise_warn.explanation||'')}</span></div>`;
  }

  if (note){
    h += `<div class="note-box">${esc(note)}</div>`;
  }
  h += `</div>`;

  // verified holdings
  if (passed.length){
    h += `<div class="r-section"><div class="r-head"><span class="num">04 /</span> <span class="lbl">Verified holdings</span> <span class="count">${passed.length} cleared</span></div>
      <div class="hold-list">${passed.map((x,i)=>renderHold(x,i,true)).join('')}</div></div>`;
  }
  // failed
  if (failed.length){
    h += `<div class="r-section"><div class="r-head"><span class="num">05 /</span> <span class="lbl">Did not clear</span> <span class="count">${failed.length} below threshold</span></div>
      <div class="hold-list">${failed.map((x,i)=>renderHold(x,passed.length+i,false)).join('')}</div></div>`;
  }

  $('results').innerHTML = h;
  // staggered entrance
  document.querySelectorAll('.hold').forEach((el, i) => {
    el.style.animationDelay = (i * 60) + 'ms';
  });
}

function renderHold(h, idx, pass){
  const conf = Math.round((h.judge_conf || 0) * 100);
  const adv = h.adv_verdict || 'skipped';
  return `<article class="hold ${pass?'pass':'fail'}" data-i="${idx}">
    <div class="hold-h" onclick="toggleHold(${idx})">
      <div class="hold-num">${String(idx+1).padStart(2,'0')}</div>
      <div class="hold-main">
        <div class="hold-title">${esc(h.case_name)}</div>
        <div class="hold-meta">
          ${esc(h.citation || 'Citation pending')}<span class="dot-sep">/</span>Para ${esc(h.para_num)}<span class="dot-sep">/</span>${h.is_ratio?'Ratio':'Dicta'}<span class="dot-sep">/</span>${esc(h.court || '')}
        </div>
        <p class="hold-prop">${esc(h.prop)}</p>
        <div class="hold-badges">
          <span class="bd ${pass?'bd-pass':'bd-fail'}">${pass?'Judge pass':'Judge fail'}</span>
          <span class="bd bd-warn">Treatment unverified</span>
          <span class="bd ${h.L1?'bd-pass':'bd-fail'}">L1 ${h.L1?'✓':'✗'}</span>
          <span class="bd ${adv==='SUPPORTED'?'bd-pass':adv==='NOT_SUPPORTED'?'bd-fail':'bd-mute'}">Adv ${esc(adv.toLowerCase())}</span>
          <div class="conf-bar"><div class="conf-track"><div class="conf-fill" style="width:${conf}%"></div></div><span>${conf}%</span></div>
        </div>
      </div>
      <div class="hold-chev">▾</div>
    </div>
    <div class="hold-body">
      ${h.verbatim ? `<div class="hb-label">Verbatim holding <span class="hb-hint">— click quote to verify on Indian Kanoon</span></div><blockquote class="hb-quote"><a class="hb-quote-link" href="${esc(h.ik_url||'#')}" target="_blank" rel="noopener" title="Open judgment on Indian Kanoon. Use Ctrl+F to locate this phrase.">"${esc(h.verbatim)}"<span class="hb-quote-arrow"> ↗</span></a></blockquote>`:''}
      <div class="hb-label">Source paragraph · Para ${esc(h.para_num)}</div>
      <div class="hb-para">${esc((h.para_text||'').slice(0,700))}${(h.para_text||'').length>700?'…':''}</div>
      <div class="hb-verified">
        ${pass
          ? `<span class="hb-verified-badge">Council-verified ✓</span>`
          : `<span class="hb-verified-badge hb-verified-fail">Did not verify ✗</span>`}
      </div>
      <div class="hb-actions">
        <button class="btn-thin" onclick="copyCite(this,'${esc(h.case_name)}, ${esc(h.citation||'')}')">⎘ copy citation</button>
        <a class="btn-thin" href="${esc(h.ik_url||'#')}" target="_blank" rel="noopener" title="Open the full judgment on Indian Kanoon">↗ open source</a>
      </div>
    </div>
  </article>`;
}

window.toggleHold = function(i){
  const el = document.querySelector('.hold[data-i="'+i+'"]');
  if (el) el.classList.toggle('open');
};
window.copyCite = function(btn, txt){
  navigator.clipboard.writeText(txt).then(()=>{
    const orig = btn.innerHTML;
    btn.classList.add('copied');
    btn.innerHTML = '✓ copied';
    setTimeout(()=>{ btn.classList.remove('copied'); btn.innerHTML = orig; }, 1800);
  });
};

/* ───────── Init ───────── */
checkHealth();
autoSizeTextarea();

/* ───────── Scroll reveal ───────── */
const _io = new IntersectionObserver((entries) => {
  for (const e of entries){
    if (e.isIntersecting){
      e.target.classList.add('sr-in');
      _io.unobserve(e.target);
    }
  }
}, { threshold: 0, rootMargin: '0px 0px -4% 0px' });
document.querySelectorAll('.sr').forEach(el => {
  _io.observe(el);
  // failsafe: if the observer never fires (rare layout edge cases),
  // reveal anyway so nothing stays hidden.
  setTimeout(() => el.classList.add('sr-in'), 1600);
});

/* ───────── Busy buffering on the query card ───────── */
const _glass = $('glassCard');
const _origRun = run;
window.run = async function(){
  if (appState.busy) return;
  _glass?.classList.add('busy');
  try{ await _origRun(); }
  finally{ _glass?.classList.remove('busy'); }
};
$('run').onclick = window.run;
qEl.addEventListener('keydown', e => {
  if ((e.key === 'Enter' && (e.ctrlKey || e.metaKey)) || (e.key === 'Enter' && !e.shiftKey)){
    e.preventDefault(); window.run();
  }
}, true);

/* ───────── Query history (browser localStorage) ───────── */
const HIST_KEY = 'karyaniti_history_v1';
const HIST_MAX = 25;

function loadHistory(){
  try { return JSON.parse(localStorage.getItem(HIST_KEY) || '[]'); }
  catch { return []; }
}

function saveHistory(query, data){
  if (!query) return;
  try {
    const list = loadHistory();
    const passed = (data.holdings || []).filter(h => h.pass).length;
    const total = (data.holdings || []).length;
    // Remove any earlier entry with the same query so it floats to top
    const filtered = list.filter(e => e.q !== query);
    filtered.unshift({
      q: query,
      pass: passed,
      total: total,
      ts: Date.now()
    });
    localStorage.setItem(HIST_KEY, JSON.stringify(filtered.slice(0, HIST_MAX)));
    renderHistory();
  } catch (e) {
    console.warn('history save failed', e);
  }
}

function clearHistory(){
  try { localStorage.removeItem(HIST_KEY); } catch {}
  renderHistory();
}

function fmtAgo(ts){
  const d = Date.now() - ts;
  if (d < 60_000) return 'just now';
  if (d < 3_600_000) return Math.floor(d/60_000) + 'm';
  if (d < 86_400_000) return Math.floor(d/3_600_000) + 'h';
  return Math.floor(d/86_400_000) + 'd';
}

function escHtml(s){
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function renderHistory(){
  const root = document.getElementById('historyList');
  if (!root) return;
  const list = loadHistory();
  if (!list.length){
    root.innerHTML = '<p class="hist-empty">No previous queries yet.</p>';
    return;
  }
  root.innerHTML = list.map(e => `
    <button class="hist-item" data-q="${escHtml(e.q)}">
      <span class="hist-q">${escHtml(e.q)}</span>
      <span class="hist-meta">
        <span class="hist-pass">${e.pass}/${e.total}</span>
        <span class="hist-ago">${fmtAgo(e.ts)}</span>
      </span>
    </button>
  `).join('');
  root.querySelectorAll('.hist-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.q;
      qEl.value = q;
      qEl.focus();
      run();
    });
  });
}

// Render history on page load
document.addEventListener('DOMContentLoaded', renderHistory);
// Also try immediately in case DOM already loaded
if (document.readyState !== 'loading') renderHistory();
