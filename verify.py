"""Synthetic 120 fps end-to-end test; no athlete footage required."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import io
import zipfile
import server


def main():
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    times = [i/120 for i in range(720)]
    scores = [0 if t < 2.5 or t >= 4.5 else 5 for t in times]
    event = server.motion_events(times, scores, 6, .75)
    assert 2.4 < event['start'] < 2.6
    assert 4.4 < event['exit'] < 4.6
    assert server.motion_events(times, [0]*720, 6, .75)['confidence'] == 'Review required'
    tight = server.tighten_selection(dict(set=1,start=2.534583,inTime=1.784583,outTime=5.194167,reason=''),
                                     [0,.992083,1.984167,2.97625])
    assert tight['inTime'] == 1.984167
    assert 2.534583-tight['inTime'] >= .5
    assert 5.194167-tight['inTime'] < 3.5
    # Never force the head past the minimum set lead-in, even if the target is unreachable.
    limited = server.tighten_selection(dict(set=1,start=2,inTime=1.25,outTime=7,reason=''),[0,1,2,3])
    assert limited['inTime'] == 1.25
    onset_clip = server.motion_events(times,scores,6,.75)
    assert onset_clip['inTime'] == onset_clip['start']-.75
    assert onset_clip['inTime'] > onset_clip['set']
    with tempfile.TemporaryDirectory() as directory:
        server.WORK = Path(directory)/'jobs'
        server.WORK.mkdir()
        http = server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        base = 'http://127.0.0.1:'+str(http.server_address[1])
        source = Path(directory)/'synthetic.mp4'
        raw = bytearray()
        for i in range(720):
            t = i/120
            frame = bytearray(160*90)
            if t < 4.5:
                left = 20 if t < 2.5 else 20+int((t-2.5)*70)
                for y in range(25,65):
                    for x in range(left,min(160,left+20)):
                        frame[y*160+x] = 220
            raw.extend(frame)
        subprocess.run([server.binary('ffmpeg'),'-v','error','-y','-f','rawvideo','-pix_fmt','gray',
                        '-s','160x90','-r','120','-i','-','-c:v','libx264','-g','60',
                        '-keyint_min','60','-sc_threshold','0',str(source)],input=raw,check=True)
        status = json.load(urllib.request.urlopen(base+'/api/status'))
        assert status['ready']
        def post(path, body, **headers):
            req = urllib.request.Request(base+path, data=body,
                                         headers={'X-Local-Token':status['token'],**headers})
            try:
                return json.load(urllib.request.urlopen(req,timeout=180))
            except urllib.error.HTTPError as error:
                raise AssertionError(error.read().decode()) from error
        data = post('/api/analyze',source.read_bytes(), **{'X-Extension':'.mp4','X-Lead':'.75'})
        (server.ROOT/'test-output').mkdir(exist_ok=True)
        (server.ROOT/'test-output'/'synthetic-analysis.json').write_text(json.dumps(data))
        assert data['frames'] == 720, data
        assert abs(data['start']-2.5) <= .05, data['start']
        assert 4.2 < data['exit'] < 4.8, data['exit']
        exported = post('/api/export', json.dumps(dict(id=data['id'],start=1.71,end=4.61)).encode())
        assert exported['start'] <= 1.71 and exported['end'] >= 4.61
        report = json.load(urllib.request.urlopen(base+exported['report']))
        assert report['videoPacketsVerified']
        assert report['decodedFramesVerified']
        assert report['relativePresentationTimingVerified']
        output = Path(directory)/'clip.mp4'
        output.write_bytes(urllib.request.urlopen(base+exported['url']).read())
        info = server.probe(output,['-show_streams'])['streams'][0]
        assert info['avg_frame_rate'] == '120/1', info
        assert 0 < int(info['nb_frames']) < 720
        assert exported['duration'] < 3.3, exported
        # Regression: a six-second file with only ONE keyframe used to export all six seconds.
        long_gop = Path(directory)/'long-gop.mp4'
        subprocess.run([server.binary('ffmpeg'),'-v','error','-y','-i',str(source),
                        '-c:v','libx264','-g','720','-keyint_min','720','-sc_threshold','0',
                        str(long_gop)],check=True)
        long_data = post('/api/analyze',long_gop.read_bytes(), **{'X-Extension':'.mp4','X-Lead':'.75'})
        assert len(long_data['keys']) == 1
        long_export = post('/api/export',json.dumps(dict(id=long_data['id'],start=1.71,end=4.61)).encode())
        assert 4.61 <= long_export['duration'] < 4.75, long_export
        long_output = Path(directory)/'long-cut.mp4'
        long_output.write_bytes(urllib.request.urlopen(base+long_export['url']).read())
        # Re-analyze the exported clip: later motion must still decode, not just its initial still.
        reanalyzed = post('/api/analyze',long_output.read_bytes(), **{'X-Extension':'.mp4','X-Lead':'.75'})
        assert max(reanalyzed['scores'][240:]) > .3, reanalyzed['scores']
        assert 2.4 < reanalyzed['start'] < 2.8, reanalyzed['start']
        assert reanalyzed['frames'] > 500
        bundle = post('/api/bundle',json.dumps(dict(items=[
            dict(id=data['id'],name='same.mov',status='Done'),
            dict(id=long_data['id'],name='same.mov',status='Done'),
            dict(id=None,name='broken.mov',status='Failed',message='Bad codec')])).encode())
        assert bundle['count'] == 2
        with zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(base+bundle['url']).read())) as archive:
            names=archive.namelist()
            assert len(names)==5 and len(set(names))==5, names
            summary=json.loads(archive.read('batch-summary.json'))
            assert summary[2]['status']=='Failed'
            assert archive.read(summary[0]['clip']) == output.read_bytes()
            assert archive.read(summary[1]['clip']) == long_output.read_bytes()
        post('/api/discard',json.dumps(dict(ids=[data['id'],long_data['id'],reanalyzed['id']],clearBundles=True)).encode())
        assert data['id'] not in server.JOBS and not server.BUNDLES
        http.shutdown()
        http.server_close()
        print(json.dumps(dict(passed=True, sourceFrames=720, originalFPS='120/1',
                              detectedStart=data['start'],detectedExit=data['exit'],
                              exportStart=exported['start'],exportEnd=exported['end'],
                              verifiedVideoPackets=exported['packets'],
                              trimmedDuration=exported['duration'],
                              singleKeyframeSourceDuration=6,
                              singleKeyframeTrimmedDuration=long_export['duration'],
                              laterMotionDecoded=True, batchZIPVerified=True,
                              temporaryFilesCleared=True),indent=2))


if __name__ == '__main__':
    main()
