const rowCache=new Map();
const queue=new VideoQueue(renderQueue);
function renderQueue(){
  const rows=$('queueRows');if(!queue.items.length){rows.replaceChildren();rowCache.clear();}
  const counts={};for(const item of queue.items)counts[item.status]=(counts[item.status]||0)+1;
  $('queueCount').textContent=`${queue.items.length} videos · ${counts.Done||0} done · ${counts.Review||0} need review · ${counts.Failed||0} failed`;
  $('batchProgress').textContent=queue.running?`${queue.stopRequested?'Stopping after current video. ':''}${counts.Done||0} exported; ${counts.Review||0} held for review. ${queue.items.find(i=>['Analyzing','Exporting'].includes(i.status))?.name??''}`:`${counts.Queued||0} queued · ${counts.Done||0} exported · ${counts.Review||0} need review · ${counts.Failed||0} failed. All files stay local.`;
  for(const item of queue.items){
    const signature=[item.status,item.error,item.exported?.url,item.exported?.duration,item.result?.id,busy,queue.running].join('|');
    const previous=rowCache.get(item.key);if(previous?.signature===signature)continue;
    const row=previous?.row??document.createElement('tr');row.replaceChildren();row.style.borderTop='1px solid #34453b';
    const cell=(text)=>{const td=document.createElement('td');td.style.padding='10px 12px';td.textContent=text;row.append(td);return td};
    cell(item.name).style.overflowWrap='anywhere';
    const status=cell(item.status);status.title=item.error||item.exported?.warning||'';
    if(item.error){const note=document.createElement('div');note.className='note';note.textContent=item.error;status.append(note)}
    cell(item.exported?time(item.exported.duration):(item.result?`Onset ${time(item.result.start)}`:'—'));
    const actions=cell('');
    const open=document.createElement('button');open.textContent=item.result?'Review':'Open';open.disabled=busy||queue.running;open.onclick=()=>openItem(item);actions.append(open);
    if(item.exported){const link=document.createElement('a');link.href=item.exported.url;link.textContent='Download';link.className='link';link.style.marginLeft='6px';link.download=item.file.name.replace(/\.[^.]+$/,'')+'-trimmed'+item.exported.url.match(/\.[^.]+$/)[0];actions.append(link);if(item.exported.warning){const note=document.createElement('div');note.className='note';note.textContent=item.exported.warning;actions.append(note)}}
    if(!previous)rows.append(row);rowCache.set(item.key,{row,signature});
  }
  const blocked=busy||queue.running||!token;
  $('runBatch').disabled=blocked||!counts.Queued;$('retryBatch').disabled=blocked||!counts.Failed;
  $('clearBatch').disabled=blocked||!queue.items.length;$('bundle').disabled=blocked||!counts.Done;
  $('stopBatch').disabled=!queue.running||queue.stopRequested;
  $('addFiles').disabled=busy;$('addFolder').disabled=busy;
}
function addToQueue(files){const count=queue.add(Array.from(files));$('bundleLink').hidden=true;message(`${count} videos added. Unsupported files and duplicate imports were skipped.`);if(!source&&!busy&&!queue.running&&queue.items.length)openItem(queue.items[0]);}
function openItem(item){
  if(busy||queue.running)return;
  select(item.file);selectedItem=item;
  if(item.result)showAnalysis(item.result,item.bounds);
  if(item.exported)showExport(item.exported);
  lock(false);renderQueue();
}
$('addFiles').onclick=()=>$('file').click();$('addFolder').onclick=()=>$('folder').click();
$('folder').onchange=e=>{addToQueue(e.target.files);e.target.value=''};
$('runBatch').onclick=async()=>{
  if(busy||queue.running||!token)return;
  $('bundleLink').hidden=true;v.pause();lock(true);
  try{await queue.run(settings(),{analyze:analyzeFile,export:(id,bounds)=>post('/api/export',JSON.stringify({id,...bounds}),{'Content-Type':'application/json'})});}
  finally{lock(false);renderQueue();message('Batch paused or finished. Review flagged videos, or download completed clips together.');}
};
$('stopBatch').onclick=()=>queue.stop();$('retryBatch').onclick=()=>queue.retry();
$('bundle').onclick=async()=>{
  if(busy||queue.running)return;lock(true);$('bundleLink').hidden=true;renderQueue();
  try{const r=await post('/api/bundle',JSON.stringify({items:queue.items.map(item=>({id:item.exported?item.result.id:null,name:item.name,status:item.status,message:item.error}))}),{'Content-Type':'application/json'});$('bundleLink').href=r.url;$('bundleLink').textContent=`Download ZIP · ${r.count} verified clips ↓`;$('bundleLink').hidden=false;message('ZIP ready. It includes named clips, individual reports, and a batch summary.');}
  catch(e){message(e.message,true)}finally{lock(false);renderQueue()}
};
$('clearBatch').onclick=async()=>{
  if(busy||queue.running)return;lock(true);renderQueue();
  try{await post('/api/discard',JSON.stringify({ids:queue.items.filter(i=>i.result).map(i=>i.result.id),clearBundles:true}),{'Content-Type':'application/json'});queue.items=[];$('filename').textContent='Source video';$('meta').textContent='1–10 seconds';$('graphstate').textContent='Awaiting analysis';['set','start','exit'].forEach(id=>$(id).textContent='—');if($('exportVideo').src.startsWith('blob:'))URL.revokeObjectURL($('exportVideo').src);$('exportVideo').removeAttribute('src');source=null;result=null;selectedItem=null;v.pause();v.removeAttribute('src');v.load();v.hidden=true;$('empty').hidden=false;if(objectURL)URL.revokeObjectURL(objectURL);objectURL=null;$('downloads').hidden=true;$('bundleLink').hidden=true;message('Queue and its local temporary files cleared. Downloaded copies are retained.');draw();}
  catch(e){message(e.message,true)}finally{lock(false);renderQueue()}
};
renderQueue();
