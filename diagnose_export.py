"""Local cut/decode diagnostics; retains files under ignored test-output/."""
import json
from pathlib import Path
import sys
import server


def hashes(path, no_rotate=False):
    args = ['-noautorotate'] if no_rotate else []
    data = server.run('ffmpeg', [*args,'-i',str(path),'-map','0:v:0','-an','-fps_mode','passthrough','-f','framemd5','-']).decode()
    return [s.split(',')[-1].strip() for s in data.splitlines() if s and not s.startswith('#')]


def main():
    source = Path(sys.argv[1]).resolve()
    folder = server.ROOT/'test-output'/source.stem
    folder.mkdir(parents=True,exist_ok=True)
    data = server.analyze(source,folder,.75)
    start=max((t for t in data['keys'] if t<=data['inTime']+1e-6),default=0)
    end=next((t for t in data['times'] if t>=data['outTime']-1e-6),data['duration'])
    clip=folder/'cut.mov'
    server.run('ffmpeg',['-y','-ss',str(start),'-i',str(source),'-t',str(end-start),'-map','0:v:0','-map','0:a?',
                         '-map_metadata','0','-map_chapters','-1','-c','copy','-avoid_negative_ts','disabled','-movflags','+faststart',str(clip)])
    print(json.dumps(dict(source=str(source),duration=data['duration'],frames=data['frames'],onset=data['start'],
                          requestedStart=data['inTime'],start=start,end=end,keys=data['keys']),indent=2),flush=True)
    report=dict(analysis=data)
    for label,no_rotate in [('display',False),('unrotated',True)]:
        a,b=hashes(source,no_rotate),hashes(clip,no_rotate)
        offsets=[i for i in range(len(a)-len(b)+1) if a[i:i+len(b)]==b]
        matches=[(i,a.index(h) if h in a else None) for i,h in enumerate(b)]
        summary=dict(sourceFrames=len(a),clipFrames=len(b),offsets=offsets,
                     unmatched=sum(j is None for i,j in matches),firstMatches=matches[:8],lastMatches=matches[-8:])
        print(label,json.dumps(summary),flush=True)
        report[label]=dict(summary=summary,source=a,clip=b,matches=matches)
    for name,path in [('source',source),('clip',clip)]:
        video=next(s for s in server.probe(path,['-show_streams'])['streams'] if s['codec_type']=='video')
        print(name,json.dumps({k:video[k] for k in ['codec_name','width','height','pix_fmt','start_time','duration','side_data_list'] if k in video}),flush=True)
    (folder/'diagnostic.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__': main()
