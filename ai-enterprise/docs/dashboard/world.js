"use strict";
// The world is an illustration of public snapshots, never a command interface.
const $ = id => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const DEPARTMENTS = {
  executive: ["Ledningshuset", "Ledning & samarbete", "#cd9d69", "#f3dbb0", "★"],
  research: ["Idélabbet", "Forskning & nya idéer", "#789eaa", "#d7e9e4", "✦"],
  finance: ["Skattkammaren", "Ekonomi & budget", "#b9a15e", "#f1e5bc", "◈"],
  risk: ["Vakttornet", "Risk & trygghet", "#b18077", "#f0d7cb", "⚑"],
  compliance: ["Regelhuset", "Regler & ansvar", "#8e88af", "#e4dfef", "§"],
  audit: ["Granskarstugan", "Revision & kontroll", "#73a18d", "#dce8cf", "✓"]
};
const STATES = {ACTIVE:"Aktiv", TESTING:"Testas", CREATED:"Skapad", PROPOSED:"Föreslagen", PROBATION:"Prövotid", SUSPENDED:"Pausad", RETIRED:"Avslutad"};
const MOBILE = new Set(["ACTIVE", "TESTING", "PROBATION"]);
let status = null, people = [], houses = [], selected = null, followed = false;
let paused = matchMedia("(prefers-reduced-motion: reduce)").matches;
let lastFrame = 0, elapsed = 0, fetching = false, error = "", shownBubbles = true, lastSnapshot = "";
function svg(tag, attrs = {}, text) {
  const node = document.createElementNS(NS, tag);
  for (const [k,v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}
function el(tag, cls, text) { const n = document.createElement(tag); if(cls)n.className=cls; if(text !== undefined)n.textContent=text; return n; }
function hash(s) { let h=0; for(const c of s)h=(h*31+c.charCodeAt(0))>>>0; return h; }
function dep(id) { return DEPARTMENTS[id] || [id, "Avdelning", "#799e88", "#deead2", "⌂"]; }
function money(n,c="SIM") { return Number.isFinite(n) ? (n/100).toLocaleString("sv-SE",{minimumFractionDigits:2,maximumFractionDigits:2})+" "+c : "–"; }
function tree(x,y,s=1) {
  const g=svg("g",{transform:`translate(${x} ${y}) scale(${s})`});
  g.append(svg("ellipse",{cx:3,cy:17,rx:21,ry:8,fill:"#719a60",opacity:".22"}),svg("path",{d:"M-4 0h8v21h-8Z",fill:"#977953"}),svg("circle",{cx:-10,cy:-9,r:18,fill:"#6d9b60"}),svg("circle",{cx:9,cy:-15,r:22,fill:"#7aa968"}),svg("circle",{cx:-2,cy:-27,r:17,fill:"#8ab875"}));
  return g;
}
function buildLandscape() {
  const land=$('landscape');
  [[45,90,1.2],[81,53,.8],[915,186,1.1],[958,239,.8],[42,330,1],[954,555,1.3],[899,655,1],[355,694,.8],[659,685,1.1],[49,483,.85]].forEach(v=>land.append(tree(...v)));
  for(let i=0;i<55;i++){const x=30+hash("flower"+i)%930,y=60+hash("pos"+i)%620;land.append(svg("path",{d:`M${x} ${y}v5`,stroke:"#739453","stroke-width":2}),svg("circle",{cx:x,cy:y,r:2.5,fill:i%2?"#f9efb8":"#f4d2bd"}));}
}
function buildHouses(departments) {
  $('roads').replaceChildren(); $('buildings').replaceChildren(); $('plaza').replaceChildren();
  const order=["executive","research","finance","audit","compliance","risk"];
  const names=[...new Set(departments)].sort((a,b)=>order.indexOf(a)-order.indexOf(b));
  const cols=Math.max(3,Math.ceil(names.length/2)), gap=790/(cols-1);
  houses=names.map((id,i)=>({id,x:105+(i%cols)*gap,y:i<cols?210:555,top:i<cols}));
  for(const h of houses){
    const doorY=h.top?h.y+35:h.y-78;
    const road=svg("path",{d:`M${h.x} ${doorY}V370H500`,fill:"none",stroke:"#e9dbb3","stroke-width":39,"stroke-linejoin":"round","stroke-linecap":"round"});$('roads').append(road);
    $('roads').append(svg("path",{d:`M${h.x-12} ${h.top?300:443}h24`,stroke:"#d4c298","stroke-width":2}));
    const [name,sub,roof,wall,icon]=dep(h.id);
    const g=svg("g",{class:"house",transform:`translate(${h.x} ${h.y})`,role:"button",tabindex:0,"aria-label":`${name}: visa avdelningens kollegor`});
    g.append(svg("ellipse",{cx:0,cy:28,rx:86,ry:23,fill:"#7c9b61",opacity:".22"}));
    const b=svg("g",{class:"house-body",filter:"url(#shadow)"});
    b.append(svg("rect",{x:-70,y:-71,width:140,height:93,rx:6,fill:wall,stroke:"#698065","stroke-width":2}),svg("path",{d:"M-82-68L-61-124H57L82-68Z",fill:roof,stroke:"#5f735c","stroke-width":2,"stroke-linejoin":"round"}),svg("path",{d:"M-64-111H61M-71-95H68M-76-81H75",fill:"none",stroke:"#ffffff",opacity:".18","stroke-width":3}),svg("rect",{x:37,y:-147,width:16,height:38,rx:2,fill:wall,stroke:"#71805e","stroke-width":2}));
    [-44,36].forEach(x=>{b.append(svg("rect",{x,y:-52,width:24,height:29,rx:4,fill:"#88bac0",stroke:"#fdf4d8","stroke-width":5}),svg("path",{d:`M${x+12}-52v29m-12-14h24`,stroke:"#fdf4d8","stroke-width":2}));});
    b.append(svg("rect",{x:-13,y:-27,width:26,height:49,rx:12,fill:"#8b7658",stroke:"#6d7555","stroke-width":2}),svg("circle",{cx:6,cy:4,r:2,fill:"#ead596"}),svg("rect",{x:-22,y:22,width:44,height:8,rx:3,fill:"#e5d3a8"}),svg("circle",{cx:0,cy:-88,r:15,fill:"#fff3d6",stroke:"#6c795b","stroke-width":2}),svg("text",{x:0,y:-82,"text-anchor":"middle",fill:roof,"font-size":19,"font-weight":800},icon));
    const labelY=h.top?-182:44;
    g.append(b,svg("rect",{x:-91,y:labelY,width:182,height:45,rx:10,fill:"#faf8e4",stroke:"#9caf87","stroke-width":1}),svg("text",{y:labelY+19,"text-anchor":"middle",class:"world-label"},name),svg("text",{y:labelY+34,"text-anchor":"middle",class:"world-caption"},sub));
    function pick(){const p=people.find(p=>p.a.department===h.id);if(p)select(p.a.id);}
    g.addEventListener("click",pick);g.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();pick();}});$('buildings').append(g);
  }
  const plaza=$('plaza');
  plaza.append(svg("ellipse",{cx:500,cy:370,rx:81,ry:49,fill:"#e3d2a7",stroke:"#f9eccb","stroke-width":5}),svg("ellipse",{cx:500,cy:359,rx:31,ry:16,fill:"#86b8bd",stroke:"#f4e6c6","stroke-width":6}),svg("path",{d:"M500 359v-26",stroke:"#eee8cc","stroke-width":9,"stroke-linecap":"round"}),svg("ellipse",{cx:500,cy:329,rx:17,ry:7,fill:"#aed8d4",stroke:"#eee8cc","stroke-width":4}),svg("text",{x:500,y:416,"text-anchor":"middle",class:"world-label"},"Mötestorget"));
  [-1,1].forEach(n=>{plaza.append(svg("rect",{x:500+n*111-23,y:365,width:46,height:10,rx:3,fill:"#a88257",stroke:"#826e4e","stroke-width":2}),svg("path",{d:`M${500+n*111-17} 375v9m34-9v9`,stroke:"#826e4e","stroke-width":4}));});
}
function makePerson(a,i) {
  const seed=hash(a.id),h=houses.find(h=>h.id===a.department)||houses[0]||{x:500,y:300,top:true};
  const p={a,x:h.x-20+(i%3)*20,y:h.top?325:405,route:[],wait:i*1.2,seed,node:null,bob:0};
  const color=dep(a.department)[2],skin=["#edc297","#c98e65","#875f49","#f3d2aa"][seed%4];
  const g=svg("g",{class:"agent",role:"button",tabindex:0,"aria-label":`${a.name}: ${a.activity}`});
  g.append(svg("ellipse",{class:"selection",cx:0,cy:1,rx:20,ry:9}),svg("ellipse",{cx:1,cy:3,rx:12,ry:5,fill:"#355c38",opacity:".2"}));
  const body=svg("g",{class:"body"});
  body.append(svg("path",{d:"M-5-3v7m10-7v7",stroke:"#4b594b","stroke-width":5,"stroke-linecap":"round"}),svg("rect",{x:-9,y:-21,width:18,height:20,rx:7,fill:color,stroke:"#596e56","stroke-width":1.5}),svg("path",{d:"M-11-17l-3 9m25-9 3 9",stroke:skin,"stroke-width":4,"stroke-linecap":"round"}),svg("circle",{cx:0,cy:-31,r:11,fill:skin,stroke:"#6d624e","stroke-width":1}),svg("path",{d:"M-11-32q-1-16 14-11q11 2 8 15l-6-9-7 2-9-1Z",fill:["#5d4c3d","#ac8152","#424b44"][seed%3]}),svg("path",{d:"M-4-30v2m8-2v2",stroke:"#3d483d","stroke-width":2,"stroke-linecap":"round"}),svg("path",{d:"M-3-24q3 2 6 0",fill:"none",stroke:"#8c614c","stroke-width":1.2}));
  g.append(body,svg("text",{y:21,"text-anchor":"middle",class:"agent-name"},a.name));
  const bubble=svg("g",{class:"bubble",transform:"translate(0 -62)"});
  const txt=String(a.activity||"Ingen aktivitet rapporterad"),short=txt.length>31?txt.slice(0,28)+"…":txt,w=Math.max(70,short.length*6.1+18);
  bubble.append(svg("path",{d:"M-5 10l5 7 5-7",fill:"#fffdf0",stroke:"#8b9c78","stroke-width":1}),svg("rect",{x:-w/2,y:-11,width:w,height:25,rx:8,fill:"#fffdf0",stroke:"#8b9c78","stroke-width":1}),svg("text",{y:6,"text-anchor":"middle"},short));
  g.append(bubble);const social=svg("text",{x:18,y:-30,class:"social"},"♡");social.style.display="none";g.append(social);p.social=social;p.node=g;p.body=body;p.bubble=bubble;
  g.addEventListener("click",()=>select(a.id));g.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();select(a.id);}});
  $('agents').append(g); return p;
}
function chooseRoute(p) {
  if(!houses.length)return;
  const h=houses[(p.seed+Math.floor(elapsed/10))%houses.length];
  if(status.meeting){p.route=[{x:p.x,y:370},{x:460+p.seed%80,y:380+p.seed%30}];p.wait=4;return;}
  // All interdepartmental walks use the town's east/west road and vertical lanes.
  p.route=[{x:p.x,y:370},{x:h.x,y:370},{x:h.x,y:h.top?325:405}];p.wait=2+p.seed%4;
}
function active(p) { return MOBILE.has(p.a.state)&&!status.kill_switch&&!status.protected_mode; }
function frame(now) {
  const dt=Math.min((now-lastFrame)/1000||0,.05);lastFrame=now;
  const running=status&&!paused&&!status.kill_switch&&!status.protected_mode;
  if(running)elapsed+=dt;
  for(const p of people){let walking=false;
    if(running&&active(p)){
      if(p.route.length){const t=p.route[0],dx=t.x-p.x,dy=t.y-p.y,d=Math.hypot(dx,dy),step=25*dt;if(d<=step){p.x=t.x;p.y=t.y;p.route.shift();}else{p.x+=dx/d*step;p.y+=dy/d*step;walking=true;}}
      else {p.wait-=dt;if(p.wait<=0)chooseRoute(p);}
    }
    p.bob=walking?Math.sin(elapsed*12+p.seed)*1.8:0;
    p.node.setAttribute("transform",`translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`);
    p.body.setAttribute("transform",`translate(0 ${p.bob.toFixed(2)})`);
    const near=running&&active(p)&&people.some(q=>q!==p&&active(q)&&Math.hypot(q.x-p.x,q.y-p.y)<46);
    p.social.style.display=near?"block":"none";
  }
  if(followed){const p=people.find(p=>p.a.id===selected);if(p)camera(p);}
  // Separate nearby speech bubbles without removing anyone's activity.
  for(let i=0;i<people.length;i++){const p=people[i];let lane=0;
    for(let j=0;j<i;j++){const q=people[j];if(Math.abs(q.x-p.x)<145&&Math.abs(q.y-p.y)<45)lane++;}
    p.bubble.setAttribute("transform",`translate(0 ${-62-lane*29})`);
  }
  requestAnimationFrame(frame);
}
function avatar(p,large=false){const a=el("span","avatar"+(large?" large":""),"♟");a.style.setProperty("--avatar-bg",dep(p.a.department)[3]);a.style.color=dep(p.a.department)[2];return a;}
function camera(p) {
  $('world').setAttribute("viewBox",`${Math.max(0,Math.min(580,p.x-210))} ${Math.max(0,Math.min(430,p.y-155))} 420 310`);
}
function select(id) {
  selected=id;const p=people.find(p=>p.a.id===id);if(!p)return;
  for(const q of people)q.node.classList.toggle("chosen",q===p);
  for(const b of $('team').children){const chosen=b.dataset.id===id;b.classList.toggle("selected",chosen);b.setAttribute("aria-pressed",String(chosen));}
  const profile=$('profile');profile.replaceChildren();const heading=el("div","profile-heading"),text=el("div");text.append(el("h2","",p.a.name),el("small","",dep(p.a.department)[1]));heading.append(avatar(p,true),text);
  const report=el("div","reported");report.append(el("small","","SENAST RAPPORTERAD AKTIVITET"),document.createTextNode(p.a.activity||"Ingen aktivitet rapporterad"));
  const follow=el("button","full",followed?"◎ Sluta följa":"◎ Följ på kartan");follow.setAttribute("aria-pressed",String(followed));follow.addEventListener("click",()=>{followed=!followed;select(id);});
  profile.append(heading,el("span","state-label",(active(p)?"● ":"○ ")+(STATES[p.a.state]||p.a.state)),report,el("p","profile-detail","Hemmabas: "+dep(p.a.department)[0]),el("p","profile-detail","Roll: "+p.a.role),follow);
  if(followed)camera(p);
  else $('world').setAttribute("viewBox","0 0 1000 740");
}
function render(data) {
  const old=new Map(people.map(p=>[p.a.id,p]));status=data;
  buildHouses(data.departments);$('agents').replaceChildren();people=data.agents.map(makePerson);
  for(const p of people){const prev=old.get(p.a.id);if(prev&&prev.a.department===p.a.department){p.x=prev.x;p.y=prev.y;p.route=prev.route;p.wait=prev.wait;}}
  $('population').textContent=data.agents.length;$('departments').textContent=data.departments.length;
  $('capital').textContent=money(data.scoreboard.sim?.capital_minor,data.scoreboard.sim?.currency||"SIM");$('result').textContent=money(data.scoreboard.sim?.result_minor,data.scoreboard.sim?.currency||"SIM");
  $('real').textContent=data.scoreboard.real?"Riktiga pengar · Kapital: "+money(data.scoreboard.real.capital_minor,data.scoreboard.real.currency):"Ingen pilotdata för riktiga pengar ännu.";
  $('team-count').textContent=data.agents.length;$('team').replaceChildren();$('activities').replaceChildren();
  for(const p of people){const b=el("button","agent-button");b.dataset.id=p.a.id;const info=el("span");info.append(el("span","name",p.a.name),el("span","activity",p.a.activity||"Ingen aktivitet rapporterad"));b.append(avatar(p),info,el("span","dot"+(active(p)?"":" inactive")));b.addEventListener("click",()=>select(p.a.id));$('team').append(b);const item=el("li");item.append(el("b","",p.a.name+" · "+dep(p.a.department)[0]),document.createTextNode(p.a.activity||"Ingen aktivitet rapporterad"));$('activities').append(item);}
  if(!people.length){$('profile').replaceChildren(el("p","","Inga kollegor i senaste statusen."));$('activities').replaceChildren(el("li","","Inga aktiviteter rapporterade."));}
  else select(people.some(p=>p.a.id===selected)?selected:people[0].a.id);
  updateStatus();
}
function updateStatus(){
  if(!status)return;
  const age=Date.now()-Date.parse(status.generated_at),stale=!Number.isFinite(age)||age>24*3600*1000;
  $('connection').textContent=error?"Kunde inte hämta ny status":stale?"Äldre ögonblicksbild":"Visar senaste ögonblicksbild";
  const date=new Date(status.generated_at);$('time').textContent="Systemdata: "+(Number.isFinite(date.getTime())?date.toLocaleString("sv-SE"):"okänt datum");
  const alerts=[];if(status.kill_switch)alerts.push("NÖDSTOPP — alla agenters rörelser är stoppade.");if(status.protected_mode)alerts.push("SKYDDAT LÄGE — världen står stilla.");if(error)alerts.push("Status kunde inte uppdateras. Senast hämtade data visas.");
  $('alert').hidden=!alerts.length;$('alert').textContent=alerts.join(" ");
  $('world-state').textContent=status.kill_switch?"Nödstopp":status.protected_mode?"Skyddat läge":paused?"Animation pausad":status.meeting?"Möte rapporterat · animerad samling på torget":"Animerad visning av sparad status";
}
function validate(data){
  if(!data||data.classification!=="public"||!Array.isArray(data.agents)||!Array.isArray(data.departments)||!data.scoreboard)throw Error("Ogiltig offentlig status");
  if(!data.departments.every(d=>typeof d==="string")||!data.agents.every(a=>a&&["id","name","department","role","state","activity"].every(k=>typeof a[k]==="string")))throw Error("Ogiltiga agentdata");
  return data;
}
async function refresh(){if(fetching)return;fetching=true;$('refresh').disabled=true;
  try{const response=await fetch("status.json",{cache:"no-store",signal:AbortSignal.timeout(10000)});if(!response.ok)throw Error("HTTP "+response.status);const data=validate(await response.json());error="";const snapshot=JSON.stringify(data);if(snapshot!==lastSnapshot){render(data);lastSnapshot=snapshot;}else updateStatus();}
  catch(e){error=String(e);if(status)updateStatus();else{$('connection').textContent="Kunde inte läsa status";$('alert').hidden=false;$('alert').textContent="Statusdata kunde inte läsas. Försök med Uppdatera data.";}}
  finally{fetching=false;$('refresh').disabled=false;}
}
$('refresh').addEventListener("click",refresh);
function updatePause(){$('pause').setAttribute("aria-pressed",String(paused));$('pause').textContent=paused?"▶ Spela":"Ⅱ Pausa";updateStatus();}
$('pause').addEventListener("click",()=>{paused=!paused;updatePause();});
$('labels').addEventListener("click",()=>{shownBubbles=!shownBubbles;$('world').classList.toggle("hide-bubbles",!shownBubbles);$('labels').setAttribute("aria-pressed",String(shownBubbles));});
buildLandscape();updatePause();refresh();requestAnimationFrame(frame);setInterval(refresh,15000);
