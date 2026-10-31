/* Execute the real page scripts together, with a small DOM and local API fixture. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const ids=new Set([...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]));
const context2d=new Proxy({}, {get:(o,k)=>o[k]??(()=>{}),set:(o,k,v)=>(o[k]=v,true)});
class Element{
  constructor(id=''){this.id=id;this.style={};this.classList={toggle(){},add(){},remove(){}};this.value='0';this.src='';this.href='';this.children=[];this.currentTime=0;this.duration=6;this.width=1000;this.height=160;this.checked=true;}
  append(...items){this.children.push(...items)} replaceChildren(){this.children=[]}
  getContext(){return context2d} pause(){} load(){} click(){} play(){return Promise.resolve()}
  getAttribute(name){return this[name]||null} removeAttribute(name){this[name]=''}
}
const elements=Object.fromEntries([...ids].map(id=>[id,new Element(id)]));
elements.lead.value='.75';elements.signal.value='motion';
let count=0,requests=[];
const sandbox={console,document:{getElementById:id=>{assert.ok(ids.has(id),'Missing HTML control '+id);return elements[id]},createElement:()=>new Element()},URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}},fetch:async(url,options={})=>{
  requests.push(url);let data;
  if(url==='/api/status')data={ready:true,token:'local-fixture'};
  else if(url==='/api/analyze'){const quiet=options.body.name==='quiet.mov';data={id:'job'+(++count),inTime:3.25,outTime:5.2,start:4,set:2,exit:5.2,duration:6,width:320,height:180,frames:720,fps:'120/1',times:[0,1,2,3,4,5,6],scores:[0,0,0,0,1,0,0],keys:[0,1,2,3,4,5],confidence:quiet?'Review required':'Candidate found',onsetDetection:quiet?null:{},reason:'Fixture'};}
  else if(url==='/api/export')data={url:'/download/test/clip.mov',report:'/download/test/edit-report.json',duration:2.2,sourceDuration:6,frames:264};
  else if(url==='/api/bundle')data={url:'/bundle/test',count:1};
  else data={ok:true};
  return {ok:true,json:async()=>data,blob:async()=>({})};
}};
async function main(){
  vm.createContext(sandbox);vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],sandbox);
  vm.runInContext(fs.readFileSync('queue.js','utf8'),sandbox);vm.runInContext(fs.readFileSync('batch.js','utf8'),sandbox);
  await new Promise(setImmediate);
  assert.equal(elements.runBatch.disabled,true);
  const file=name=>({name,size:100,lastModified:1});
  elements.file.onchange({target:{files:[file('start.mov'),file('quiet.mov')],value:'selected'}});
  assert.equal(vm.runInContext('queue.items.length',sandbox),2);assert.equal(elements.runBatch.disabled,false);
  await elements.runBatch.onclick();
  assert.deepEqual(Array.from(vm.runInContext('queue.items.map(i=>i.status)',sandbox)),['Done','Review']);
  assert.equal(requests.filter(r=>r==='/api/export').length,1);
  vm.runInContext('openItem(queue.items[0])',sandbox);
  assert.equal(elements.in.value,'3.250000');assert.equal(elements.out.value,'5.200000');
  elements.video.onloadedmetadata();assert.equal(elements.out.value,'5.200000');
  elements.signal.value='curvature';elements.signal.onchange();
  await elements.bundle.onclick();assert.equal(elements.bundleLink.hidden,false);
  await elements.clearBatch.onclick();assert.equal(vm.runInContext('queue.items.length',sandbox),0);
  assert.equal(elements.runBatch.disabled,true);
  console.log('Page integration passed: file import, API queue, review hold, precise bounds, metadata load, graph switch, ZIP and clear.');
}
main().catch(e=>{console.error(e);process.exitCode=1});
