# BearEd

Generate an AI-presented slide deck (text-to-speech + auto slides), lip-sync that narration to a face video with Wav2Lip, and view the result in a simple web UI: video on the left, slides on the right.

## Demo

https://github.com/user-attachments/assets/06e9f5ff-e452-497d-81df-0482c0e39932 

## What's inside

- `slide_audio_gen/` — creates a transcript from a topic using OpenAI, renders slide images from slide titles, synthesizes narration audio, and produces `presentation.mp4` (slides + audio). Requires your OpenAI API key.
- `Wav2Lip-master/` — open-source lip-sync engine. You provide the face video and the narration audio; it outputs a lip-synced video.
- `pipeline.py` — glue script that runs slide generation, then Wav2Lip, and prepares `results/` with a manifest for the web UI.
- `web/` — a tiny static site that reads `results/latest/manifest.json` and shows the lip-synced video alongside the slides.
- `results/` — output artifacts per run (gitignored). `results/latest/` always points to the most recent run.

## Prerequisites

- macOS (tested) with Python 3.9+ and ffmpeg installed
- An OpenAI API key (for slide & transcript generation)
- Wav2Lip pretrained checkpoint (.pth)

Install ffmpeg (one-time):

```bash
brew install ffmpeg
```

## Setup

1) Create a virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

2) Install slide generator deps

```bash
pip install -r slide_audio_gen/requirements.txt
```

3) Configure OpenAI key

```bash
cp slide_audio_gen/config.example.json slide_audio_gen/config.json
# Edit slide_audio_gen/config.json and place your OpenAI API key
```

4) Install Wav2Lip deps and model

- From `Wav2Lip-master/requirements.txt` install the dependencies (you may use updated versions; recent PyTorch works fine for inference on CPU). At minimum, ensure `torch`, `opencv-python`, `tqdm`, `numpy`, `librosa` are installed.
- Download a Wav2Lip checkpoint and the face detector:
  - Wav2Lip (or Wav2Lip + GAN) checkpoint `.pth` — see links in `Wav2Lip-master/README.md`.
  - Face detection model to `Wav2Lip-master/face_detection/detection/sfd/s3fd.pth` (see README links).

Example (minimal):

```bash
pip install torch torchvision torchaudio
pip install opencv-python tqdm numpy librosa
```

## Run the end-to-end pipeline

Provide a face video (any single-person talking head clip; the face should be clearly visible) and a topic. The pipeline will:

- Generate a transcript and slides for the topic
- Synthesize narration audio and build `presentation.mp4`
- Run Wav2Lip to lip-sync the narration to your face video
- Prepare `results/<run>/` and mirror it to `results/latest/`

```bash
python pipeline.py \
  --topic "Introduction to Graph Algorithms" \
  --face /absolute/path/to/your_face_video.mp4 \
  --checkpoint /absolute/path/to/wav2lip_checkpoint.pth
```

Outputs are written to:

- `results/<timestamp>/lipsynced.mp4` — final lip-synced talking-head video
- `results/<timestamp>/slides/` — generated slide images
- `results/<timestamp>/presentation_audio.mp4` — the slides-with-audio reference
- `results/<timestamp>/manifest.json` — consumed by the web UI
- `results/latest/` — a copy of the most recent run for convenience

Note: The slide generator downloads a TTS model the first time and calls OpenAI’s API; the first run can take several minutes.

## View in the web UI

Serve the repo root as static files (one of many options shown below), then open `http://localhost:8000/web/`.

```bash
# from repo root
python -m http.server 8000
# then open http://localhost:8000/web/
```

The page loads `results/latest/manifest.json`, shows the lip-synced video on the left, and a slide viewer on the right.

## Tips and notes

- Face video quality: Clear, front-facing videos work best. You can tweak Wav2Lip parameters (pads, resize, nosmooth) by editing `pipeline.py` to add extra flags to the inference call.
- Keeping artifacts: The slide generator used to delete intermediates. We’ve added support for `KEEP_SLIDES=1` (handled by `pipeline.py`) so the generated slides are preserved under `results/`.
- Checkpoints: Don’t commit `.pth` files to git (they’re large and licensed separately). Store them locally.
- Reproducibility: Different OpenAI generations will yield different slide content. Re-run with the same topic to regenerate.

## Repository structure

```
slide_audio_gen/         # slide + audio generation (OpenAI + TTS + ffmpeg)
Wav2Lip-master/          # upstream Wav2Lip (open-source)
web/                     # simple static web viewer
results/                 # run artifacts (gitignored, .gitkeep only)
pipeline.py              # orchestrates end-to-end flow
```

## Troubleshooting

- Module import errors (PyTorch/Transformers): Ensure your virtualenv is active and dependencies are installed. Apple Silicon users may prefer conda-forge PyTorch builds.
- ffmpeg not found: Install via Homebrew (`brew install ffmpeg`).
- Wav2Lip face detection error: Download `s3fd.pth` to `Wav2Lip-master/face_detection/detection/sfd/s3fd.pth`.
- Face not detected in some frames: Try `--pads 0 20 0 0` or `--nosmooth` in `Wav2Lip-master/inference.py` (you can add these flags in `pipeline.py`).

## License

- Your code in `slide_audio_gen/`, `web/`, and `pipeline.py` is your project code.
- `Wav2Lip-master/` is from the original authors and restricted to research/personal/non-commercial use. See its README for details. Do not use it commercially.
