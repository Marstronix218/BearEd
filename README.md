# BearEd

Generate an AI-presented slide deck (text-to-speech + auto slides), lip-sync that narration to a face video with Wav2Lip, and view the result in a simple web UI: video on the left, slides on the right.

## Demo

https://github.com/user-attachments/assets/cdc64c60-b2e6-483d-a4a5-f6591fa63e10
 

## What's inside

- `slide_audio_gen/` — creates a transcript from a topic using OpenAI, renders slide images from slide titles, synthesizes narration audio, and produces `presentation.mp4` (slides + audio). Requires your OpenAI API key.
- `Wav2Lip-master/` — open-source lip-sync engine. You provide the face video and the narration audio; it outputs a lip-synced video.
- `pipeline.py` — glue script that runs slide generation, then Wav2Lip, and prepares `results/` with a manifest for the web UI.
- `web/` — a tiny static site that reads `results/latest/manifest.json` and shows the lip-synced video alongside the slides.
- `results/` — output artifacts per run (gitignored). `results/latest/` always points to the most recent run.

## Prerequisites

- macOS (tested) with Python 3.9+ and ffmpeg installed
- An OpenAI API key (for slide & transcript generation)

Install ffmpeg (one-time):

```bash
brew install ffmpeg
```

## Setup

1) Create the virtual environment and install everything (Python 3.11 tested)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r slide_audio_gen/requirements.txt -r Wav2Lip-master/requirements-modern.txt
```

(The upstream `Wav2Lip-master/requirements.txt` pins torch 1.1 / Python 3.6 and will not install; the bundled Wav2Lip code is patched for librosa ≥ 0.10 and torch ≥ 2.6.)

2) Create your `.env` (gitignored) and fill it in

```bash
cp .env.example .env
```

| Variable | What |
|---|---|
| `OPENAI_API_KEY` | OpenAI key for transcript + slide generation |
| `OPENAI_MODEL` | Chat model (default `gpt-4o-mini`) |
| `WAV2LIP_CHECKPOINT` | Path to `wav2lip.pth` or `wav2lip_gan.pth` |
| `FACE_VIDEO` | Talking-head clip or photo of the presenter (e.g. `assets/face.mp4`; `assets/` is gitignored) |
| `WAV2LIP_ARGS` | Extra Wav2Lip flags (default `--resize_factor 2`) |

3) Model weights download automatically

On the first lip-sync run, `wav2lip_gan.pth` (436 MB) and the `s3fd.pth` face detector (90 MB) are fetched from a pinned revision of the `camenduru/Wav2Lip` Hugging Face mirror and verified by SHA-256 (see `weights.py`; run `python weights.py` to pre-fetch). They are loaded with `torch.load(weights_only=True)`. The text-to-speech model downloads automatically too; the narrator voices (female, male) are bundled in `slide_audio_gen/voices/`.

## Use the web app (recommended)

```bash
source .venv/bin/activate
python serve.py 8000        # open http://localhost:8000/web/
```

In **Create a presentation**, enter a topic, optionally describe what it should cover (**Details**), pick a **Video length** (1–8 min) and **Voice** (female/male), upload a face photo or short video, and click **Generate**. Progress and logs show in the page; when it finishes the new presentation loads automatically and **Download MP4** saves a single 1280×720 video (slide on the left, talking presenter on the right). Tick *Reuse the last narration* to redo only the face (no OpenAI call). One generation runs at a time; the server listens on localhost only.

Rough timing on an Apple-silicon CPU: ~90 s for a 1-minute video, ~5 min for 3 minutes. The face input is shrunk to fit 720 px before lip-sync.

## Run the pipeline from the command line

Provide a face video (any single-person talking head clip; the face should be clearly visible) and a topic. The pipeline will:

- Generate a transcript and slides for the topic
- Synthesize narration audio and build `presentation.mp4`
- Run Wav2Lip to lip-sync the narration to your face video
- Prepare `results/<run>/` and mirror it to `results/latest/`

```bash
python pipeline.py --topic "Introduction to Graph Algorithms" \
  --details "Focus on BFS vs DFS with a maze example" --minutes 3
# --face / --checkpoint override the .env values if given
```

Useful flags:

- `--skip-lipsync` — no Wav2Lip needed (no checkpoint/face video); the UI plays the slides+narration video. Good for testing the rest of the pipeline.
- `--skip-slides` — reuse the last slide/narration output (skip OpenAI + TTS), e.g. to retry Wav2Lip with different settings.
- `--w2l-args "--pads 0 20 0 0 --resize_factor 2 --nosmooth"` — pass extra flags to Wav2Lip.

The pipeline runs a preflight check (ffmpeg, OpenAI key, face video, checkpoint, `s3fd.pth`) before doing any work.

Outputs are written to:

- `results/<timestamp>/presentation_final.mp4` — the shareable export (slides + presenter, 1280×720)
- `results/<timestamp>/lipsynced.mp4` — lip-synced talking-head video
- `results/<timestamp>/slides/` — generated slide images
- `results/<timestamp>/presentation_audio.mp4` — the slides-with-audio reference
- `results/<timestamp>/manifest.json` — consumed by the web UI; each slide has `start`/`end` times (seconds) in the narration, taken from `slide_audio_gen/timings.json`
- `results/latest/` — a copy of the most recent run for convenience

Note: The slide generator downloads a TTS model the first time and calls OpenAI’s API; the first run can take several minutes.

## View in the web UI

```bash
# from repo root
python serve.py 8000
# then open http://localhost:8000/web/
```

Use `serve.py` rather than `python -m http.server`: the latter does not support HTTP Range requests, so the browser cannot seek in the video.

The page loads `results/latest/manifest.json`, shows the lip-synced video on the left and the slides on the right. The slides follow the video as it plays. Clicking a thumbnail, Prev/Next, or the ←/→ keys jumps the video to that slide. The narration for the current slide is shown under it.

## Tips and notes

- Face video quality: Clear, front-facing videos work best. Tweak Wav2Lip with `--w2l-args`.
- Keeping artifacts: `pipeline.py` sets `KEEP_SLIDES=1` so slides survive cleanup; each new run clears the previous run's intermediates first.
- Checkpoints: Don’t commit `.pth` files to git (they’re large and licensed separately). Store them locally.
- Reproducibility: Different OpenAI generations will yield different slide content. Re-run with the same topic to regenerate.

## Repository structure

```
slide_audio_gen/         # slide + audio generation (OpenAI + TTS + ffmpeg)
Wav2Lip-master/          # upstream Wav2Lip (open-source)
web/                     # simple static web viewer
results/                 # run artifacts (gitignored, .gitkeep only)
pipeline.py              # orchestrates end-to-end flow
serve.py                 # web app: viewer + upload/generate API
weights.py               # auto-download + checksum of model weights
```

## Troubleshooting

- Module import errors (PyTorch/Transformers): Ensure your virtualenv is active and dependencies are installed. Apple Silicon users may prefer conda-forge PyTorch builds.
- ffmpeg not found: Install via Homebrew (`brew install ffmpeg`).
- "Face not detected": use a clip where the face is clearly visible and front-facing in every frame.
- Face not detected in some frames: Try `--w2l-args "--pads 0 20 0 0 --nosmooth"`.
- Wav2Lip is slow on CPU: try `--w2l-args "--resize_factor 2"` and a short face clip (it is looped to the narration length).

## License

- Your code in `slide_audio_gen/`, `web/`, and `pipeline.py` is your project code.
- `Wav2Lip-master/` is from the original authors and restricted to research/personal/non-commercial use. See its README for details. Do not use it commercially.
