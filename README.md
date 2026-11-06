# Start Lab — local video preparation

Double-click **Start Editor.cmd**, then open http://127.0.0.1:8765. Requires Python 3 and FFmpeg; place `ffmpeg.exe` and `ffprobe.exe` under `tools/` if they are not on PATH. No Python packages are needed.

## Workflow

1. Import one video, several videos, or a folder tree. Inputs may be 1–10 seconds (up to 12 accepted), at most 512 MB each.
2. Choose 0.5–1 second before movement onset. The earlier set estimate is informational and may be outside the clip.
3. Detect onset and exit, then inspect the graph and pose. Review flagged cases manually.
4. Export one clip or process the queue and download a ZIP with reports.

**Keep exports ≤3.5 seconds** is enabled by default, based on the user's APOPT threshold. It is now enforced, not merely warned about. Copy-only cuts that cannot fit are held for review. Explicitly disabling the setting permits a longer export. Original frame timestamps determine boundaries; keyframe alignment can retain additional lead-in.

**Keep originals unchanged when already ≤3.5 seconds** is also enabled by default. For an automatic selection, an original MOV/MP4 with a valid near-zero playback start and total duration within the limit is copied byte for byte. SHA256 equality verifies the complete file, including hidden frames, all tracks, HDR and playback metadata. Manual changes to the in/out bounds request a trim instead; uncheck the option to force trimming a short original.

## Onset mathematics

A three-frame median removes isolated spikes. A local quadratic fit over approximately 150 ms on actual source timestamps smooths the signal and provides derivatives directly, including for variable-frame-rate footage.

The detector measures rolling RMS second-derivative energy over approximately 50 ms, considering both curvature signs. Significant energy above three robust quiet-baseline noise deviations, followed by a sustained motion increase, identifies candidate rise episodes. Lobes remain in the same episode until the signal returns to quiet for at least 120 ms. The strongest confirmed episode is selected, but its first departure anchors onset fitting, not its largest peak.

A robust change-point model then fits a drifting quiet baseline followed by a nonnegative rising segment. A grid search over the joining time, rise duration and power minimizes Huber residual loss on the despiked samples. Candidate times whose preceding samples are already persistently moving are rejected. This prevents a later peak from masquerading as the beginning. This is image-motion analysis, not a physical measurement of athlete acceleration.

If no reliable change point is found, onset is left unset and the queue holds the video for review. The app never substitutes the maximum-motion frame. Review remains necessary for camera movement, other people, gradual setup motion, lighting changes and poorly framed footage.

The graph selector offers raw motion, smoothed motion, signed second derivative, and **Onset change-point fit**. That last view overlays the fitted rise in amber and the quiet baseline in blue. Reports contain the fitted parameters, baseline noise, episode diagnostics, curvature crossing and refined onset. Centered smoothing's apparent early response is corrected by fitting the unsmoothed/despiked samples.

## Copy-only export and playback timelines

Sources are never modified. Analysis uses a separate 160×90 losslessly compressed grayscale MKV, retaining every source frame. Exports never re-encode, interpolate frames or set a new frame rate.

For a trimmed MOV/MP4, FFmpeg copies primary video and audio packets from an earlier source keyframe. The app limits the visible playback interval using the generated container's existing edit-list and movie/track duration fields. It does not alter media samples or move file offsets. Necessary encoded reference frames can remain stored outside the visible interval without becoming unwanted displayed frames. Unsupported metadata layouts or speed-changing edit lists are flagged for review.

Verification requires original packet hashes, preserved relative presentation timing, an uninterrupted sequence of original decoded-image hashes, coverage of the selected interval, and a near-zero playback start. It validates the visible timeline rather than exposing frames hidden by the original MOV. Media packet coverage and decoded visible coverage are recorded separately.

Recovery is bounded to 0.25 seconds of additional coded tail/head context. It never silently expands to the entire recording or an arbitrarily earlier keyframe. Candidates share a fixed visible tail; the shortest verified candidate in the bounded search is retained. The measured output must fit 3.5 seconds while that setting is enabled. Otherwise the queue holds the case for review, without re-encoding or creating a long fallback.

Trimmed exports keep the primary video and audio tracks. Auxiliary timed metadata and chapters are omitted to avoid stale timelines; original stream/container metadata is recorded in the report. Absolute container timestamps are rebased. Byte-identical original passthrough preserves all original tracks and metadata. Existing reports may contain device/location data; they remain local. MP4/MOV retain their container type; other inputs export as MKV with the same strict verification and bounded recovery, but without MOV edit-list handling. APOPT compatibility of each codec/container still requires checking on the user's device.

## Batch processing

**Add videos**, **Add folder**, or drag/drop imports many files. Unsupported files and duplicate imports are skipped; identically named videos in separate subfolders remain distinct. Processing is serial and captures shared settings when the queue starts. Files are streamed over loopback one at a time, not combined into one large in-memory upload.

Keep the page and server open. **Stop after current** finishes the active video before pausing; **Process queue** resumes pending entries. Uncertain onset, unsupported copy-only cuts and duration-limit cases are held in **Review**. Invalid files appear as **Failed** while the queue continues. Open a row to inspect or manually export it; **Retry failed** preserves successful analysis when only export failed.

The completed-clips ZIP contains numbered source filenames, individual edit reports and a JSON summary listing completed, review and failed cases. It includes only verified exports and supports ZIP64; up to 10,000 entries can be listed in one archive. Individual downloads are also available. The exported preview is loaded only on request to avoid loading every batch clip into browser memory.

The queue is not persisted across a page refresh. Temporary originals, dummy copies, clips and ZIPs consume local disk space until **Clear queue & temporary files** or normal server shutdown. Download wanted results first. Crashes/forced shutdown can leave `apopt-starts-*` folders in the OS temporary directory. Downloaded copies remain where saved.

## Privacy and verification

The server binds only to 127.0.0.1, checks hosts and requires a per-session token for processing. No remote video uploads, third-party scripts/fonts, analytics or accounts are used. No processing history is persisted. Installing FFmpeg requires a one-time download; all subsequent processing works offline. Intended for one trusted local user; each FFmpeg operation has a three-minute timeout.

Checks/Debugging:

- noisy step, quadratic, linear, oscillating and multi-lobe rises; isolated spikes, quiet signals and irregular timestamps. Known fixtures do not establish physical onset accuracy on all athlete footage.
- version 0/1 metadata fields, empty edits, unchanged media/file offsets, idempotence and rejection before metadata writes.
-  forced-remux hidden-frame handling, video samples and enforced duration limit.
- seven video 30/120 fps sources, the former tail-gap case, strict decoded coverage and fixed visible playback durations.
- synthetic 120 fps exports, explicit long-export opt-out, batch ZIP contents, duplicate names and cleanup through an isolated local HTTP server.
- queue behavior and actual page scripts with DOM/API fixtures, including review routing and export settings. Fixture tests do not replace visual browser QA.

Real-video regression artifacts are saved under `outputs/start-video-editor/` when the relevant script specifies it; intermediates remain in ignored `test-output/`.
