"""Loopback-only start-video editor. Python standard library + local FFmpeg."""
import json
import bisect
import math
from pathlib import Path
import secrets
import shutil
import statistics
import subprocess
import tempfile
import threading
import zipfile
import hashlib
from timeline import limit_playback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
WORK = None
TOKEN = secrets.token_urlsafe(32)
JOBS = {}
BUNDLES = {}
LOCK = threading.Lock()
MAX_BYTES = 512 * 1024 * 1024
MAX_PLAYBACK_SECONDS = 3.5
MAX_EXTRA_CONTEXT_SECONDS = .25


def binary(name):
    found = shutil.which(name)
    if found:
        return found
    choices = list((ROOT / 'tools').rglob(name + '.exe'))
    if choices:
        return str(choices[0])
    raise ValueError('FFmpeg is missing. Put ffmpeg.exe and ffprobe.exe in tools, then restart.')


def run(name, args):
    result = subprocess.run([binary(name), '-v', 'error', *args], capture_output=True,
                            timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError(result.stderr.decode(errors='replace')[-1400:] or 'Video processing failed.')
    return result.stdout


def probe(path, extra):
    return json.loads(run('ffprobe', ['-print_format', 'json', *extra, str(path)]))


def fit_motion(times, scores):
    """Centered local quadratic least squares on actual timestamps (including VFR)."""
    clean = [statistics.median(scores[max(0,i-1):i+2]) for i in range(len(scores))]
    dt = statistics.median([b-a for a,b in zip(times,times[1:]) if b>a])
    radius = max(2, round(.075/dt))
    fitted, slope, curvature = [], [], []
    for i,t in enumerate(times):
        left, right = max(0,i-radius), min(len(times),i+radius+1)
        # Scale time to keep the small normal system numerically well conditioned.
        scale = max(.075, dt*radius)
        xs = [(x-t)/scale for x in times[left:right]]
        ys = clean[left:right]
        sums = [sum(x**k for x in xs) for k in range(5)]
        matrix = [[sums[r+c] for c in range(3)] + [sum(y*x**r for x,y in zip(xs,ys))]
                  for r in range(3)]
        for column in range(3):
            pivot = max(range(column,3),key=lambda r:abs(matrix[r][column]))
            matrix[column],matrix[pivot] = matrix[pivot],matrix[column]
            divisor = matrix[column][column]
            if abs(divisor) < 1e-12:
                raise ValueError('Video frame timestamps do not support a motion fit.')
            matrix[column] = [v/divisor for v in matrix[column]]
            for row in range(3):
                if row != column:
                    factor = matrix[row][column]
                    matrix[row] = [a-factor*b for a,b in zip(matrix[row],matrix[column])]
        a,b,c = [matrix[r][3] for r in range(3)]
        fitted.append(a)
        slope.append(b/scale)
        curvature.append(2*c/(scale*scale))
    return dict(despiked=clean, smoothed=fitted, slope=slope, curvature=curvature,
                fitWindowSeconds=2*radius*dt, method='Median despike + centered local quadratic fit on source timestamps')


def curvature_onset(times, fit):
    """Find a motion episode from curvature energy, then fit its onset change point."""
    values, second, clean = fit['smoothed'], fit['curvature'], fit['despiked']
    dt = statistics.median([b-a for a,b in zip(times,times[1:]) if b>a])
    def span(a,b):
        return range(max(0,a),min(len(times),b))
    candidates=[]
    for i in range(max(4,round(.4/dt)),len(times)-max(3,round(.3/dt))):
        past=list(span(i-round(.4/dt),i-round(.12/dt)))
        baseline=statistics.median([values[j] for j in past])
        noise=max(.015,1.4826*statistics.median([abs(values[j]-baseline) for j in past]))
        center=statistics.median([second[j] for j in past])
        curvature_noise=max(1.,1.4826*statistics.median([abs(second[j]-center) for j in past]))
        threshold=max(4.,3*curvature_noise)
        energy_window=list(span(i,i+max(2,round(.05/dt))))
        energy=math.sqrt(statistics.mean([(second[j]-center)**2 for j in energy_window]))
        future=list(span(i+round(.12/dt),i+round(.4/dt)))
        gain=statistics.mean([values[j] for j in future])-baseline
        if energy>threshold and gain>max(.06,4*noise) and gain>max(0,baseline)*.25:
            candidates.append(dict(index=i,score=gain/(max(0,baseline)+noise+.1),
                                   threshold=threshold,baseline=baseline,noise=noise))
    if not candidates:
        return None,None
    # Opposite-sign lobes belong to one episode until there is a substantial gap.
    # Rank episodes by confirmed activity, then use their FIRST departure.
    groups=[]
    for candidate in candidates:
        separated = not groups
        if groups and times[candidate['index']]-times[groups[-1][-1]['index']]>.35:
            previous=groups[-1]
            quiet_limit=previous[0]['baseline']+max(.04,3*previous[0]['noise'])
            run=0
            for j in range(previous[-1]['index'],candidate['index']):
                run=run+1 if values[j]<=quiet_limit else 0
                if run>=max(2,round(.12/dt)):
                    separated=True
                    break
        if separated:
            groups.append([])
        groups[-1].append(candidate)
    group=max(groups,key=lambda g:max(c['score'] for c in g))
    first=group[0];crossing=first['index']
    # Estimate a drifting quiet baseline from despiked, unsmoothed samples.
    quiet=[j for j,t in enumerate(times) if times[crossing]-.4<=t<times[crossing]-.1]
    baseline=statistics.median([clean[j] for j in quiet])
    noise=max(.015,1.4826*statistics.median([abs(clean[j]-baseline) for j in quiet]))
    mean_t=statistics.mean([times[j] for j in quiet])
    mean_y=statistics.mean([clean[j] for j in quiet])
    denominator=sum((times[j]-mean_t)**2 for j in quiet)
    drift=sum((times[j]-mean_t)*(clean[j]-mean_y) for j in quiet)/max(denominator,1e-12)
    def base(t):return baseline+drift*(t-mean_t)
    local=[j for j,t in enumerate(times) if times[crossing]-.35<=t<=times[crossing]+.42]
    best=(float('inf'),None,None)
    for candidate in (j for j in local if times[crossing]-.20<=times[j]<=times[crossing]+.24):
        pre=[j for j in local if times[candidate]-.12<=times[j]<times[candidate]]
        # A candidate at the motion peak cannot pass if the signal was already
        # persistently above its quiet baseline immediately before that candidate.
        if len(pre)<2 or statistics.median([clean[j]-base(times[j]) for j in pre])>max(.04,3*noise):
            continue
        for rise in (0.,.05,.1,.2,.35,.5,.8):
            for power in ((1,) if rise==0 else (1,2,3)):
                basis=[float(times[j]>=times[candidate]) if rise==0 else
                       min(1.,max(0.,(times[j]-times[candidate])/rise))**power for j in local]
                residual=[clean[j]-base(times[j]) for j in local]
                amplitude=max(0.,sum(x*y for x,y in zip(basis,residual))/max(sum(x*x for x in basis),1e-12))
                def huber(error):
                    z=abs(error)/noise
                    return z*z/2 if z<=2 else 2*(z-1)
                cost=sum(huber(y-amplitude*x) for x,y in zip(basis,residual))
                if cost<best[0]:best=cost,candidate,dict(riseSeconds=rise,power=power,amplitude=amplitude,
                                                     baseline=baseline,baselineReferenceTime=mean_t,baselineDrift=drift)
    idx=best[1]
    if idx is None:
        return None,None
    fit['changePointFit'] = dict(times=[times[j] for j in local],
        values=[base(times[j])+best[2]['amplitude']*(float(times[j]>=times[idx]) if best[2]['riseSeconds']==0 else
                min(1.,max(0.,(times[j]-times[idx])/best[2]['riseSeconds']))**best[2]['power']) for j in local],
        baseline=[base(times[j]) for j in local])
    return idx,dict(method='Curvature-energy episode + robust baseline-to-rise change-point fit',
                    curvatureThreshold=first['threshold'],curvatureCrossingTime=times[crossing],
                    onsetFrame=idx,onsetTime=times[idx],baselineNoise=noise,baselineDrift=drift,
                    changePointModel=best[2],episodeCandidates=len(group),
                    episodes=[dict(start=times[g[0]['index']],end=times[g[-1]['index']],
                                   strength=max(c['score'] for c in g)) for g in groups],
                    refinement='Earliest departure in the selected episode; late candidates with already-moving prehistory rejected')


def motion_events(times, scores, duration, lead):
    """Heuristic: sustained movement after a quiet window; sustained quiet after launch."""
    if len(scores) < 6 or max(scores, default=0) < 0.15:
        return dict(set=0, start=None, exit=duration, inTime=0,
                    outTime=duration, confidence='Review required', reason='Too little motion to identify a reliable start.')
    dt = statistics.median([b-a for a, b in zip(times, times[1:]) if b > a])
    window = max(2, round(.22 / dt))
    fit = fit_motion(times, scores)
    smooth = [max(0,s) for s in fit['smoothed']]
    floor = sorted(smooth)[max(0, len(smooth)//5)]
    peak = max(smooth)
    idx, onset_details = curvature_onset(times, fit)
    if idx is None:
        return dict(set=0,start=None,exit=duration,inTime=0,outTime=duration,
                    confidence='Review required',reason='No reliable baseline-to-rise change point found. Mark onset manually; no motion peak was substituted.',
                    motionFit=fit,onsetDetection=None)
    reason='Onset estimated at the quiet-to-motion change point; curvature oscillation energy identifies the rise episode.'
    confidence='Candidate found'
    quiet_end = max(1, idx-round(.15/dt))
    set_idx = max(0, quiet_end-window)
    quiet_samples = smooth[set_idx:quiet_end] or [floor]
    baseline = statistics.median(quiet_samples)
    deviation = statistics.median([abs(s-baseline) for s in quiet_samples])
    quiet_limit = max(floor*1.3, baseline + max(.03, deviation*3))
    # Require sustained quiet, rather than allowing a permissive threshold to
    # swallow the athlete's slower movement into set.
    lookback = max(2, round(.10/dt))
    while set_idx > 0 and statistics.mean(smooth[max(0,set_idx-lookback):set_idx]) < quiet_limit:
        set_idx -= 1
    end = duration
    sustain = max(3, round(.25/dt))
    threshold = max(floor * 1.7, peak * .12, .25)
    for i in range(idx + max(3, round(.3/dt)), len(smooth)-sustain+1):
        if max(smooth[i:i+sustain]) < threshold:
            end = times[i]
            break
    else:
        reason += ' No sustained exit drop found; end of source retained.'
    return dict(set=times[set_idx], start=times[idx], exit=end,
                inTime=max(0, times[idx]-lead), outTime=end,
                confidence=confidence, reason=reason, motionFit=fit, onsetDetection=onset_details)


def tighten_selection(events, keys, target=3.5):
    """Trade preferred lead-in for another keyframe, retaining 0.5s before onset."""
    events = dict(events)
    if events.get('start') is None:
        return events
    original_in = events['inTime']
    head = max((t for t in keys if t <= original_in+1e-6), default=0)
    if events['outTime']-head > target:
        latest = max((t for t in keys if t <= events['start']-.5+1e-6), default=head)
        if latest > head:
            events['inTime'] = latest
            events['reason'] += (f' Tight framing uses {events["start"]-latest:.3f}s before movement onset '
                                 'to reduce clip length while preserving original frames.')
    return events


def analyze(source, folder, lead, tight=True):
    info = probe(source, ['-show_streams', '-show_format'])
    video = next((s for s in info['streams'] if s['codec_type']=='video'), None)
    if not video:
        raise ValueError('No video stream found.')
    duration = float(video.get('duration') or info['format'].get('duration') or 0)
    if not 0 < duration <= 12:
        raise ValueError('Please use a short start video (1–10 seconds; maximum 12 seconds).')
    # Decode every original frame. Analysis reduces spatial resolution only, never temporal resolution.
    frames = probe(source, ['-select_streams', 'v:0', '-show_frames', '-show_entries',
                            'frame=best_effort_timestamp_time,key_frame'])['frames']
    origin = float(frames[0]['best_effort_timestamp_time'])
    times = [float(f['best_effort_timestamp_time'])-origin for f in frames]
    keys = [t for t,f in zip(times,frames) if f.get('key_frame') == 1]
    dummy = folder / 'analysis-gray.mkv'
    run('ffmpeg', ['-y', '-i', str(source), '-map', '0:v:0', '-an', '-vf',
                   'scale=160:90:flags=area,format=gray', '-fps_mode', 'passthrough',
                   '-c:v', 'ffv1', str(dummy)])
    raw = run('ffmpeg', ['-i', str(dummy), '-map', '0:v:0', '-fps_mode', 'passthrough',
                         '-f', 'rawvideo', '-pix_fmt', 'gray', '-'])
    size = 160*90
    count = len(raw)//size
    if count != len(times):
        raise ValueError('Analysis frame count differs from the original. Cannot safely map timestamps.')
    scores = [0.0]
    for i in range(1, count):
        before, after = raw[(i-1)*size:i*size], raw[i*size:(i+1)*size]
        scores.append(sum(abs(a-b) for a,b in zip(before,after))/size)
    events = motion_events(times, scores, duration, lead)
    if tight:
        events = tighten_selection(events, keys)
    return dict(duration=duration, fps=video.get('avg_frame_rate'), width=video['width'],
                height=video['height'], codec=video['codec_name'], frames=count,
                times=times, scores=scores, keys=keys, durationLimit=MAX_PLAYBACK_SECONDS if tight else None, **events)


class UnsafeCutError(ValueError):
    def __init__(self, message, boundary='tail'):
        super().__init__(message)
        self.boundary = boundary


def _export_attempt(job, start, end, actual_start, actual_end, ident, cache, playback_end=None):
    data = job['result']
    ext = job['source'].suffix.lower()
    ext = ext if ext in ('.mp4','.mov') else '.mkv'
    output = job['folder']/('clip'+ext)
    # Only the head requires a keyframe. Packet decode order retains references
    # required by the tail; decoded-frame checks below validate the result.
    args = ['-y', '-ss', str(actual_start), '-i', str(job['source']), '-t',
            str(actual_end-actual_start), '-map', '0:v:0', '-map', '0:a?', '-map_metadata', '0',
            '-map_chapters', '-1', '-c', 'copy', '-avoid_negative_ts', 'disabled']
    if ext in ('.mp4', '.mov'):
        args += ['-movflags', '+faststart', '-use_editlist', '1']
    args += [str(output)]
    run('ffmpeg', args)
    timeline = None
    if playback_end is not None and ext in ('.mp4','.mov'):
        try:
            timeline = limit_playback(output, playback_end-actual_start)
        except ValueError as error:
            output.unlink(missing_ok=True)
            raise ValueError('Review required: unsupported playback edits. '+str(error)) from error
    # Verify preservation of encoded video packets against source packet sequence.
    def packets(path):
        return probe(path, ['-select_streams','v:0','-show_packets','-show_data_hash','sha256',
                            '-show_entries','packet=data_hash,pts_time,duration_time'])['packets']
    if 'packets' not in cache:
        cache['packets'] = packets(job['source'])
    original_packets, clipped_packets = cache['packets'], packets(output)
    original = [p['data_hash'] for p in original_packets]
    clipped = [p['data_hash'] for p in clipped_packets]
    offset = next((i for i in range(len(original)-len(clipped)+1)
                   if original[i:i+len(clipped)] == clipped), None) if clipped else None
    matching = offset is not None
    timing_verified = False
    coverage = None
    if matching:
        corresponding = original_packets[offset:offset+len(clipped)]
        source_pts = [float(p['pts_time']) for p in corresponding]
        output_pts = [float(p['pts_time']) for p in clipped_packets]
        timing_verified = all(abs((a-source_pts[0])-(b-output_pts[0])) < .0001
                              for a,b in zip(source_pts,output_pts))
        source_origin = float(original_packets[0]['pts_time'])
        coverage = [min(source_pts)-source_origin,
                    max(float(p['pts_time'])+float(p.get('duration_time',0))
                        for p in corresponding)-source_origin]
        matching = coverage[0] <= start+.001 and coverage[1] >= end-.001
    if not matching or not timing_verified:
        output.unlink(missing_ok=True)
        raise UnsafeCutError('Export verification failed: content, timing, or requested coverage differs from the source.')
    def decoded_hashes(path):
        raw = run('ffmpeg', ['-err_detect', 'explode', '-i', str(path), '-map', '0:v:0',
                             '-an', '-fps_mode', 'passthrough', '-f', 'framemd5', '-'])
        return [line.split(',')[-1].strip() for line in raw.decode().splitlines()
                if line and not line.startswith('#')]
    if 'decoded' not in cache:
        cache['decoded'] = decoded_hashes(job['source'])
    source_decoded = cache['decoded']
    try:
        output_decoded = decoded_hashes(output)
    except ValueError as error:
        output.unlink(missing_ok=True)
        raise UnsafeCutError(str(error)) from error
    decoded_offset = next((i for i in range(len(source_decoded)-len(output_decoded)+1)
                           if source_decoded[i:i+len(output_decoded)] == output_decoded), None) if output_decoded else None
    output_info = probe(output, ['-show_streams', '-show_format'])
    output_video = next(s for s in output_info['streams'] if s['codec_type'] == 'video')
    measured_duration = float(output_video.get('duration') or output_info['format']['duration'])
    video_start = float(output_video.get('start_time', 0))
    if abs(video_start) > .05 or float(output_info['format']['duration']) > measured_duration+.1:
        output.unlink(missing_ok=True)
        raise UnsafeCutError('Export has an inconsistent playback timeline.')
    if decoded_offset is None or len(output_decoded) < 2:
        output.unlink(missing_ok=True)
        kind = 'head' if not output_decoded or output_decoded[0] not in set(source_decoded) else 'tail'
        raise UnsafeCutError('Export did not decode to a continuous sequence of original frames.', kind)
    source_times = data['times']
    if len(source_decoded) != len(source_times):
        output.unlink(missing_ok=True)
        raise ValueError('Source decode timestamps and frame count differ; manual review is required.')
    last = decoded_offset+len(output_decoded)
    decoded_coverage = [source_times[decoded_offset],
                        source_times[last] if last < len(source_times) else data['duration']]
    if decoded_coverage[0] > start+.001 or decoded_coverage[1] < end-.001:
        output.unlink(missing_ok=True)
        raise UnsafeCutError('Decoded frames do not cover the requested interval.',
                             'head' if decoded_coverage[0] > start+.001 else 'tail')
    actual_end = coverage[1]
    if 'metadata' not in cache:
        cache['metadata'] = probe(job['source'], ['-show_streams', '-show_format'])
    report = dict(requestedStart=start, requestedEnd=end, exportStart=actual_start,
                  exportEnd=actual_end, original=data, videoPacketsVerified=True,
                  relativePresentationTimingVerified=timing_verified,
                  sourcePresentationCoverage=coverage,
                  decodedSourceCoverage=decoded_coverage,
                  playbackTimeline=timeline,
                  decodedFramesVerified=True, exportedFrames=len(output_decoded),
                  measuredVideoDuration=measured_duration,
                  sourceDecodedFrameOffset=decoded_offset,
                  outputVideoStart=video_start,
                  originalMetadata=cache['metadata'],
                  auxiliaryTracks='Only primary video and audio included in playback file; original stream metadata preserved in this report.',
                  exportedVideoPackets=len(clipped), method='Stream copy; original encoded video packets preserved. Container timestamps rebased for playback.')
    (job['folder']/'edit-report.json').write_text(json.dumps(report,indent=2))
    exported = dict(url='/download/'+ident+'/'+output.name,
                             report='/download/'+ident+'/edit-report.json',
                             start=coverage[0], end=actual_end, packets=len(clipped),
                             duration=measured_duration, sourceDuration=data['duration'],
                             frames=len(output_decoded),
                             warning=('Over 3.5 seconds: APOPT may reduce its analysis frame rate. A tighter cut needs manual review or different source keyframes.'
                                      if float(output_info['format']['duration']) > 3.5 else None))
    job['export'] = exported
    return exported


def passthrough_original(job, ident):
    data = job['result']
    info = probe(job['source'], ['-show_streams','-show_format'])
    video = next(s for s in info['streams'] if s['codec_type']=='video')
    duration = max(float(video.get('duration') or 0),float(info['format']['duration']))
    if duration > MAX_PLAYBACK_SECONDS or abs(float(video.get('start_time',0))) > .05:
        return None
    ext = job['source'].suffix.lower()
    output = job['folder']/('clip'+ext)
    shutil.copyfile(job['source'],output)
    def checksum(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream,'sha256').hexdigest()
    source_hash, copied_hash = checksum(job['source']), checksum(output)
    if source_hash != copied_hash:
        output.unlink(missing_ok=True)
        raise ValueError('Original-file copy verification failed.')
    report = dict(original=data, originalMetadata=info, exportStart=0, exportEnd=data['duration'],
                  requestedStart=data['inTime'], requestedEnd=data['outTime'],
                  measuredVideoDuration=duration, exportedFrames=data['frames'],
                  sourcePresentationCoverage=[0,data['duration']], decodedSourceCoverage=[0,data['duration']],
                  videoPacketsVerified=True, decodedFramesVerified=True, relativePresentationTimingVerified=True,
                  originalFileSHA256=source_hash, outputFileSHA256=copied_hash, originalFileUnchanged=True,
                  method='Byte-identical original file; existing playback edits and all tracks preserved',
                  verificationMode='Whole-file SHA256 equality; source frame count from analysis',
                  boundaryRecovery=dict(retried=False,attempts=[]))
    (job['folder']/'edit-report.json').write_text(json.dumps(report,indent=2))
    result = dict(url='/download/'+ident+'/'+output.name,report='/download/'+ident+'/edit-report.json',
                  start=0,end=data['duration'],duration=duration,sourceDuration=data['duration'],frames=data['frames'],
                  packets=len(probe(output,['-select_streams','v:0','-show_packets','-show_entries','packet=pts_time'])['packets']),
                  originalFileUnchanged=True,boundaryAdjusted=False,verificationAttempts=1,warning=None,
                  boundaryNote='Original already fits 3.5 seconds; downloaded file is byte-identical.')
    job['export'] = result
    return result


def export_verified(job, start, end, ident, allow_original=True):
    """Bounded copy-only recovery with a fixed visible playback interval."""
    data = job['result']
    # Manual boundary changes always request a trim, even for a short source.
    automatic = abs(start-data['inTime'])<.000002 and abs(end-data['outTime'])<.000002
    if allow_original and automatic and job['source'].suffix.lower() in ('.mp4','.mov'):
        result = passthrough_original(job,ident)
        if result:
            return result
    keys, times = data['keys'], data['times']
    head = max((t for t in keys if t <= start+1e-6), default=0)
    index = bisect.bisect_left(times,end-1e-6)
    tail = times[index] if index < len(times) else data['duration']
    limit = data.get('durationLimit',MAX_PLAYBACK_SECONDS)
    if limit is not None and tail-head > limit+.000001:
        raise ValueError('Review required: a copy-only cut cannot fit 3.5 seconds at these boundaries. Adjust the interval or explicitly disable the duration limit.')
    ends = [tail]+[times[index+step] for step in (1,2,4,8,16,32) if index+step < len(times)]
    last_context = bisect.bisect_right(times,tail+MAX_EXTRA_CONTEXT_SECONDS)-1
    if last_context >= index:
        ends.append(times[last_context])
    ends += [t for t in keys if tail < t <= tail+MAX_EXTRA_CONTEXT_SECONDS]
    if data['duration'] <= tail+MAX_EXTRA_CONTEXT_SECONDS:
        ends.append(data['duration'])
    ends = sorted({t for t in ends if tail <= t <= tail+MAX_EXTRA_CONTEXT_SECONDS+.000001})
    heads = [head]+sorted((t for t in keys if head-MAX_EXTRA_CONTEXT_SECONDS <= t < head-.000001),reverse=True)
    if head <= MAX_EXTRA_CONTEXT_SECONDS and 0 not in heads:
        heads.append(0)
    attempts,cache = [],{}
    best = None
    best_output = job['folder']/'verified-best.tmp'
    best_report = None
    for candidate_head in heads:
        if limit is not None and tail-candidate_head > limit+.000001:
            continue
        # An earlier head can never be shorter than the already verified result.
        if best is not None and tail-candidate_head >= best['duration']-.001:
            continue
        for candidate_tail in ends:
            try:
                result = _export_attempt(job,start,end,candidate_head,candidate_tail,ident,cache,playback_end=tail)
            except UnsafeCutError as error:
                attempts.append(dict(start=candidate_head,end=candidate_tail,error=str(error)))
                if error.boundary == 'head':
                    break
                continue
            if limit is not None and result['duration'] > limit+.000001:
                attempts.append(dict(start=candidate_head,end=candidate_tail,error='Measured duration exceeds the enabled limit.'))
                continue
            if best is None or result['duration'] < best['duration']-.000001:
                best = result
                best_report = json.loads((job['folder']/'edit-report.json').read_text())
                best_report['boundaryRecovery'] = dict(retried=bool(attempts),attempts=list(attempts),
                    requestedStart=start,requestedEnd=end,chosenSeekStart=candidate_head,chosenCutEnd=candidate_tail,
                    addedCutTailSeconds=candidate_tail-tail,extraHeadSeconds=head-candidate_head,
                    maximumContextSeconds=MAX_EXTRA_CONTEXT_SECONDS,playbackEnd=tail)
                shutil.copyfile(job['folder']/result['url'].split('/')[-1],best_output)
            # Longer coded tails have the same fixed visible interval, so cannot
            # improve duration after this head has produced a verified candidate.
            break
    if best is None:
        job.pop('export',None)
        for ext in ('.mov','.mp4','.mkv'):
            (job['folder']/('clip'+ext)).unlink(missing_ok=True)
        message = attempts[-1]['error'] if attempts else 'No bounded copy-only cut fits.'
        raise ValueError('Review required: '+message+' Recovery was limited to 0.25 seconds of source context; no re-encoding or long fallback was used.')
    shutil.copyfile(best_output,job['folder']/best['url'].split('/')[-1])
    best_output.unlink()
    (job['folder']/'edit-report.json').write_text(json.dumps(best_report,indent=2))
    best['boundaryAdjusted'] = bool(best_report['boundaryRecovery']['retried'])
    best['boundaryNote'] = 'Original playback interval preserved; extra coded context is hidden by playback edits.'
    best['verificationAttempts'] = len(attempts)+1
    job['export'] = best
    return best


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, data, status=200, mime='application/json'):
        body = json.dumps(data).encode() if mime=='application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        port = self.server.server_address[1]
        return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def do_GET(self):
        if not self.allowed():
            return self.respond({'error':'Invalid host'}, 403)
        path = urlparse(self.path).path
        if path == '/api/status':
            try:
                binary('ffmpeg'); binary('ffprobe')
                ready = True
            except ValueError:
                ready = False
            return self.respond(dict(ready=ready, token=TOKEN))
        if path == '/':
            return self.respond((ROOT/'index.html').read_bytes(), mime='text/html; charset=utf-8')
        if path in ('/queue.js','/batch.js'):
            return self.respond((ROOT/path[1:]).read_bytes(), mime='text/javascript; charset=utf-8')
        if path.startswith('/bundle/'):
            file = BUNDLES.get(path.split('/')[-1])
            if file and file.is_file():
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Length', str(file.stat().st_size))
                self.send_header('Content-Disposition', 'attachment; filename="start-clips.zip"')
                self.end_headers()
                with file.open('rb') as stream:
                    shutil.copyfileobj(stream, self.wfile)
                return
        if path.startswith('/download/'):
            parts = path.split('/')
            job = JOBS.get(parts[2]) if len(parts)==4 else None
            name = parts[3] if len(parts)==4 else ''
            if job and name in ('clip.mp4','clip.mov','clip.mkv','edit-report.json') and (job['folder']/name).is_file():
                file = job['folder']/name
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(file.stat().st_size))
                self.send_header('Content-Disposition', 'attachment; filename="'+name+'"')
                self.end_headers()
                with file.open('rb') as stream:
                    shutil.copyfileobj(stream, self.wfile)
                return
        self.respond({'error':'Not found'}, 404)

    def do_POST(self):
        if not self.allowed() or self.headers.get('X-Local-Token') != TOKEN:
            return self.respond({'error':'Invalid local session'}, 403)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= MAX_BYTES:
                raise ValueError('File is empty or exceeds 512 MB.')
            if not LOCK.acquire(blocking=False):
                return self.respond({'error':'Processing another clip. Please wait.'}, 409)
            try:
                if self.path == '/api/bundle':
                    rows = json.loads(self.rfile.read(length)).get('items', [])
                    if not isinstance(rows,list) or not rows or len(rows)>10000:
                        raise ValueError('Choose up to 10,000 queue entries per archive.')
                    ident = secrets.token_hex(12)
                    archive = WORK/('batch-'+ident+'.zip')
                    included = 0
                    manifest = []
                    try:
                        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
                            for index,row in enumerate(rows,1):
                                name = str(row.get('name','video'))[:180]
                                summary = dict(index=index, sourceName=name, status=str(row.get('status','')),
                                               message=str(row.get('message',''))[:2000])
                                job = JOBS.get(row.get('id'))
                                if job and job.get('export'):
                                    output = job['folder']/job['export']['url'].split('/')[-1]
                                    # Prefix each entry to avoid collisions even for identical source filenames.
                                    stem = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in Path(name).stem)[:100] or 'video'
                                    prefix = f'{index:05d}-{stem}'
                                    bundle.write(output, prefix+output.suffix)
                                    bundle.write(job['folder']/'edit-report.json', prefix+'-report.json')
                                    summary.update(status='exported', clip=prefix+output.suffix,
                                                   duration=job['export']['duration'], warning=job['export']['warning'])
                                    included += 1
                                manifest.append(summary)
                            if not included:
                                raise ValueError('No verified exports are available to download.')
                            bundle.writestr('batch-summary.json',json.dumps(manifest,indent=2))
                        BUNDLES[ident] = archive
                    except Exception:
                        archive.unlink(missing_ok=True)
                        raise
                    return self.respond(dict(url='/bundle/'+ident, count=included))
                if self.path == '/api/discard':
                    request = json.loads(self.rfile.read(length))
                    for ident in request.get('ids',[]):
                        job = JOBS.pop(ident,None)
                        if job:
                            shutil.rmtree(job['folder'])
                    if request.get('clearBundles'):
                        for archive in BUNDLES.values():
                            archive.unlink(missing_ok=True)
                        BUNDLES.clear()
                    return self.respond(dict(ok=True))
                if self.path == '/api/analyze':
                    ident = secrets.token_hex(12)
                    folder = WORK/ident
                    folder.mkdir()
                    ext = self.headers.get('X-Extension', '.mp4').lower()
                    if ext not in ('.mp4','.mov','.mkv','.webm','.avi','.m4v'):
                        raise ValueError('Choose MP4, MOV, MKV, WebM, AVI or M4V.')
                    source = folder/('original'+ext)
                    with source.open('wb') as out:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(1024*1024, remaining))
                            if not chunk:
                                raise ValueError('Incomplete file transfer.')
                            out.write(chunk)
                            remaining -= len(chunk)
                    lead = float(self.headers.get('X-Lead', '.75'))
                    if not .5 <= lead <= 1:
                        raise ValueError('Lead-in must be 0.5–1 seconds.')
                    try:
                        result = analyze(source, folder, lead, self.headers.get('X-Tight', '1') == '1')
                    except Exception:
                        shutil.rmtree(folder)
                        raise
                    JOBS[ident] = dict(source=source, folder=folder, result=result)
                    return self.respond(dict(id=ident, **result))
                if self.path == '/api/export':
                    request = json.loads(self.rfile.read(length))
                    job = JOBS[request['id']]
                    job.pop('export', None)
                    if 'limitDuration' in request:
                        if not isinstance(request['limitDuration'], bool):
                            raise ValueError('Invalid duration-limit setting.')
                        job['result']['durationLimit'] = MAX_PLAYBACK_SECONDS if request['limitDuration'] else None
                    data = job['result']
                    start, end = float(request['start']), float(request['end'])
                    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= data['duration']+.001):
                        raise ValueError('Choose a valid in/out interval.')
                    exported = export_verified(job,start,end,request['id'],allow_original=request.get('keepOriginal',True) is True)
                    return self.respond(exported)
                self.respond({'error':'Not found'},404)
            finally:
                LOCK.release()
        except Exception as error:
            self.respond({'error':str(error)},400)


if __name__ == '__main__':
    SESSION = tempfile.TemporaryDirectory(prefix='apopt-starts-')
    WORK = Path(SESSION.name)
    server = ThreadingHTTPServer(('127.0.0.1',8765),Handler)
    print('Start editor: http://127.0.0.1:8765 (Ctrl+C to stop)',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        SESSION.cleanup()
