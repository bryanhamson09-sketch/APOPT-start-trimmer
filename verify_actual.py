"""Local regression using the user-provided original and failed export."""
import json
from pathlib import Path
import tempfile
import threading
import urllib.request
import urllib.error
import server


def main():
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    source = server.ROOT.parent/'IMG_1708.MOV'
    destination = server.ROOT.parent/'outputs'/'start-video-editor'
    destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='apopt-regression-') as temp:
        server.WORK = Path(temp)
        http = server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        base = 'http://127.0.0.1:'+str(http.server_address[1])
        token = json.load(urllib.request.urlopen(base+'/api/status'))['token']
        def post(path, body, **headers):
            req = urllib.request.Request(base+path,data=body,headers={'X-Local-Token':token,**headers})
            try:
                return json.load(urllib.request.urlopen(req,timeout=600))
            except urllib.error.HTTPError as e:
                raise RuntimeError(e.read().decode()) from e
        try:
            data = post('/api/analyze',source.read_bytes(),**{'X-Extension':'.mov','X-Lead':'.75'})
            print(json.dumps({k:data[k] for k in ['duration','start','set','exit','inTime','outTime','keys','reason']},indent=2),flush=True)
            result = post('/api/export',json.dumps(dict(id=data['id'],start=data['inTime'],end=data['outTime'])).encode())
            output = destination/'IMG_1708-onset.mov'
            output.write_bytes(urllib.request.urlopen(base+result['url']).read())
            report = json.load(urllib.request.urlopen(base+result['report']))
            (destination/'IMG_1708-onset-report.json').write_text(json.dumps(report,indent=2))
            assert report['decodedFramesVerified']
            assert report['relativePresentationTimingVerified']
            assert abs(report['outputVideoStart']) <= .05
            assert result['duration'] < data['duration']-.25, result
            latest_safe_head = max((t for t in data['keys'] if t <= data['start']-.5),default=0)
            if data['exit']-latest_safe_head <= 3.5-.05:
                assert result['duration'] <= 3.5, result
            else:
                assert result['warning'] is not None
            assert 3.98 <= data['start'] <= 4.04
            assert data['start']-result['start'] >= .5
            assert result['start'] > data['set']
            assert result['end'] >= data['exit']-.001
            print(json.dumps(dict(output=str(output),**result),indent=2),flush=True)
        finally:
            http.shutdown()
            http.server_close()


if __name__ == '__main__':
    main()
