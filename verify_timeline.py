"""Metadata bounds, version support and untouched-media invariants."""
from pathlib import Path
import struct
from timeline import limit_playback


def box(kind, payload):return struct.pack('>I4s',8+len(payload),kind)+payload


def movie(version=0, rate=65536):
    flags=bytes([version,0,0,0])
    stamp=b'\0'*(16 if version else 8)
    width=8 if version else 4
    duration=(6000).to_bytes(width,'big')
    mvhd=box(b'mvhd',flags+stamp+struct.pack('>I',1000)+duration+b'\0'*24)
    tkhd=box(b'tkhd',flags+stamp+struct.pack('>II',1,0)+duration+b'\0'*24)
    entries=b''
    for length,media in [(1000,-1),(5000,0)]:
        entries+=length.to_bytes(width,'big')+media.to_bytes(width,'big',signed=True)+struct.pack('>I',rate)
    edits=box(b'edts',box(b'elst',flags+struct.pack('>I',2)+entries))
    return box(b'ftyp',b'qt  ')+box(b'moov',mvhd+box(b'trak',tkhd+edits))+box(b'mdat',b'UNTOUCHED-MEDIA'*100)


def main():
    folder=Path(__file__).parent/'test-output/timeline-unit'
    folder.mkdir(parents=True,exist_ok=True)
    for version in (0,1):
        path=folder/f'version-{version}.mov'
        before=movie(version);path.write_bytes(before)
        result=limit_playback(path,2.5);after=path.read_bytes()
        assert result['trackDurations']==[2.5] and result['limitSeconds']==2.5
        assert len(before)==len(after)
        marker=before.index(b'mdat')
        assert before[marker:]==after[marker:]
        # Applying the same limit twice is stable.
        limit_playback(path,2.5);assert path.read_bytes()==after
    path=folder/'unsupported-rate.mov';before=movie(rate=131072);path.write_bytes(before)
    try:limit_playback(path,2.5)
    except ValueError:pass
    else:raise AssertionError('Unsupported speed accepted.')
    assert path.read_bytes()==before
    print('Timeline checks passed: 32/64-bit fields, empty edits, fixed file offsets, untouched media, idempotence and rejection before writes.')


if __name__=='__main__':main()
