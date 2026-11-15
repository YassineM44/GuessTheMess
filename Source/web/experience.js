/* Original synthesized game sounds. Offline, no audio downloads or permissions. */
"use strict";
window.MessExperience = (() => {
  const get = (key, fallback) => { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } };
  const save = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
  let muted = get("gtm-muted", "false") === "true", context, master;
  let avatar = get("gtm-avatar", "👾"), lastKey = 0, tickKey = "", previous, feedbackTimer;
  const avatars = ["👾", "🐸", "🦊", "🐼", "🐙", "👻", "🤖", "🌵"];
  const avatarNames = ["Alien", "Frog", "Fox", "Panda", "Octopus", "Ghost", "Robot", "Cactus"];
  if (!avatars.includes(avatar)) avatar = avatars[0];
  function unlock() {
    try {
      if (!context) { context = new (window.AudioContext || window.webkitAudioContext)(); master=context.createGain();master.gain.value=muted?0:.25;master.connect(context.destination); }
      if (context.state === "suspended") context.resume().catch(()=>{});
    } catch { /* The game remains usable when audio is unavailable. */ }
  }
  document.addEventListener("pointerdown", unlock, {capture:true});
  document.addEventListener("keydown", unlock, {capture:true});
  function tone(freq, at, duration, type="sine", volume=.35, end=freq) {
    const oscillator=context.createOscillator(), gain=context.createGain();
    oscillator.type=type;oscillator.frequency.setValueAtTime(freq,at);
    oscillator.frequency.exponentialRampToValueAtTime(Math.max(1,end),at+duration);
    gain.gain.setValueAtTime(.0001,at);gain.gain.exponentialRampToValueAtTime(volume,at+.005);
    gain.gain.exponentialRampToValueAtTime(.0001,at+duration);
    oscillator.connect(gain);gain.connect(master);oscillator.start(at);oscillator.stop(at+duration+.01);
    oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};
  }
  function play(kind) {
    if (muted || !context || context.state!=="running" || document.hidden) return;
    const t=context.currentTime;
    if(kind==="type") tone(500+Math.random()*180,t,.025,"triangle",.15,150);
    else if(kind==="wrong") {tone(190,t,.1,"triangle",.45,115);tone(130,t+.08,.14,"triangle",.3,85);}
    else if(kind==="close") {tone(440,t,.1,"sine",.4);tone(554,t+.11,.15,"sine",.4);}
    else if(kind==="correct") [523,659,784,1047].forEach((f,i)=>tone(f,t+i*.075,.21,"triangle",.45));
    else if(kind==="tick") tone(1050,t,.035,"sine",.19,600);
    else if(kind==="hurry") {tone(1320,t,.04,"sine",.28,800);}
    else if(kind==="round") [330,440,660].forEach((f,i)=>tone(f,t+i*.08,.19,"triangle",.35));
    else if(kind==="finish") [523,659,784,659,1047].forEach((f,i)=>tone(f,t+i*.13,.3,"triangle",.45));
    else if(kind==="pop") tone(700,t,.07,"sine",.2,1000);
    else return;
    document.dispatchEvent(new CustomEvent("gtm:sound", {detail:kind}));
  }
  function feedback(kind, text) {
    const element=document.getElementById("guessFeedback");
    element.className=`guess-feedback ${kind}`;element.textContent=text || ({wrong:"✕ Not that one. Go again!",close:"≈ So close! Check the spelling and spaces.",correct:"★ Nailed it! Keep the answer secret."}[kind] || "");
    clearTimeout(feedbackTimer);feedbackTimer=setTimeout(()=>{element.textContent="";element.className="guess-feedback";},4000);
    play(kind);
    if(kind==="correct") celebrate();
  }
  function celebrate() {
    if(matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const layer=document.getElementById("celebration");
    layer.replaceChildren();
    for(let i=0;i<32;i++) {
      const piece=document.createElement("i");piece.style.setProperty("--x",`${Math.random()*100}vw`);
      piece.style.setProperty("--spin",`${Math.random()*900-450}deg`);
      piece.style.setProperty("--delay",`${Math.random()*.3}s`);
      piece.style.background=["#b49aff","#d9f56b","#ff8ea3","#65d5cf","#ffc56b"][i%5];
      layer.append(piece);
    }
    setTimeout(()=>layer.replaceChildren(),2400);
  }
  function update(s) {
    const active=s.phase==="drawing", me=s.players.find(p=>p.id===s.you);
    const ticking=active && !s.paused.length && !me?.guessed && s.remaining>0 && s.remaining<=20;
    document.body.classList.toggle("time-pressure",ticking);
    document.body.classList.toggle("final-seconds",ticking && s.remaining<=8);
    document.getElementById("timeFill").style.width=`${active?s.remaining/80*100:0}%`;
    if(previous && s.turn!==previous.turn && active) { play("round");feedback("",""); }
    if(previous && s.phase==="finished" && previous.phase!=="finished") {play("finish");celebrate();}
    if(ticking) {
      const key=`${s.turn}:${s.remaining<=8?"fast":"slow"}:${Math.ceil(s.remaining*(s.remaining<=8?2:1))}`;
      if(key!==tickKey) {play(s.remaining<=8?"hurry":"tick");tickKey=key;}
    }
    previous=s;
  }
  function themeUI() {
    const dark=document.documentElement.dataset.theme==="dark", b=document.getElementById("themeButton");
    b.textContent=dark?"☀":"☾";b.setAttribute("aria-pressed",String(dark));
    b.setAttribute("aria-label",`Switch to ${dark?"light":"dark"} mode`);b.title=b.getAttribute("aria-label");
    document.querySelector('meta[name="theme-color"]').content=dark?"#171520":"#f4f0e8";
  }
  function soundUI() {
    const b=document.getElementById("soundButton");b.textContent=muted?"♪̸":"♫";
    b.setAttribute("aria-pressed",String(muted));b.setAttribute("aria-label",muted?"Unmute sound":"Mute sound");b.title=b.getAttribute("aria-label");
  }
  document.getElementById("themeButton").onclick=()=>{
    const theme=document.documentElement.dataset.theme==="dark"?"light":"dark";
    document.documentElement.dataset.theme=theme;save("gtm-theme",theme);themeUI();play("pop");
  };
  document.getElementById("soundButton").onclick=()=>{
    unlock();muted=!muted;save("gtm-muted",String(muted));
    if(master) master.gain.setValueAtTime(muted?0:.25,context.currentTime);
    soundUI();if(!muted)play("pop");
  };
  const picker=document.getElementById("avatarPicker");
  avatars.forEach((a,i)=>{
    const b=document.createElement("button");b.type="button";b.textContent=a;b.title=avatarNames[i];
    b.setAttribute("aria-label",`Play as ${avatarNames[i]}`);b.setAttribute("aria-pressed",String(a===avatar));
    b.onclick=()=>{avatar=a;save("gtm-avatar",a);for(const x of picker.children)x.setAttribute("aria-pressed",String(x===b));play("pop");};picker.append(b);
  });
  document.getElementById("chatInput").addEventListener("input",e=>{
    if(e.isComposing || !e.target.value || performance.now()-lastKey<65) return;
    lastKey=performance.now();play("type");
  });
  themeUI();soundUI();
  return {play,feedback,update,celebrate,get avatar(){return avatar;},get audioState(){return context?.state || "locked";},get muted(){return muted;}};
})();
