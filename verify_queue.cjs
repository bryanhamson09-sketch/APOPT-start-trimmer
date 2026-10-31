const assert=require('node:assert/strict');
const {VideoQueue}=require('./queue.js');
const file=(name,path='')=>({name,webkitRelativePath:path,size:100,lastModified:1});
async function main(){
  let active=0,maxActive=0,analyzed=[],exports=[];
  const queue=new VideoQueue();
  assert.equal(queue.add([file('start.mov','one/start.mov'),file('start.mov','two/start.mov'),file('broken.mp4'),file('quiet.mp4'),file('notes.txt')]),4);
  assert.equal(queue.add([file('start.mov','one/start.mov')]),0);
  const ops={analyze:async(f,settings)=>{active++;maxActive=Math.max(maxActive,active);analyzed.push(f.webkitRelativePath||f.name);await Promise.resolve();active--;if(f.name==='broken.mp4')throw Error('Bad codec');return {id:analyzed.length,inTime:1,outTime:3,start:2,confidence:f.name==='quiet.mp4'?'Review required':'Candidate found',onsetDetection:f.name==='quiet.mp4'?null:{},reason:'Check onset'}},export:async(id,bounds)=>{exports.push(id);return {duration:bounds.end-bounds.start,url:'/clip/'+id}}};
  await queue.run({lead:'.75'},ops);
  assert.equal(maxActive,1);assert.deepEqual(queue.items.map(i=>i.status),['Done','Done','Failed','Review']);
  assert.equal(exports.length,2);assert.equal(analyzed.length,4);
  queue.retry();assert.equal(queue.items[2].status,'Queued');assert.equal(queue.items[3].status,'Review');
  const paused=new VideoQueue();paused.add([file('a.mov'),file('b.mov'),file('c.mov')]);
  const pauseOps={...ops,export:async(id,bounds)=>{paused.stop();return {duration:2}}};
  await paused.run({},pauseOps);assert.deepEqual(paused.items.map(i=>i.status),['Done','Queued','Queued']);
  await paused.run({},ops);assert.ok(paused.items.every(i=>i.status==='Done'));
  // Resuming a failed export reuses its analyzed source and bounds.
  const retry=new VideoQueue();retry.add([file('retry.mov')]);let calls=0;
  const retryOps={analyze:async()=>{calls++;return {id:'retry',inTime:1,outTime:3,confidence:'Candidate found',onsetDetection:{}}},export:async()=>{throw Error('Export failed')}};
  await retry.run({},retryOps);retry.retry();await retry.run({}, {...retryOps,export:async()=>({duration:2})});assert.equal(calls,1);assert.equal(retry.items[0].status,'Done');
  console.log('Queue checks passed: serial processing, folders, duplicate names, failures, review hold, stop/resume, export retry.');
}
main().catch(e=>{console.error(e);process.exitCode=1});
