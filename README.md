# Start Lab — local prototype

Double-click **Start Editor.cmd**, then open http://127.0.0.1:8765. Requires Python 3 and FFmpeg. If FFmpeg is not installed, place `ffmpeg.exe` and `ffprobe.exe` anywhere under `tools/` (the server searches recursively). No Python packages are needed.

1. Choose a 1–10 second video (up to 12 seconds accepted, 512 MB maximum).
2. Choose a 0.5–1 second lead-in and run detection.
3. Review the motion graph and suggested in/out times. Use actual frame timestamps with the frame buttons, or type boundaries. Confirm that the pre-onset pose and the athlete's full exit are included.
4. Export, then download the clip and optional JSON edit report.

The default **Aim for ≤3.5 seconds** option uses the user's APOPT analysis threshold. If keyframe alignment makes the preferred selection too long, it tries a later original keyframe while retaining at least 0.5 seconds before movement onset. It may cut out the earlier detected set; it retains the onset lead-in, launch and exit. Disable this option to retain the preferred lead-in. If the measured export still exceeds 3.5 seconds, the interface warns you. Some recordings cannot meet both constraints without re-encoding, which this app does not do. Boundaries retain microsecond precision so rounding cannot accidentally select the previous keyframe.

## What is preserved

Onset detection first removes isolated spikes with a three-frame median, then fits a quadratic in a centered window of approximately 150 ms using the original frame timestamps. The fitted curve supplies its first and second derivatives directly, avoiding noisy numerical differencing. Sustained positive curvature must exceed the preceding quiet baseline by four robust noise deviations; a subsequent rise confirms the event without determining its timestamp. The earliest significant lobe in a launch is selected. A fitted flat-to-rise change point refines the timestamp against the despiked samples so centered smoothing does not falsely backdate a sharp edge. This is curvature of the image-motion score, not a physical measurement of athlete acceleration.

The graph selector shows raw motion, smoothed motion, or the signed second derivative (with a zero line). The local report includes fitted values, derivatives, the curvature threshold, crossing time and refined onset. If no reliable curvature event is found, the app explicitly requests manual review. The earlier set estimate is informational only and may be outside the exported clip. Clip selection uses movement onset, with at least 0.5 seconds of pre-onset footage when available. The app preserves that minimum instead of forcing the duration target.

The source is never modified. A separate 160×90 losslessly compressed grayscale MKV is decoded for motion scoring, retaining every source frame. Mean absolute pixel changes identify a quiet interval followed by a surge and a sustained low-motion exit. This is a heuristic, not pose estimation. Camera movement, background activity, compression noise, lighting changes, or initial stillness may confuse it. Review is required.

Export expands the requested start backwards to a keyframe. The end aligns to a source frame boundary, retaining any forward-reference frames needed by the decoder. It no longer expands to the next keyframe. Video and audio are copied without re-encoding or setting a new frame rate. The download is offered only after packet hashes, relative presentation timing, interval coverage, full decoded-frame hashes, and a near-zero playback start are verified. Actual measured duration is shown beside the original duration, and the exported clip has its own preview.

Only the primary video and audio tracks are included in the playback file. Auxiliary iPhone timed metadata tracks can retain the original duration and distort the trimmed timeline; they are excluded, with original stream and container metadata recorded in the local JSON report. Original video rotation and audio remain intact. Chapters are removed. Container timestamps are rebased for playback; absolute timestamps and file bytes are not preserved. Existing metadata may include device or location information.

Long GOPs can retain extra footage at the beginning. B-frame decode order can retain a few extra reference frames at the tail. The report contains actual source packet coverage and measured output duration. MP4/MOV retain their container type; other sources export as MKV. APOPT analysis itself still needs confirmation on the user's device; successful local decoding is not a guarantee of its pose-model results.

## Privacy and working files

The web interface and processing server run on this computer only. The server binds to 127.0.0.1, checks local hosts, and requires a per-session token for processing. No third-party fonts, scripts, analytics, accounts, remote APIs, or video uploads are used. Browser-to-server file transfer stays on loopback. Working originals, grayscale copies, and exports are held in a temporary local session folder and deleted at normal shutdown. Download anything you want to keep before stopping. A crash or forced termination can leave temporary files in the OS temporary directory (`apopt-starts-*`); delete those manually when no session is running. Downloaded files remain where you save them. No processing history is persisted by the app.

This prototype processes one operation at a time, with a three-minute timeout per FFmpeg operation. It is intended for a trusted single-user workstation, not deployment as a public server. Installing FFmpeg is a one-time external download; processing afterwards needs no network access.

## Verification

Run `python verify.py` from this folder; it starts and closes an isolated test server automatically. This generates a 120 fps moving-object fixture, tests motion onset and exit, analyzes it through the local API, exports a non-keyframe selection, downloads the result, and checks frame rate and original video packet verification. It also checks the no-motion fallback. This synthetic check does not establish accuracy on athlete footage. Browser layout and APOPT ingestion require separate review.

`python verify_onset.py` checks known step and gradual onsets at 30/60/120 fps with noise and isolated spikes, an irregular-timestamp quadratic with known second derivative, quiet-signal rejection, and the user's recorded motion signal. `python verify_actual.py` additionally processes `IMG_1708.MOV` and saves `IMG_1708-onset.mov` and its report to `outputs/start-video-editor/`, preserving earlier exports. It checks frame preservation, onset lead-in, exit coverage and the duration warning when the target is unreachable. This is a local regression test specific to this project.

## Batch processing

Use **Add videos** to select multiple files, **Add folder** to import a directory tree, or drag multiple files onto the preview. Non-video files and duplicate imports are skipped. Identically named videos in different subfolders remain separate queue items.

Choose the shared onset lead-in and duration target, then click **Process queue**. Videos are transferred over loopback, analyzed and verified one at a time; the app does not load the batch into memory as one large byte array. Settings are captured when processing starts. Keep the tab and local server open until it finishes. **Stop after current** finishes the active video before pausing; **Process queue** resumes pending entries. Files added later can be processed in the next run.

Reliable detections export automatically. Uncertain onsets remain in **Review**, and invalid files appear as **Failed** while processing continues. Use a row's **Review** button to inspect the graph and manually adjust/export that video. **Retry failed** returns failed entries to the pending queue, retaining successful analysis when only export failed. Completed entries offer individual downloads; **Download completed clips (.zip)** creates a single archive with numbered source filenames, per-video reports, and a JSON summary that also lists review/failed entries. Up to 10,000 queue entries can be listed in one archive. It contains only verified completed clips.

The queue is held in the current browser tab and is not restored after refresh. Sources, analysis copies, clips and prepared ZIPs consume local temporary disk space until **Clear queue & temporary files** or normal server shutdown. Download the results first. Prepared ZIPs are created on disk and streamed as downloads, with ZIP64 support; allow enough free disk space for both the working files and archive. File size limit remains 512 MB each; source duration remains at most 12 seconds.

Batch checks: `node verify_queue.cjs` verifies serial execution, duplicate handling, failure continuation, review holds, stop/resume and export retry. `node verify_ui.cjs` exercises the actual page scripts together with a DOM/API fixture. `python verify.py` verifies real exported ZIP contents, duplicate-name handling, summary entries and temporary-file cleanup. DOM fixture tests do not replace visual browser QA.
