"""Original passthrough, hidden MOV frame, bounded playback and no-long-fallback tests."""
import hashlib
import json
from pathlib import Path
import shutil
import server


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=server.ROOT/'test-output/export-policy'
    root.mkdir(parents=True,exist_ok=True)
    summaries=[]
    for name in ['Start7_120fps.MOV','Start6_120fps.MOV','Start8_120fps.MOV']:
        source=server.ROOT.parent/'Study3_Vid_11_4/Ashley'/name
        folder=root/source.stem;folder.mkdir(exist_ok=True)
        data=server.analyze(source,folder,.75)
        job=dict(source=source,folder=folder,result=data)
        # A reviewer may request export even when onset requires manual review.
        before=digest(source)
        result=server.export_verified(job,data['inTime'],data['outTime'],'test')
        assert digest(source)==before
        report=json.loads((folder/'edit-report.json').read_text())
        assert report['decodedFramesVerified'] and report['relativePresentationTimingVerified']
        assert result['duration']<=3.5
        if name=='Start7_120fps.MOV':
            assert result['originalFileUnchanged']
            assert digest(folder/'clip.mov')==before
            assert result['frames']==338
            # Force remux: timeline patch must hide the additional stored frame.
            trimmed=server.export_verified(job,data['inTime'],data['outTime'],'test',allow_original=False)
            remux_report=json.loads((folder/'edit-report.json').read_text())
            assert trimmed['frames']<=338
            assert remux_report['playbackTimeline'] is not None
            assert remux_report['decodedFramesVerified']
            # Leave a verified byte-identical original for the user to compare.
            result=server.export_verified(job,data['inTime'],data['outTime'],'test')
            destination=server.ROOT.parent/'outputs/start-video-editor'
            shutil.copyfile(folder/'clip.mov',destination/'Ashley-Start7_120fps-original.mov')
            shutil.copyfile(folder/'edit-report.json',destination/'Ashley-Start7_120fps-original-report.json')
        summaries.append(dict(file=name,duration=result['duration'],onset=data['start'],
                              unchanged=result.get('originalFileUnchanged',False),frames=result['frames']))
        print(json.dumps(summaries[-1]),flush=True)
    # A manually requested over-limit interval must fail before creating a long file.
    try:server.export_verified(job,0,data['duration'],'test',allow_original=False)
    except ValueError as error:assert str(error).startswith('Review required:')
    else:raise AssertionError('Long export silently accepted.')
    print('Original-file, hidden-frame, fixed playback interval and duration-limit checks passed.',flush=True)


if __name__=='__main__':main()
