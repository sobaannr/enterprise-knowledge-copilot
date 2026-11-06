"use strict";
let token = "", currentRun = null, user = null, conversationId = null;
const $ = id => document.getElementById(id);
$("new-conversation").addEventListener("click", () => { conversationId = null; $("conversation-label").textContent = "New conversation"; });
const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function notify(message) { $("notice").textContent = message; $("notice").hidden = !message; }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {"Content-Type":"application/json", "Authorization":`Bearer ${token}`, ...options.headers}});
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`); }
  return response;
}
$("connect-form").addEventListener("submit", async event => {
  event.preventDefault(); token = $("token").value.trim(); notify("");
  try {
    user = await (await api("/api/me")).json();
    const incidents = await (await api("/api/incidents")).json();
    $("incident").innerHTML = '<option value="">Resolve from question</option>' + incidents.map(i => `<option value="${escapeHTML(i.id)}">${escapeHTML(i.title)} · ${escapeHTML(i.started_at.slice(0,10))}</option>`).join("");
    $("connection").hidden = true; $("token").value = ""; $("analyze").disabled = false;
    $("mode").textContent = user.retrieval === "gemini" ? `Gemini embeddings + FAISS + BM25 · ${user.generation_model}` : `${user.retrieval === "local" ? "Local BM25" : "OpenSearch hybrid"} · ${user.rerank ? "cross-encoder" : "no reranker"}`;
    if ((user.retrieval === "gemini" || user.generation === "gemini") && !user.gemini_configured) notify("Setup: fill GEMINI_API_KEY in your .env file and restart the server. Your database is already ready.");
    await loadTickets();
  } catch (error) { token = ""; notify(error.message); }
});
$("ask-form").addEventListener("submit", async event => {
  event.preventDefault(); notify(""); currentRun = null;
  $("analyze").disabled = true; $("progress").hidden = false; $("progress").textContent = "Starting investigation…";
  $("result").hidden = true; $("empty-state").hidden = true;
  try {
    const response = await api("/api/runs/stream", {method:"POST", body:JSON.stringify({question:$("question").value.replace(/[’]/g,"'"), incident_id:$("incident").value || null, conversation_id:conversationId})});
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "", received = false;
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream:true});
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0,boundary); buffer = buffer.slice(boundary+2);
        const type = frame.split("\n").find(l=>l.startsWith("event: "))?.slice(7);
        const raw = frame.split("\n").filter(l=>l.startsWith("data: ")).map(l=>l.slice(6)).join("\n");
        if (!raw) continue; const data = JSON.parse(raw);
        if (type === "progress") { const labels = {started:"Resolving the incident…", resolve:"Retrieving evidence: query rewrite, cached embeddings, hybrid search and reranking…",retrieve:"Joining customer and subscription records…",synthesize:"Generating a cited answer…",generate:"Checking each claim against its sources…",verify:"Planning policy-eligible follow-up drafts…",plan_actions:"Saving the proposal for your approval…"}; $("progress").textContent = labels[data.stage] || data.message; }
        if (type === "error") throw new Error(data.message);
        if (type === "result") { received = true; currentRun = data; conversationId = data.conversation_id; $("conversation-label").textContent = "Conversation active: follow-up questions can refer to this incident"; renderResult(data); }
      }
    }
    if (!received) throw new Error("Connection ended before a result arrived. No tickets were created.");
  } catch (error) { notify(error.message); }
  finally { $("analyze").disabled = false; $("progress").hidden = true; }
});
function citations(ids, sourceMap) {
  return ids.map(id=>`<a class="source-chip" href="#source-${sourceMap.get(id)}">${escapeHTML(id.split(":").slice(-1)[0])}</a>`).join("");
}
function draftCard(d) {
  return `<div class="card draft"><h3>${escapeHTML(d.title)}</h3><small>ASSIGNED TO ${escapeHTML(d.assigned_to)}</small><pre>${escapeHTML(d.body)}</pre></div>`;
}
function renderResult(data) {
  const map = new Map(data.sources.map((s,i)=>[s.id,i]));
  $("result").hidden = false;
  $("result").innerHTML = `<div class="result-header">◈ INVESTIGATION ${data.verification?.passed ? "VERIFIED AGAINST SOURCES" : "RESULT"}</div><div class="result-summary">${escapeHTML(data.summary)}</div>
    ${data.answer_mode === "gemini" ? `<p class="muted">Gemini answer · ${data.verification.accepted || 0} claims accepted · ${data.verification.rejected || 0} rejected by verification</p><section class="result-section"><h2>AI evidence summary</h2>${(data.ai_findings || []).map(f=>`<div class="finding">${escapeHTML(f.text)}<div>${citations(f.source_ids,map)}</div></div>`).join("")}</section>` : ""}
    ${data.verification?.errors?.length ? `<div class="warning">${data.verification.errors.map(escapeHTML).join(" ")}</div>` : ""}
    ${data.action_plan ? '<p class="muted">Gemini proposed prepare_followups. The server validated the incident and eligible customers. Human approval is pending.</p>' : ''}
    ${data.time_basis ? `<p class="muted">${escapeHTML(data.time_basis)}</p>` : ""}
    <section class="result-section">${data.findings.map(f=>`<div class="finding">${escapeHTML(f.text)}<div>${citations(f.source_ids,map)}</div></div>`).join("")}</section>
    ${data.conflicts.map(c=>`<div class="warning"><strong>Conflicting evidence</strong>${escapeHTML(c.message)}<div>${citations(c.source_ids,map)}</div></div>`).join("")}
    ${data.gaps.map(g=>`<div class="warning"><strong>Information gap</strong>${escapeHTML(g.message)}</div>`).join("")}
    ${data.drafts.length ? `<section class="result-section"><h2>Proposed follow-ups · ${data.drafts.length}</h2>${data.drafts.map(draftCard).join("")}<div id="approval" class="approval-bar"><p>Review the complete tickets above. Approval creates these tickets in the local action ledger. Proposal expires ${escapeHTML(new Date(data.proposal.expires_at).toLocaleTimeString())}.</p><button id="approve" class="button dark" ${user.role !== "operator" ? "disabled" : ""}>Approve & create ${data.drafts.length} tickets</button><button id="reject" class="button secondary" ${user.role !== "operator" ? "disabled" : ""}>Reject proposal</button>${user.role !== "operator" ? '<p>An operator must approve this proposal.</p>' : ""}</div></section>` : ""}
    <section class="result-section"><h2>Evidence library · ${data.sources.length}</h2>${data.sources.map((s,i)=>`<details class="source" id="source-${i}"><summary>${escapeHTML(s.title)}</summary><span class="source-meta">${escapeHTML(s.id)} · ${escapeHTML(s.kind)} ${s.revision ? `· revision ${s.revision}` : ""}</span><p>${escapeHTML(s.excerpt)}</p></details>`).join("")}</section>
    ${data.verification ? `<p class="muted">${escapeHTML(data.verification.method)} ${escapeHTML(data.verification.limitations)}</p>` : ""}`;
  $("approve")?.addEventListener("click",()=>decide("approve"));
  $("reject")?.addEventListener("click",()=>decide("reject"));
  document.querySelectorAll(".source-chip").forEach(link=>link.addEventListener("click",()=>{ const target = document.querySelector(link.getAttribute("href")); if (target) target.open = true; }));
}
async function decide(decision) {
  if (!currentRun?.proposal) return;
  $("approve").disabled = true; $("reject").disabled = true; notify("");
  try {
    const p = currentRun.proposal;
    const receipt = await (await api(`/api/proposals/${encodeURIComponent(p.id)}/decision`, {method:"POST", body:JSON.stringify({digest:p.digest,decision})})).json();
    $("approval").className = "receipt";
    $("approval").textContent = decision === "approve" ? `${receipt.tickets.length} follow-ups recorded. Existing tickets are reused to prevent duplicates.` : "Proposal rejected. No tickets were created by this decision.";
    await loadTickets();
  } catch (error) { notify(error.message); $("approve").disabled = false; $("reject").disabled = false; }
}
async function loadTickets() {
  const tickets = await (await api("/api/tickets")).json();
  $("ticket-count").textContent = tickets.length;
  $("tickets-list").innerHTML = tickets.length ? tickets.map(draftCard).join("") : '<div class="empty-state">No tickets yet. Review and approve a proposal to create follow-ups.</div>';
}
async function loadAudit() {
  const events = await (await api("/api/audit")).json();
  $("audit-list").innerHTML = events.length ? `<div class="table-wrap"><table class="audit-table"><thead><tr><th>TIME</th><th>ACTION</th><th>ACTOR</th><th>DETAILS</th></tr></thead><tbody>${events.map(e=>`<tr><td>${escapeHTML(new Date(e.created_at).toLocaleString())}</td><td>${escapeHTML(e.action)}</td><td>${escapeHTML(e.actor)}</td><td>${escapeHTML(JSON.stringify(e.details))}</td></tr>`).join("")}</tbody></table></div>` : '<div class="empty-state">No activity yet.</div>';
}
document.querySelectorAll(".nav").forEach(button=>button.addEventListener("click",async()=>{
  notify(""); document.querySelectorAll(".nav").forEach(b=>{ b.classList.toggle("active",b===button); b.setAttribute("aria-current", b===button ? "page" : "false"); });
  document.querySelectorAll(".panel").forEach(p=>p.hidden = p.id !== `${button.dataset.panel}-panel`);
  $("page-label").textContent = {workspace:"Knowledge & action",knowledge:"Knowledge library",tickets:"Follow-up tickets",audit:"Activity log",metrics:"Monitoring"}[button.dataset.panel];
  if (!token && button.dataset.panel !== "workspace") return notify("Connect to the workspace first.");
  try { if (button.dataset.panel === "tickets") await loadTickets(); if (button.dataset.panel === "audit") await loadAudit(); if (button.dataset.panel === "metrics") await loadMetrics(); }
  catch (error) { notify(error.message); }
}));

$("knowledge-form").addEventListener("submit", async event => {
  event.preventDefault(); notify("");
  if (!token) return notify("Connect to the workspace first.");
  $("knowledge-submit").disabled = true; $("knowledge-result").textContent = "Retrieving and checking source passages…";
  try {
    const data = await (await api("/api/answers", {method:"POST",body:JSON.stringify({question:$("knowledge-question").value})})).json();
    const items = data.claims || data.quotes;
    const byId = new Map(data.sources.map(s=>[s.chunk_id,s]));
    $("knowledge-result").innerHTML = `<section class="result-section"><h2>${items.length ? "Cited answer" : "Insufficient evidence"}</h2><p class="muted">${escapeHTML(data.mode)} · ${data.verification.accepted} accepted · ${data.verification.rejected} rejected</p>${items.map(q=>`<div class="card draft">${q.title ? `<h3>${escapeHTML(q.title)}</h3>` : ""}<p class="finding">${escapeHTML(q.text)}</p>${(q.source_ids || [q.source_id]).map(id=>`<details class="source"><summary>${escapeHTML(byId.get(id)?.title || id)}</summary><small>${escapeHTML(id)}</small><p>${escapeHTML(byId.get(id)?.excerpt || "")}</p></details>`).join("")}</div>`).join("")}<p class="muted">${escapeHTML(data.verification.limitation)}</p></section>`;
  } catch (error) { notify(error.message); $("knowledge-result").textContent = ""; }
  finally { $("knowledge-submit").disabled = false; }
});

async function loadMetrics() {
  const data = await (await api("/api/metrics")).json();
  $("metrics-list").innerHTML = `<div class="metric-grid"><div class="metric-card"><small>Operations</small><strong>${data.count}</strong></div><div class="metric-card"><small>Median latency</small><strong>${data.p50_ms ?? "—"} <span>ms</span></strong></div><div class="metric-card"><small>95th percentile</small><strong>${data.p95_ms ?? "—"} <span>ms</span></strong></div><div class="metric-card"><small>Error rate</small><strong>${data.error_rate === null ? "—" : (100*data.error_rate).toFixed(1)+"%"}</strong></div></div><div class="table-wrap"><table class="audit-table"><thead><tr><th>Operation</th><th>Status</th><th>Latency</th><th>Verification</th><th>Estimated USD</th></tr></thead><tbody>${data.recent.map(r => `<tr><td>${escapeHTML(r.operation)}</td><td><span class="status-pill ${r.status === "error" ? "error" : ""}">${escapeHTML(r.status)}</span></td><td>${r.latency_ms} ms</td><td>${escapeHTML(r.verification?.passed === true ? "Source checks passed" : r.verification?.passed === false ? "Needs review" : r.verification ? `${r.verification.accepted ?? 0} accepted / ${r.verification.rejected ?? 0} rejected` : "No result")}</td><td>${r.estimated_usd === null ? "Unknown" : r.estimated_usd.toFixed(6)}</td></tr>`).join("")}</tbody></table></div>`;
}
