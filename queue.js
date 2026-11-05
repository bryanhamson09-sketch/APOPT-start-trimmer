/* Serial queue: at most one source is transferred or processed at a time. */
class VideoQueue {
  constructor(update=()=>{}) { this.items=[];this.running=false;this.stopRequested=false;this.update=update;this.sequence=0; }
  add(files) {
    let added=0;
    const signatures=new Set(this.items.map(i=>i.signature));
    for(const file of files){
      if(!/\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(file.name))continue;
      const signature=[file.webkitRelativePath||file.name,file.size,file.lastModified].join('|');
      if(signatures.has(signature))continue;
      signatures.add(signature);
      this.items.push({key:++this.sequence,signature,file,name:file.webkitRelativePath||file.name,
        status:file.size>512*1024*1024?'Failed':'Queued',error:file.size>512*1024*1024?'Exceeds 512 MB.':'',
        result:null,bounds:null,exported:null});added++;
    }
    this.update();return added;
  }
  stop(){this.stopRequested=true;this.update();}
  retry(){if(this.running)return;for(const item of this.items)if(item.status==='Failed'){item.status='Queued';item.error='';}this.update();}
  async run(settings,ops){
    if(this.running)return;
    this.running=true;this.stopRequested=false;const saved={...settings};this.update();
    try{
      for(const item of this.items){
        if(this.stopRequested)break;
        if(item.status!=='Queued')continue;
        try{
          if(item.file.size>512*1024*1024)throw Error('Exceeds 512 MB.');
          if(!item.result){item.status='Analyzing';this.update();item.result=await ops.analyze(item.file,saved);}
          item.bounds??={start:item.result.inTime,end:item.result.outTime};
          if(item.result.confidence==='Review required'||!item.result.onsetDetection){
            item.status='Review';item.error=item.result.reason||'Confirm onset before export.';continue;
          }
          item.status='Exporting';this.update();
          item.exported=await ops.export(item.result.id,item.bounds,saved);
          item.status='Done';item.error='';
        }catch(error){item.error=error.message||String(error);item.status=item.error.startsWith('Review required:')?'Review':'Failed';}
        finally{this.update();}
      }
    }finally{this.running=false;this.update();}
  }
}
if(typeof module!=='undefined')module.exports={VideoQueue};
