"""Known-onset signal regressions, independent of codecs or athlete pose labels."""
import json
import math
import random
from pathlib import Path
import server


def main():
    results = []
    for fps in (30,60,120):
        for shape in ('step','quadratic'):
            randomizer = random.Random(184+fps)
            times = [i/fps for i in range(6*fps)]
            scores = []
            for t in times:
                rise = max(0,t-2.5)
                movement = (3 if rise>=0 and t>=2.5 else 0) if shape=='step' else min(3,20*rise*rise)
                if t>=4.5:
                    movement = 0
                scores.append(.2+randomizer.gauss(0,.012)+movement)
            scores[fps] += 2  # Isolated pre-start spike must not become the onset.
            event = server.motion_events(times,scores,6,.75)
            error = event['start']-2.5
            assert abs(error) <= max(.065,2/fps), (fps,shape,event['start'])
            assert event['onsetDetection'] is not None
            results.append(dict(fps=fps,shape=shape,onset=event['start'],errorSeconds=error))
    # The fit uses real timestamps: an irregularly sampled quadratic has d²/dt² = 6.
    times = [i/120+.0006*math.sin(i*.8) for i in range(400)]
    scores = [2+4*t+3*t*t for t in times]
    fit = server.fit_motion(times,scores)
    assert max(abs(v-6) for v in fit['curvature'][20:-20]) < 1e-7
    randomizer = random.Random(1)
    quiet = [.2+randomizer.gauss(0,.01) for _ in times]
    quiet[130] += 3
    quiet[240] += 2
    event = server.motion_events(times,quiet,times[-1],.75)
    assert event['onsetDetection'] is None
    assert event['start'] is None  # Never substitute the largest noise/motion peak.
    for shape in ('linear','oscillating','two_lobes'):
        times=[i/120 for i in range(720)]
        randomizer=random.Random(43)
        scores=[]
        for t in times:
            r=max(0,t-2.5)
            if shape=='linear': movement=min(3,3.75*r)
            elif shape=='oscillating': movement=min(3,5*r)+(.035*math.sin(80*r) if r>0 else 0)
            else: movement=min(.7,3.5*r)+min(2.3,max(0,t-3.05)*8)
            scores.append(.2+movement+randomizer.gauss(0,.008) if t<4.5 else .2)
        event=server.motion_events(times,scores,6,.75)
        assert event['start'] is not None and abs(event['start']-2.5)<=.085,(shape,event['start'])
        assert event['start']<3.0  # A later large lobe or peak must not become onset.
        results.append(dict(fps=120,shape=shape,onset=event['start']))
    # Real clip comparison is a lag regression, not manually labeled ground truth.
    saved = server.ROOT.parent/'outputs/start-video-editor/IMG_1708-tight-report.json'
    if saved.exists():
        original = json.loads(saved.read_text())['original']
        event = server.motion_events(original['times'],original['scores'],original['duration'],.75)
        assert 3.98 <= event['start'] <= 4.04
        results.append(dict(clip='IMG_1708',previousOnset=4.152083,newOnset=event['start']))
    print(json.dumps(dict(passed=True, cases=results, irregularTimestampFit=True,
                          isolatedNoiseRejected=True),indent=2))


if __name__ == '__main__':
    main()
