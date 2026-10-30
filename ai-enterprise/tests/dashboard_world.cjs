/* Run with node --test tests/dashboard_world.cjs. No browser or dependencies. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../docs/dashboard/world.js'), 'utf8');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, '../docs/dashboard/status.json'), 'utf8'));
fixture.execution={state:'running',heartbeat_at:new Date().toISOString(),lease_seconds:10};
fixture.meetings=[];
for(const a of fixture.agents)a.work={phase:'thinking',current:'Bearbetar underlaget',next:'Granska nästa rapport',last:a.activity,updated_at:fixture.generated_at};
// Small DOM boundary adapter; assertions exercise the real shipped script.
class Element {
  constructor(tag) {
    this.tagName=tag;this.children=[];this.attributes={};this.dataset={};this.events={};this.textContent='';
    this.style={setProperty(){}};this.classList={toggle(){}};
  }
  get lastChild(){return this.children[this.children.length-1];}
  querySelector(selector){
    for(const c of this.children){if(!(c instanceof Element))continue;
      if(selector.startsWith('.')?(c.className||'').split(' ').includes(selector.slice(1)):c.tagName===selector)return c;
      const nested=c.querySelector(selector);if(nested)return nested;
    }
    return null;
  }
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(k,v){this.attributes[k]=String(v);}
  addEventListener(k,f){this.events[k]=f;}
}
async function setup(data=structuredClone(fixture),reduced=false){
  const nodes=new Map();let payload=data,fail=false;
  const context=vm.createContext({console,Date,Math,Set,Map,Number,String,JSON,Error,AbortSignal,
    document:{addEventListener(){},hidden:false,getElementById(id){if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id);},createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),createTextNode:t=>({textContent:t})},
    matchMedia:()=>({matches:reduced}),requestAnimationFrame(){},setInterval(){},setTimeout(){},clearTimeout(){},
    fetch:async()=>{if(fail)throw Error('offline');return {ok:true,json:async()=>structuredClone(payload)};}
  });
  vm.runInContext(source,context);
  await new Promise(setImmediate);
  return {nodes,run:code=>vm.runInContext(code,context),async update(data){payload=data;await vm.runInContext('refresh()',context);},async fail(){fail=true;await vm.runInContext('refresh()',context);}};
}
test('public snapshot drives all houses, characters and exact reported activities',async()=>{
  const w=await setup();assert.equal(w.nodes.get('population').textContent,fixture.agents.length);
  assert.equal(w.nodes.get('buildings').children.length,fixture.departments.length);
  assert.equal(w.nodes.get('agents').children.length,fixture.agents.length);
  assert.equal(w.run('people.find(p=>p.a.name==="Greta").a.activity'),'gör en prognos');
});
test('selection and continuous following do not control the company',async()=>{
  const w=await setup();w.run('select("res-1");followed=true;select("res-1")');
  const before=w.nodes.get('world').attributes.viewBox;
  w.run('people.find(p=>p.a.id==="res-1").x=700; frame(1000)');
  assert.notEqual(w.nodes.get('world').attributes.viewBox,before);
  assert.equal(w.run('selected'),'res-1');assert.equal(w.run('status.kill_switch'),false);
});
test('walking crosses departments and pause freezes positions',async()=>{
  const w=await setup();w.run('const p=people[0]; p.wait=0; frame(1000);');
  const before=w.run('people[0].y');w.run('frame(1050)');assert.notEqual(w.run('people[0].y'),before);
  w.run('paused=true');const frozen=w.run('people[0].y');w.run('frame(1100)');assert.equal(w.run('people[0].y'),frozen);
});
test('emergency stop, protected mode and inactive states freeze animated agents',async()=>{
  for(const flag of ['kill_switch','protected_mode']){
    const data=structuredClone(fixture);data[flag]=true;const w=await setup(data);
    w.run('people[0].route=[{x:900,y:700}];frame(1000)');const before=w.run('people[0].x');w.run('frame(1050)');assert.equal(w.run('people[0].x'),before);
    assert.equal(w.nodes.get('alert').hidden,false);
  }
  const data=structuredClone(fixture);data.agents[0].state='SUSPENDED';const w=await setup(data);
  w.run('people[0].route=[{x:900,y:700}];frame(1000)');const before=w.run('people[0].x');w.run('frame(1050)');assert.equal(w.run('people[0].x'),before);
});
test('polling preserves selection, position and DOM when snapshots are unchanged',async()=>{
  const w=await setup();w.run('select("res-1");people[0].x=333');const old=w.nodes.get('agents').children[0];
  await w.update(fixture);assert.equal(w.nodes.get('agents').children[0],old);
  const data=structuredClone(fixture);data.agents[0].activity='Ny granskning';await w.update(data);
  assert.equal(w.run('selected'),'res-1');assert.equal(w.run('people[0].x'),333);assert.equal(w.run('people[0].a.activity'),'Ny granskning');
});
test('failed or non-public updates retain last valid snapshot with warning',async()=>{
  const w=await setup();await w.update({...fixture,classification:'internal'});
  assert.equal(w.nodes.get('alert').hidden,false);assert.equal(w.run('status.classification'),'public');
  await w.fail();assert.equal(w.run('people.length'),fixture.agents.length);
});
test('reduced motion defaults to paused, empty snapshots and unknown departments work',async()=>{
  const w=await setup({...fixture,agents:[],departments:[]},true);assert.equal(w.run('paused'),true);assert.equal(w.run('people.length'),0);
  const data=structuredClone(fixture);data.departments.push('new');data.agents[0].department='new';await w.update(data);assert.equal(w.nodes.get('buildings').children.length,7);
});
test('untrusted labels are rendered as text, never parsed as HTML',async()=>{
  const data=structuredClone(fixture);data.agents[0].name='<img src=x onerror=alert(1)>';data.agents[0].activity='<script>bad()</script>';
  const w=await setup(data);assert.equal(w.run('people[0].a.name'),data.agents[0].name);
  assert.equal(w.nodes.get('team').children[0].children[1].children[0].textContent,data.agents[0].name);
});

test('legacy saved snapshots never masquerade as live work',async()=>{
  const data=structuredClone(fixture);delete data.execution;const w=await setup(data);
  assert.equal(w.run('live()'),false);assert.match(w.run('activity(people[0].a)'),/^Senast:/);
  w.run('people[0].route=[{x:900,y:700}];frame(1000)');const before=w.run('people[0].x');w.run('frame(1050)');assert.equal(w.run('people[0].x'),before);
});
test('expired heartbeats freeze movement and replace current work with disconnected state',async()=>{
  const w=await setup();w.run('status.execution.heartbeat_at=new Date(Date.now()-20000).toISOString();updateStatus()');
  assert.equal(w.run('live()'),false);assert.match(w.run('activity(people[0].a)'),/Kontakt/);
  w.run('people[0].route=[{x:900,y:700}];frame(1000)');const before=w.run('people[0].x');w.run('frame(1050)');assert.equal(w.run('people[0].x'),before);
});
test('only actual meeting participants are directed to the plaza',async()=>{
  const data=structuredClone(fixture);data.meetings=[{kind:'assessment',participants:['cfo-1','cro-1']}];
  const w=await setup(data);assert.equal(w.run('inMeeting("cfo-1")'),true);assert.equal(w.run('inMeeting("res-1")'),false);
  assert.equal(w.run('people.filter(p=>inMeeting(p.a.id)).length'),2);
  assert.equal(w.run('people.find(p=>p.a.id==="cfo-1").route.at(-1).y>=380'),true);
  await w.update({...data,meetings:[]});assert.equal(w.run('inMeeting("cfo-1")'),false);
});
test('heartbeat-only updates renew freshness without recreating focused controls',async()=>{
  const w=await setup();const before=w.nodes.get('team').children[0];
  const data=structuredClone(fixture);data.execution.heartbeat_at=new Date(Date.now()+1000).toISOString();await w.update(data);
  assert.equal(w.nodes.get('team').children[0],before);assert.equal(w.run('status.execution.heartbeat_at'),data.execution.heartbeat_at);
});
