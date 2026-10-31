# Prototype 05 verification — October 31, 2026

## Onset-based selection and batch processing

Clip selection now uses 0.5–1 seconds before movement onset rather than requiring the earlier detected set. The optional duration target can use a later original keyframe while retaining a minimum 0.5-second onset lead-in. The earlier set is informational and may be cut out.

On IMG_1708, onset remains 4.010417 seconds. Requested in: 3.260417 seconds. Export source coverage: 2.976250–5.202500 seconds. Measured duration: 2.226250 seconds; 267 original frames. Pre-onset lead-in: 1.034167 seconds after keyframe alignment. The earlier set at 2.042500 seconds is excluded. Content, decoded frames, relative timing and exit coverage pass. Output: ../outputs/start-video-editor/IMG_1708-onset.mov and IMG_1708-onset-report.json. Previous exports are retained.

Batch import supports multiple files, folders and drag/drop; a serial queue records progress, continues after per-file failures, holds uncertain onsets for review, and supports stop-after-current, resume and retry. The ZIP endpoint includes uniquely numbered clips and per-clip reports, plus a summary listing failed/review items. Only completed, verified exports are included. Queue cleanup removes its temporary jobs and prepared archives.

Passed `node verify_queue.cjs` (serial execution, folders/duplicates, failure continuation, review hold, stop/resume and export retry), `node verify_ui.cjs` (actual scripts with DOM/API fixtures, import/process/review/graph/ZIP/clear integration), `python verify_onset.py`, and `python verify.py` (real encoded clips, ZIP byte contents, duplicate names, summary and cleanup). `python verify_actual.py` verifies the user's real video using the new onset anchor. Python and JavaScript syntax checks pass. This does not constitute visual browser verification or a large real-video batch benchmark. All processing remains local.

## Previous onset verification

## Smoothed fitted-curvature onset

Onset now uses median despiking, a centered local quadratic fit over approximately 150 ms on actual source timestamps, and a sustained second-derivative crossing above robust quiet-baseline noise. The first significant lobe of a launch is selected; a fitted flat-to-rise change point corrects the apparent early response introduced by centered smoothing. First/second derivative arrays, thresholds and both crossing/refined times are included in the report. The graph can show raw motion, smoothed motion or signed curvature. This is image-motion curvature, not biomechanical acceleration.

`python verify_onset.py` passes deterministic noisy step and quadratic onset cases at 30, 60 and 120 fps, isolated-spike rejection, a quiet/noise-only signal and an irregularly sampled quadratic with a known second derivative. These known-onset examples recover 2.500 seconds; this is fixture validation, not a general accuracy guarantee. The encoded moving-box video detects 2.525 seconds against its programmed 2.500-second onset (previous threshold detector: 2.541667). The full export suite passes, including original frame content and relative timing.

On IMG_1708, onset moves from 4.152083 to 4.010417 seconds, approximately 142 ms (17 source frames) earlier. No manually labeled physical onset ground truth is available. The smoothed quiet/set estimate also changes to 2.042500 seconds. Preserving at least half a second before that estimate requires the earlier 0.992083-second keyframe, so this comparison export is 4.210417 seconds and correctly warns about the 3.5-second target. The app does not discard the set to meet the target. All 505 comparison frames pass content, decoded-frame, coverage and relative timing checks. Output: ../outputs/start-video-editor/IMG_1708-curvature.mov and IMG_1708-curvature-report.json. The previously working 3.21-second clip remains unchanged.

Python and browser-script syntax checks pass. New graph-selector interactions have not been visually verified. All processing remains local, and stream-copy export behavior is unchanged.

## Previous duration verification

## Tight duration regression

The default duration target uses the user's reported APOPT threshold of 3.5 seconds. With tight framing enabled, IMG_1708 exports from source 1.984167 to 5.194166 seconds, with measured video duration 3.210000 seconds and 385 original frames. Lead-in before the detected set is 0.550416 seconds. Detected exit coverage, packet content, full decoded frames and relative presentation timing all pass. Output: ../outputs/start-video-editor/IMG_1708-tight.mov; report: IMG_1708-tight-report.json. The previous 4.21-second export remains available.

Regression tests check that an eligible later keyframe is chosen, that the 0.5-second minimum lead-in is respected, and that an unreachable duration target does not force a cut into the set. All existing synthetic export checks pass. Browser script syntax passes; the new checkbox has not been tested interactively. The user confirmed the preceding corrected export works in APOPT; the tighter export has not yet been confirmed there.

## Previous timeline and decode verification

Passed Python and browser-script syntax checks, motion transition detection, no-motion fallback, and the isolated local API end-to-end tests in `verify.py` and `verify_actual.py`.

Synthetic source: 720 frames, 120 fps, H.264 MP4. Motion begins at 2.500 seconds and ends at 4.500 seconds. Detected start: 2.541667 seconds. Detected exit: 4.508333 seconds.

Requested selection: 1.710–4.610 seconds. Output duration: 3.133333 seconds. Export: 376 video packets. Content hashes match a contiguous source sequence; all decoded frames, relative presentation timing and requested coverage are verified. Export frame rate remains 120/1. A six-second source containing only one keyframe now trims to 4.633333 seconds, rather than retaining the whole source. Re-analysis verifies later motion still decodes.

Actual user-video regression: IMG_1708.MOV is 6.410 seconds and 769 frames. The previous clip (1).mov has a video start of 2.976250 seconds and an auxiliary metadata track retaining 6.411250 seconds. That inconsistent timeline is a plausible cause of importer failures; APOPT's analysis result has not been verified.

The revised export omits auxiliary timed tracks, retaining primary video and audio without re-encoding. Original stream/container metadata is retained in the local edit report. Presentation starts at zero and MP4/MOV use fast-start container layout. Tail trimming no longer expands to the next keyframe. The set detector measures its quiet baseline before the rising motion edge.

Actual detected set: 2.534583 seconds. Start: 4.152083 seconds. Exit: 5.194167 seconds. Requested in: 1.784583 seconds. Export source coverage: 0.992083–5.202500 seconds. Output duration: 4.210417 seconds; 505 frames. Video packet content, full decoded-frame hashes, relative presentation timing, and requested interval coverage all pass. Corrected clip: ../outputs/start-video-editor/IMG_1708-trimmed.mov. Its private metadata report is saved alongside it. Original files remain untouched.

Browser layout and interactive preview changes have not been visually verified. APOPT's public upload page was inspected; no athlete footage was submitted there. APOPT's actual pose-analysis result remains unverified. All athlete-video regression processing ran locally.
