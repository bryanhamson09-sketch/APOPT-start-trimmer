"""Real HEVC boundary regression, preserving every decoded source frame."""
import json
from pathlib import Path
import shutil
import sys
import server


def main():
    parent=server.ROOT.parent
    files=[Path(p).resolve() for p in sys.argv[1:]] if len(sys.argv)>1 else [
        parent/'Study3_Vid_11_4/Bryan'/name for name in
        ['Start17_30fps.MOV','Start16_30fps.MOV','Start18_30fps.MOV','Start19_30fps.MOV',
         'Start20_30fps.MOV','Start1_120fps.MOV','Start2_120fps.MOV']]
    summaries=[]
    for index,source in enumerate(files):
        folder=server.ROOT/'test-output'/'boundary-recovery'/source.stem
        folder.mkdir(parents=True,exist_ok=True)
        data=server.analyze(source,folder,.75)
        job=dict(source=source,folder=folder,result=data)
        if source.name=='Start17_30fps.MOV':
            head=max(t for t in data['keys'] if t<=data['inTime']+1e-6)
            end=next(t for t in data['times'] if t>=data['outTime']-1e-6)
            try:
                server._export_attempt(job,data['inTime'],data['outTime'],head,end,'regression',{})
            except server.UnsafeCutError as error:
                assert 'continuous sequence' in str(error)
            else:
                raise AssertionError('Reported failure did not reproduce.')
        result=server.export_verified(job,data['inTime'],data['outTime'],'regression')
        report=json.loads((folder/'edit-report.json').read_text())
        assert report['decodedFramesVerified'] and report['relativePresentationTimingVerified']
        assert report['decodedSourceCoverage'][0]<=data['inTime']+.001
        assert report['decodedSourceCoverage'][1]>=data['outTime']-.001
        if source.name=='Start17_30fps.MOV':
            assert report['playbackTimeline'] is not None
            assert result['duration'] <= 3.5
            destination=parent/'outputs/start-video-editor'
            destination.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(folder/'clip.mov',destination/'Bryan-Start17_30fps-fixed.mov')
            shutil.copyfile(folder/'edit-report.json',destination/'Bryan-Start17_30fps-fixed-report.json')
        summary=dict(file=source.name,duration=result['duration'],frames=result['frames'],
                     attempts=result['verificationAttempts'],
                     extraTail=report['boundaryRecovery']['addedCutTailSeconds'])
        summaries.append(summary)
        print(json.dumps(summary),flush=True)
    (server.ROOT/'test-output/boundary-recovery/results.json').write_text(json.dumps(summaries,indent=2))
    print('Passed '+str(len(summaries))+' real-video boundary regressions.',flush=True)


if __name__=='__main__':main()
