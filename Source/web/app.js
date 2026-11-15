/* No build tools, CDNs, or external assets required. */
"use strict";
const $ = id => document.getElementById(id);
const palette = ["#242636", "#ef5261", "#ffab40", "#f7d34c", "#4dbb87", "#4989ed", "#9567df", "#ffffff"];
let socket, pc, channel, state, mode = "join", theme = "Animals", color = palette[0], tool = "brush";
let session, reconnectTimer, reconnectAttempts = 0, intentionalLeave = false, entering = false;
let activeStroke = null, committed = new Set(), previews = new Map(), canvasTurn = "", lastRev = 0;
let lastCoverKey = "", lastPlayersKey = "", strokeSeq = 0, lastPointTime = 0, toastTimer;
const previousScores = new Map();
const experience = window.MessExperience;
let connectionMode = "lan", availableNetworks = null, networkRequest = 0;
const base = $("canvas"), ctx = base.getContext("2d", {willReadFrequently: true});
const overlay = $("overlay"), over = overlay.getContext("2d");
const W = base.width, H = base.height;
const safe = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
try { session = JSON.parse(sessionStorage.getItem("guess-the-mess-session") || "null"); } catch { session = null; }
const codeFromLink = new URLSearchParams(location.search).get("room");
if (codeFromLink) $("roomCode").value = codeFromLink.toUpperCase();

function toast(text, success = false) {
  $("toast").textContent = text; $("toast").classList.toggle("success", success);
  $("toast").hidden = false; clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 4200);
}
function setMode(value) {
  mode = value;
  $("joinTab").setAttribute("aria-selected", value === "join");
  $("createTab").setAttribute("aria-selected", value === "create");
  $("joinFields").hidden = value !== "join"; $("createFields").hidden = value !== "create";
  $("roomCode").required = value === "join"; $("roomName").required = value === "create";
  $("enterButton").innerHTML = value === "join" ? 'Join the fun <span>↗</span>' : 'Make some room <span>↗</span>';
  $("entryMessage").textContent = "";
  if(value === "create") refreshNetworks();
  else $("enterButton").disabled = entering;
}

function renderNetworks() {
  const selected = availableNetworks?.[connectionMode];
  document.querySelectorAll("[data-connection]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.connection===connectionMode)));
  $("networkMessage").textContent = selected?.message || "Checking the host’s connections…";
  $("networkMessage").className = selected?.ready ? "network-ready" : "network-unavailable";
  const old = $("inviteAddress").value;
  $("inviteAddress").replaceChildren();
  for(const address of selected?.addresses || []) {
    const option = document.createElement("option");option.value=address.ip;
    option.textContent=`${address.label} · ${address.ip}`;$("inviteAddress").append(option);
  }
  const values=(selected?.addresses || []).map(a=>a.ip);
  if(values.includes(old)) $("inviteAddress").value=old;
  else if(values.includes(availableNetworks?.current_address)) $("inviteAddress").value=availableNetworks.current_address;
  const multiple=values.length>1;
  $("inviteAddress").hidden=$("addressLabel").hidden=!multiple;
  if(mode==="create") $("enterButton").disabled=entering || !selected?.ready;
}
async function refreshNetworks() {
  const request=++networkRequest;
  availableNetworks=null;renderNetworks();$("refreshNetwork").disabled=true;
  try {
    const response=await fetch("/network-options",{cache:"no-store"});
    if(!response.ok) throw new Error();
    const options=await response.json();
    if(request===networkRequest) availableNetworks=options;
  } catch {
    if(request===networkRequest) availableNetworks={lan:{ready:false,message:"Cannot check the host’s connections. Refresh to retry."},tailscale:{ready:false,message:"Cannot check Tailscale on the host PC. Refresh to retry."}};
  } finally {
    if(request===networkRequest) {renderNetworks();$("refreshNetwork").disabled=false;}
  }
}
document.querySelectorAll("[data-connection]").forEach(button=>{
  button.onclick=()=>{connectionMode=button.dataset.connection;renderNetworks();};
});
$("refreshNetwork").onclick=refreshNetworks;
$("joinTab").onclick = () => setMode("join");
$("createTab").onclick = () => setMode("create");
document.querySelectorAll(".themes [data-theme]").forEach(button => {
  button.onclick = () => { theme = button.dataset.theme; document.querySelectorAll(".themes [data-theme]").forEach(b => b.classList.toggle("selected", b === button)); };
});
$("helpButton").onclick = () => $("helpDialog").showModal();
$("closeHelp").onclick = $("helpDone").onclick = () => $("helpDialog").close();

function send(data) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify(data)); return true;
}
function status(id, good, text) {
  $(id).textContent = `● ${text}`; $(id).className = good ? "good" : "bad";
}
function connect(firstMessage) {
  clearTimeout(reconnectTimer);
  if (socket && socket.readyState <= WebSocket.OPEN) socket.close();
  intentionalLeave = false;
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws`);
  socket = ws;
  ws.onopen = () => { status("tcpStatus", true, "TCP connected"); ws.send(JSON.stringify(firstMessage)); };
  ws.onmessage = event => { if (socket === ws) receive(JSON.parse(event.data)); };
  ws.onclose = () => {
    if (socket !== ws) return;
    status("tcpStatus", false, "TCP disconnected"); closeRTC();
    document.body.classList.remove("time-pressure", "final-seconds");
    entering = false; $("enterButton").disabled = false;
    if (session && !intentionalLeave) {
      $("connectionBanner").hidden = false;
      reconnectAttempts++;
      reconnectTimer = setTimeout(() => connect({type:"resume", ...session}), Math.min(1000 * reconnectAttempts, 5000));
      render();
    } else if (!intentionalLeave) $("entryMessage").textContent = "Cannot reach the server. Check its address and whether it is running.";
  };
  ws.onerror = () => {};
}
$("entryForm").onsubmit = event => {
  event.preventDefault(); if (entering) return;
  if(mode==="create" && !availableNetworks?.[connectionMode]?.ready) {renderNetworks();return;}
  entering = true; $("enterButton").disabled = true;
  $("entryMessage").textContent = "Connecting…";
  connect({type:mode, name:$("nickname").value, code:$("roomCode").value,
           room_name:$("roomName").value, theme, avatar:experience.avatar,
           connection_mode:connectionMode, invite_address:$("inviteAddress").value});
};

function closeRTC() {
  if (channel) { channel.onclose = null; channel.onmessage = null; channel.close(); }
  if (pc) { pc.onconnectionstatechange = null; pc.close(); }
  channel = pc = null;
  status("udpStatus", false, "UDP disconnected");
}
async function setupRTC() {
  closeRTC(); status("udpStatus", false, "UDP connecting…");
  if (!window.RTCPeerConnection) { toast("This browser does not support WebRTC. Try current Chrome, Edge, or Firefox."); return; }
  const peer = new RTCPeerConnection({iceServers:[]}); pc = peer;
  const dc = peer.createDataChannel("drawing", {ordered:false, maxRetransmits:0}); channel = dc;
  dc.onopen = () => { if (channel === dc) { dc.send("hello"); status("udpStatus", true, "UDP connected"); render(); } };
  dc.onclose = () => { if (channel === dc) { status("udpStatus", false, "UDP disconnected — repair"); render(); } };
  dc.onmessage = event => {
    if (event.data === "hello") return;
    try {
      const message = JSON.parse(event.data);
      if (message.type !== "preview" || message.turn !== canvasTurn || committed.has(message.op.id)) return;
      let stroke = previews.get(message.op.id);
      if (!stroke) { if (previews.size > 100) return; stroke = {chunks:new Map(), color:message.op.color, erase:message.op.erase, seen:Date.now()}; previews.set(message.op.id, stroke); }
      stroke.seen = Date.now(); stroke.chunks.set(message.op.seq, message.op.points); drawOverlay();
    } catch { /* Ignore an invalid or obsolete preview. */ }
  };
  try {
    await peer.setLocalDescription(await peer.createOffer());
    if (peer.iceGatheringState !== "complete") {
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error("UDP setup timed out. Check your firewall.")), 12000);
        peer.addEventListener("icegatheringstatechange", () => { if (peer.iceGatheringState === "complete") { clearTimeout(timeout); resolve(); } });
      });
    }
    if (pc === peer) send({type:"offer", sdp:peer.localDescription.sdp});
  } catch (error) { if (pc === peer) toast(error.message); }
}
$("repairButton").onclick = () => setupRTC();

function receive(message) {
  switch (message.type) {
    case "welcome":
      session = {code:message.code, token:message.token};
      sessionStorage.setItem("guess-the-mess-session", JSON.stringify(session));
      entering = false; reconnectAttempts = 0; $("enterButton").disabled = false;
      $("entryMessage").textContent = ""; $("connectionBanner").hidden = true;
      $("entry").hidden = true; $("game").hidden = false; $("footer").hidden = true;
      setupRTC(); break;
    case "answer":
      if (pc) pc.setRemoteDescription({type:"answer", sdp:message.sdp}).catch(e => toast(e.message)); break;
    case "state":
      state = message;
      experience.update(state);
      if (canvasTurn !== state.turn) resetCanvas(state.turn);
      if (!canDraw() && activeStroke) { activeStroke = null; drawOverlay(); }
      render(); break;
    case "chat": addChat(message); break;
    case "notice":
      toast(message.text, message.success);
      if(message.effect) experience.feedback(message.effect, message.text);
      break;
    case "feedback": experience.feedback(message.effect); break;
    case "error":
      entering = false; $("enterButton").disabled = false;
      if (message.reset) { returnToEntry(); $("entryMessage").textContent = message.text; }
      else if (session && !state) { forgetSession(); $("entryMessage").textContent = message.text; }
      else if ($( "game").hidden) $("entryMessage").textContent = message.text;
      else toast(message.text);
      break;
    case "canvas":
      resetCanvas(message.turn);
      for (const op of message.ops) applyCommit(op);
      break;
    case "commit":
      if (message.turn === canvasTurn) {
        if (message.op.rev > lastRev + 1) send({type:"sync"});
        else applyCommit(message.op);
      }
      break;
    case "left": returnToEntry(); break;
    case "diagnostics": {
      $("diagnostics").hidden = false;
      const s = message.stats;
      $("diagnostics").textContent = `Server totals since launch: ${s.tcp_messages} WebSocket messages · ${s.udp_received} UDP drawing packets received · ${s.udp_relayed} UDP drawing packets relayed · ${s.commits} reliable canvas operations.\nDrawing: unordered WebRTC data channel, zero retransmissions, SCTP/DTLS over UDP. Completed strokes and bucket/clear operations are confirmed over TCP. No camera or microphone is used.`;
      if (pc) pc.getStats().then(stats => {
        for (const report of stats.values()) if (report.type === "transport") $("diagnostics").textContent += `\nThis browser transport: ${report.dtlsState || "negotiating"}; bytes sent ${report.bytesSent || 0}, received ${report.bytesReceived || 0}.`;
      });
      break;
    }
  }
}

function forgetSession() {
  session = null; sessionStorage.removeItem("guess-the-mess-session");
  clearTimeout(reconnectTimer); intentionalLeave = true;
  if (socket) socket.close(); closeRTC();
}
function returnToEntry() {
  forgetSession(); state = null; lastCoverKey = lastPlayersKey = "";
  $("game").hidden = true; $("entry").hidden = false; $("footer").hidden = false;
  document.body.classList.remove("time-pressure", "final-seconds");
  previousScores.clear();
  $("entryMessage").textContent = "You left the room. There’s always another round.";
  $("chatLog").innerHTML = '<div class="chat-welcome">Say hello. Then trust your instincts.</div>';
  history.replaceState(null, "", location.pathname);
}
$("leaveButton").onclick = () => { if (!send({type:"leave"})) returnToEntry(); };
$("shareButton").onclick = async () => {
  const link = state.invite_url;
  if(!link) {toast("The room’s invite address is not available yet.");return;}
  const text = `${link}\nRoom code: ${state.code}`;
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
    else { const el = document.createElement("textarea"); el.value = text; document.body.append(el); el.select(); if (!document.execCommand("copy")) throw new Error(); el.remove(); }
    toast(state.connection_mode==="tailscale" ? "Invite copied. Friends must be connected to your tailnet." : "Invite copied. Friends must be on the same Wi-Fi / LAN.", true);
  } catch { window.prompt("Copy this room invite:", text); }
};
$("waitButton").onclick = () => send({type:"wait"});
$("continueButton").onclick = () => send({type:"continue"});
$("diagnosticsButton").onclick = () => { if (!$("diagnostics").hidden) $("diagnostics").hidden = true; else send({type:"diagnostics"}); };

function canDraw() {
  return state && state.phase === "drawing" && state.drawer === state.you && !state.paused.length
    && socket?.readyState === WebSocket.OPEN && channel?.readyState === "open";
}
function render() {
  if (!state) return;
  const s = state, host = s.host === s.you, me = s.players.find(p => p.id === s.you);
  $("game").dataset.phase = s.phase;
  $("roomTitle").textContent = s.name; $("roomTheme").textContent = `${s.theme.toUpperCase()} · ROOM ${s.code}`;
  $("connectionModeLabel").textContent = s.connection_mode==="tailscale" ? "↗ Tailscale room" : "⌂ Wi-Fi / LAN room";
  $("inviteLink").textContent = s.invite_url || "";
  $("codeDisplay").textContent = s.code; $("playerCount").textContent = `${s.players.length} / ${s.max_players}`;
  const playersKey = JSON.stringify([s.players, s.host, s.drawer, s.phase]);
  if (playersKey !== lastPlayersKey) {
    const high = Math.max(100,...s.players.map(p=>p.score));
    $("players").innerHTML = s.ranking.map(r => {
      const p=s.players.find(p=>p.id===r.id), increased=previousScores.has(p.id) && p.score>previousScores.get(p.id);
      previousScores.set(p.id,p.score);
      return `<div class="player ${p.id===s.you?"is-you":""} ${p.guessed&&s.phase==="drawing"?"has-guessed":""} ${p.id===s.drawer&&s.phase==="drawing"?"is-drawing":""} ${increased?"score-up":""}"><span class="player-rank">${r.rank===1&&p.score>0?"♛":`#${r.rank}`}</span><div class="avatar">${safe(p.avatar || "👾")}</div><div class="player-info"><div class="player-name" title="${safe(p.name)}">${safe(p.name)}${p.id === s.you ? ' <small>YOU</small>' : ""}</div><div class="player-role">${!p.connected ? "○ Offline" : p.guessed && s.phase === "drawing" ? "✓ Got it!" : p.id === s.drawer && s.phase === "drawing" ? "✎ Making a mess" : p.udp ? "Ready to rumble" : "Connecting…"}${p.id === s.host ? " · Host" : ""}</div><div class="score-track"><i style="width:${p.score/high*100}%"></i></div></div><div class="player-score">${p.score}<small>PTS</small>${increased?'<span class="score-spark">✦</span>':""}</div></div>`;
    }).join("");
    lastPlayersKey = playersKey;
  }
  $("roundLabel").textContent = ["lobby", "finished"].includes(s.phase) ? (s.phase === "lobby" ? "WAITING ROOM" : "THAT’S A WRAP") : `ROUND ${s.round} OF ${s.rounds} · ${s.theme.toUpperCase()}`;
  const drawer = s.players.find(p => p.id === s.drawer);
  $("turnLabel").textContent = s.phase === "drawing" ? (s.drawer === s.you ? "Your moment. Make your mark." : `${drawer?.name || "A friend"} is drawing…`) : s.phase === "intermission" ? "A round of applause, please." : s.phase === "finished" ? "Good drawings. Better company." : "Gather your people.";
  $("timer").textContent = s.phase === "drawing" || s.phase === "intermission" ? Math.ceil(s.remaining) : "—";
  $("timer").classList.toggle("urgent", s.phase === "drawing" && s.remaining <= 20);
  $("wordCaption").textContent = s.phase === "drawing" ? s.word ? "YOUR SECRET WORD · DON’T WRITE IT OUT" : "GUESS THE WORD" : "A little imagination goes a long way.";
  $("wordMask").textContent = s.word || s.mask || "";
  $("pauseBanner").hidden = !s.paused.length;
  $("pauseText").textContent = `Waiting for ${s.paused.join(", ")}. The timer and all actions are frozen.`;
  $("pauseControls").hidden = !host;
  const blocked = s.paused.length || socket?.readyState !== WebSocket.OPEN || s.phase === "intermission" || (s.phase === "drawing" && (s.drawer === s.you || me?.guessed));
  $("chatInput").disabled = !!blocked; $("chatForm").querySelector("button").disabled = !!blocked;
  $("chatInput").placeholder = s.paused.length ? "Game paused…" : me?.guessed && s.phase === "drawing" ? "You got it! Sit tight." : s.drawer === s.you && s.phase === "drawing" ? "Let your drawing do the talking." : "Type a guess…";
  $("chatHint").textContent = s.phase === "drawing" && me?.guessed ? "Chat returns next turn. Keep the secret!" : "Correct answers stay secret.";
  const drawing = !!canDraw();
  document.querySelectorAll("[data-tool], .color").forEach(b => { b.disabled = !drawing; });
  $("clearButton").disabled = !drawing;
  overlay.style.cursor = drawing ? tool === "fill" ? "cell" : "crosshair" : "default";
  $("drawHint").textContent = drawing ? "Make your mark." : s.phase === "drawing" ? "Trust your instincts." : "Make yourself comfortable.";
  $("stageCover").hidden = s.phase === "drawing";
  // Rebuild covers only when their meaningful content changes, preserving focus.
  const key = JSON.stringify([s.phase, s.players.map(p=>[p.name,p.connected,p.udp]), host, s.phase === "finished" ? s.ranking : s.result]);
  if (key === lastCoverKey) return;
  lastCoverKey = key;
  let content = "";
  if (s.phase === "lobby") {
    const ready = s.players.length >= s.min_players && s.players.every(p => p.connected && p.udp);
    content = `<div class="lobby-avatars">${s.players.map(p=>`<span title="${safe(p.name)}">${safe(p.avatar||"👾")}</span>`).join("")}</div><div class="eyebrow">THE PRE-GAME HUDDLE</div><h2>Your chaos crew.</h2><p>One theme. One turn each.<br>Absolutely no artistic standards.</p>${host ? `<button id="startButton" class="primary" ${ready ? "" : "disabled"}>Everybody in? Let’s draw ↗</button><p class="cover-small">${s.players.length < s.min_players ? `Waiting for at least ${s.min_players} players…` : ready ? "The crew is ready. Unleash the mess." : "Waiting for everyone’s UDP connection…"}</p>` : '<p class="cover-small">The host will start when everyone is ready.</p>'}`;
  } else if (s.phase === "intermission") {
    content = `<div class="cover-icon">✦</div><div class="eyebrow">THE WORD WAS</div><h2>${safe(s.result?.word)}</h2><p>${s.result?.skipped ? "The drawer left. Moving along!" : `${safe(s.result?.drawer)} earned <b>${s.result?.bonus} drawing points</b>.<br>${s.result?.guessed} ${s.result?.guessed === 1 ? "person guessed" : "people guessed"} correctly.`}</p><p class="cover-small">Next turn coming up…</p>`;
  } else if (s.phase === "finished") {
    const top = s.ranking.filter(p => p.rank <= 3);
    content = `<div class="eyebrow">THE DOODLE HALL OF FAME</div><h2>Certified mess legends.</h2><div class="podium">${top.map(p => `<div class="podium-person place-${p.rank}"><span class="place">${["","🥇","🥈","🥉"][p.rank]}</span><span class="podium-avatar">${safe(p.avatar||"👾")}</span><b>${safe(p.name)}</b><small>${p.score} points</small><span class="podium-rank">#${p.rank}</span></div>`).join("")}</div><div class="final-scores">${s.ranking.map(p => `${safe(p.name)} · ${p.score}`).join(" &nbsp; / &nbsp; ")}</div>${host ? `<button id="startButton" class="primary" ${s.players.length >= s.min_players && s.players.every(p=>p.connected && p.udp) ? "" : "disabled"}>Rematch. Settle the score. ↗</button>` : '<p class="cover-small">Waiting for the host to start a rematch.</p>'}`;
  }
  $("stageContent").innerHTML = content;
  if ($("startButton")) $("startButton").onclick = () => send({type:"start"});
}

function addChat(message) {
  const log = $("chatLog"), nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 70;
  const item = document.createElement("div"); item.className = `chat-item ${message.kind}`;
  if(message.kind==="correct") {
    item.innerHTML=`<span class="chat-medal">${["","🥇","🥈","🥉","✨"][message.place] || "★"}</span><div><b>${safe(message.name)}</b><span class="chat-success-label">guessed the mess!</span></div><strong class="chat-points">+${message.points}</strong>`;
    if(message.player!==state?.you) experience.play("pop");
  } else if(message.name) {
    item.classList.add("bubble");if(message.player===state?.you)item.classList.add("mine");
    item.innerHTML=`<span class="chat-avatar">${safe(message.avatar||"👾")}</span><div class="bubble-content"><b>${safe(message.name)}</b><span>${safe(message.text)}</span></div>`;
  } else item.append(document.createTextNode(message.text));
  log.append(item);
  while (log.children.length > 200) log.firstChild.remove();
  if (nearBottom || message.kind === "correct") log.scrollTop = log.scrollHeight;
}
$("chatForm").onsubmit = event => { event.preventDefault(); const input = $("chatInput"); if (!input.disabled && input.value.trim() && send({type:"chat", text:input.value})) input.value = ""; };

// Canvas operations use normalized coordinates and a fixed logical size on every device.
function resetCanvas(turn) {
  ctx.fillStyle = "#ffffff"; ctx.fillRect(0,0,W,H);
  over.clearRect(0,0,W,H); committed.clear(); previews.clear(); activeStroke = null;
  canvasTurn = turn; lastRev = 0;
}
function stroke(context, points, c, erase) {
  if (!points.length) return;
  context.strokeStyle = context.fillStyle = erase ? "#ffffff" : c;
  context.lineWidth = erase ? 24 : 5; context.lineCap = context.lineJoin = "round";
  if (points.length === 1) { context.beginPath(); context.arc(points[0][0]*W, points[0][1]*H, context.lineWidth/2,0,2*Math.PI); context.fill(); return; }
  context.beginPath(); context.moveTo(points[0][0]*W,points[0][1]*H);
  for (const [x,y] of points.slice(1)) context.lineTo(x*W,y*H);
  context.stroke();
}
function flood(point, hex) {
  const img = ctx.getImageData(0,0,W,H), pixels = img.data;
  const x = Math.min(W-1, Math.floor(point[0]*W)), y = Math.min(H-1,Math.floor(point[1]*H));
  const start = (y*W+x)*4, target = Array.from(pixels.slice(start,start+3));
  const value = parseInt(hex.slice(1),16), rgb = [value>>16,(value>>8)&255,value&255];
  if (target.every((c,i)=>c===rgb[i])) return;
  const matches = idx => pixels[idx*4]===target[0] && pixels[idx*4+1]===target[1] && pixels[idx*4+2]===target[2];
  const stack = [y*W+x];
  while (stack.length) {
    const index = stack.pop(); if (!matches(index)) continue;
    const offset=index*4; pixels[offset]=rgb[0];pixels[offset+1]=rgb[1];pixels[offset+2]=rgb[2];pixels[offset+3]=255;
    const px=index%W;
    if (px>0 && matches(index-1)) stack.push(index-1);
    if (px<W-1 && matches(index+1)) stack.push(index+1);
    if (index>=W && matches(index-W)) stack.push(index-W);
    if (index<W*(H-1) && matches(index+W)) stack.push(index+W);
  }
  ctx.putImageData(img,0,0);
}
function applyCommit(op) {
  if (committed.has(op.id)) return;
  committed.add(op.id); lastRev = op.rev;
  previews.delete(op.id);
  if (op.kind === "stroke") stroke(ctx,op.points,op.color,op.erase);
  else if (op.kind === "fill") flood(op.point,op.color);
  else if (op.kind === "clear") { ctx.fillStyle="#ffffff";ctx.fillRect(0,0,W,H);previews.clear(); }
  drawOverlay();
}
function drawOverlay() {
  over.clearRect(0,0,W,H);
  for (const p of previews.values()) for (const [,points] of [...p.chunks.entries()].sort((a,b)=>a[0]-b[0])) stroke(over,points,p.color,p.erase);
  if (activeStroke) stroke(over,activeStroke.points,activeStroke.color,activeStroke.erase);
}
function point(event) { const r=overlay.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))]; }
function id() { return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2,12)}`; }
function commit(op) { send({type:"commit",turn:canvasTurn,op}); }
function preview(points) {
  if (channel?.readyState !== "open" || channel.bufferedAmount > 64000 || !activeStroke) return;
  channel.send(JSON.stringify({turn:canvasTurn,op:{id:activeStroke.id,kind:"stroke",points,color:activeStroke.color,erase:activeStroke.erase,seq:strokeSeq++}}));
}
overlay.onpointerdown = event => {
  if (!canDraw() || event.button !== 0 || activeStroke) return;
  event.preventDefault(); overlay.setPointerCapture(event.pointerId);
  if (tool === "fill") { commit({id:id(),kind:"fill",color,point:point(event)});return; }
  activeStroke={id:id(),kind:"stroke",color,erase:tool==="eraser",points:[point(event)],pointer:event.pointerId};
  strokeSeq=0;lastPointTime=performance.now();preview(activeStroke.points);drawOverlay();
};
overlay.onpointermove = event => {
  if (!activeStroke || event.pointerId !== activeStroke.pointer || !canDraw()) return;
  const now=performance.now();if(now-lastPointTime<14)return;lastPointTime=now;
  const previous=activeStroke.points.at(-1), next=point(event);
  if(Math.hypot(next[0]-previous[0],next[1]-previous[1])<.001)return;
  activeStroke.points.push(next);preview([previous,next]);drawOverlay();
  if(activeStroke.points.length>=1400) endStroke(event);
};
function endStroke(event) {
  if (!activeStroke || (event && event.pointerId !== activeStroke.pointer)) return;
  const done=activeStroke;activeStroke=null;
  if (canDraw()) {
    commit(done);
    // Keep local ink visible until its authoritative TCP confirmation arrives.
    previews.set(done.id,{chunks:new Map([[0,done.points]]),color:done.color,erase:done.erase,seen:Date.now()});
  }
  drawOverlay();
}
overlay.onpointerup = overlay.onpointercancel = overlay.onlostpointercapture = endStroke;
palette.forEach(c => {
  const button=document.createElement("button");button.className="color"+(c===color?" selected":"");button.style.background=c;
  button.setAttribute("aria-label",`Use ${c}`);button.title=c;
  button.onclick=()=>{color=c;document.querySelectorAll(".color").forEach(b=>b.classList.toggle("selected",b===button));};
  $("colors").append(button);
});
document.querySelectorAll("[data-tool]").forEach(button=>{button.onclick=()=>{tool=button.dataset.tool;document.querySelectorAll("[data-tool]").forEach(b=>b.classList.toggle("active",b===button));render();};});
$("clearButton").onclick=()=>{if(canDraw())commit({id:id(),kind:"clear",color});};
setInterval(()=>{let changed=false;for(const [key,p]of previews)if(Date.now()-p.seen>6000){previews.delete(key);changed=true;}if(changed)drawOverlay();},2000);
resetCanvas("");
if(session){$("entryMessage").textContent="Returning to your room…";connect({type:"resume",...session});}
