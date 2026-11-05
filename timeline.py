"""Constrain MOV/MP4 playback using existing edit-list fields; never touch media bytes."""
import math
import struct


def limit_playback(path, seconds):
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Invalid playback duration.')
    with open(path, 'r+b') as stream:
        stream.seek(0, 2)
        total = stream.tell()
        def read(offset, length):
            stream.seek(offset)
            value = stream.read(length)
            if len(value) != length:
                raise ValueError('Truncated MOV metadata.')
            return value
        def boxes(start, end):
            result = []
            while start < end:
                if end-start < 8:
                    raise ValueError('Invalid MOV atom boundary.')
                size, kind = struct.unpack('>I4s', read(start, 8))
                header = 8
                if size == 1:
                    size = struct.unpack('>Q', read(start+8, 8))[0]
                    header = 16
                elif size == 0:
                    size = end-start
                if size < header or start+size > end:
                    raise ValueError('Invalid MOV atom size.')
                result.append((kind, start+header, start+size))
                start += size
            return result
        def child(nodes, kind):
            found = [node for node in nodes if node[0] == kind]
            if len(found) != 1:
                raise ValueError('Unsupported MOV playback metadata: '+kind.decode())
            return found[0]
        def version(node):
            value = read(node[1], 1)[0]
            if value not in (0, 1):
                raise ValueError('Unsupported MOV metadata version.')
            return value
        moov = child(boxes(0,total), b'moov')
        nodes = boxes(moov[1],moov[2])
        mvhd = child(nodes,b'mvhd')
        movie_version = version(mvhd)
        scale_offset = mvhd[1]+(20 if movie_version else 12)
        scale = struct.unpack('>I',read(scale_offset,4))[0]
        if not scale:
            raise ValueError('Invalid movie time scale.')
        ticks = max(1, round(seconds*scale))
        patches, durations = [], []
        def patch(offset, width, value):
            if value < 0 or value >= 1 << (width*8):
                raise ValueError('Playback duration overflows metadata field.')
            patches.append((offset, value.to_bytes(width,'big')))
        for trak in (node for node in nodes if node[0] == b'trak'):
            children = boxes(trak[1],trak[2])
            tkhd = child(children,b'tkhd')
            edts = child(children,b'edts')
            elst = child(boxes(edts[1],edts[2]),b'elst')
            edit_version = version(elst)
            count = struct.unpack('>I',read(elst[1]+4,4))[0]
            width, stride = (8,20) if edit_version else (4,12)
            if not 1 <= count <= 64 or elst[1]+8+count*stride > elst[2]:
                raise ValueError('Unsupported MOV edit list.')
            remaining, duration = ticks, 0
            for i in range(count):
                position = elst[1]+8+i*stride
                old = int.from_bytes(read(position,width),'big')
                rate = read(position+2*width,4)
                if rate != b'\x00\x01\x00\x00':
                    raise ValueError('Playback speed changes require manual review.')
                kept = min(old, remaining)
                remaining -= kept
                duration += kept
                patch(position,width,kept)
            track_version = version(tkhd)
            patch(tkhd[1]+(28 if track_version else 20),8 if track_version else 4,duration)
            durations.append(duration)
        if not durations:
            raise ValueError('No playback tracks found.')
        patch(scale_offset+4,8 if movie_version else 4,max(durations))
        # All validation completes before changing the generated output file.
        for offset, value in patches:
            stream.seek(offset)
            stream.write(value)
    return dict(limitSeconds=ticks/scale, trackDurations=[v/scale for v in durations],
                method='Existing MOV edit-list and movie/track duration fields only; media samples untouched')
