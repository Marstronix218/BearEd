# BearEd

Turn a topic into a narrated, AI-presented lesson video. BearEd writes the script with OpenAI, renders slides, reads them aloud with text-to-speech, lip-syncs the narration onto a presenter's face with Wav2Lip, and plays it all back in a web app with the slides kept in sync with the presenter. Every presentation can be downloaded as a single MP4.

## Demo

https://github.com/user-attachments/assets/cdc64c60-b2e6-483d-a4a5-f6591fa63e10

## Features

- **Topic → presentation:** give a topic, optional details on what to cover, and a target length (1–8 minutes).
- **Any presenter:** upload a front-facing photo or a short video of a face; it is lip-synced to the narration.
- **Two narrator voices:** female or male.
- **Synced viewer:** the slides follow the video, and clicking a slide jumps the video to it. The script for the current slide is shown under the presenter.
- **MP4 export:** one 1280×720 video with the slide on the left and the presenter on the right.
- **No manual model downloads:** model weights are fetched and checksum-verified on first run.

## Requirements

- Python 3.11 (tested; 3.9–3.12 should work)
- [ffmpeg](https://ffmpeg.org/) on your `PATH` (`brew install ffmpeg` on macOS, `sudo apt install ffmpeg` on Ubuntu)
- An [OpenAI API key](https://platform.openai.com/api-keys). Each presentation makes one chat completion call (default model `gpt-4o-mini`), which costs a fraction of a cent.
- About 4 GB of free disk space (1.6 GB of Python packages plus 1.7 GB of models)

Tested on macOS on Apple silicon, running on the CPU. Linux should work too, and Wav2Lip uses an NVIDIA GPU automatically if one is available.

## Quick start

```bash
git clone https://github.com/Marstronix218/BearEd.git
cd BearEd

# 1. Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r slide_audio_gen/requirements.txt -r Wav2Lip-master/requirements-modern.txt

# 2. Configuration: put your OpenAI key in .env
cp .env.example .env
#    then edit .env and set OPENAI_API_KEY=sk-...

# 3. Start the app
python serve.py 8000
#    open http://localhost:8000/web/
```

The first generation downloads about 1.7 GB of models:
- the Wav2Lip lip-sync model (436 MB)
- the face detector (90 MB)
- the SpeechT5 text-to-speech model and vocoder (about 1.1 GB, from Hugging Face)

Later runs reuse them.

## Using the web app

1. Expand **Create a presentation**.
2. Enter a **Topic**, for example *Introduction to Graph Algorithms*.
3. Optionally add **Details**, for example *focus on BFS vs DFS with a maze example; skip the math proofs*.
4. Choose a **Video length** and a **Voice**.
5. Upload a **Presenter face**: a clear, front-facing photo (JPG/PNG) or a few seconds of video (MP4/MOV/WebM), up to 200 MB. Videos are looped to match the narration length.
6. Click **Generate**. Progress and a live log appear under the form.

When it finishes, the new presentation loads automatically.
- Play the video and the slides follow it.
- Click a thumbnail, use **Prev**/**Next**, or press ←/→ to jump.
- Click **Download MP4** to save the export.

To try a different face without rewriting the script, tick **Reuse the last narration**. That skips OpenAI and text-to-speech and only redoes the lip-sync.

Rough timings on an Apple-silicon CPU: about 1.5 minutes for a 1-minute video, and about 5 minutes for a 3-minute video. Lip-sync is the slow step. Target lengths are approximate (±15%) because the script writer doesn't hit word counts exactly.

> The server listens on `127.0.0.1` only and runs one generation at a time. It is meant for local use, not for exposing to the internet.

## Command line

The web app runs `pipeline.py`, which you can also call directly:

```bash
python pipeline.py --topic "Introduction to Graph Algorithms" \
  --details "Focus on BFS vs DFS with a maze example" \
  --minutes 3 --voice male --face path/to/face.jpg
```

| Flag | Meaning |
|---|---|
| `--topic` | Presentation topic (required) |
| `--details` | What the presentation should specifically cover |
| `--minutes` | Target length in minutes (default 3) |
| `--voice` | `female` (default) or `male` |
| `--face` | Face photo or video (default: `FACE_VIDEO` from `.env`) |
| `--checkpoint` | Custom Wav2Lip checkpoint (default: auto-downloaded `wav2lip_gan.pth`) |
| `--run-name` | Output folder name under `results/` (default: timestamp) |
| `--skip-slides` | Reuse the last script, slides and narration (no OpenAI call) |
| `--skip-lipsync` | Skip Wav2Lip; no face needed. Useful for testing the rest of the pipeline |
| `--w2l-args` | Extra Wav2Lip flags, e.g. `"--pads 0 20 0 0 --nosmooth"` |

Before doing any work, the pipeline checks that ffmpeg is installed, the OpenAI key is set and the face file exists. The model weights are downloaded if they are missing.

To fetch the weights ahead of time, run `python weights.py`.

## Configuration (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI key used to write the script | (required) |
| `OPENAI_MODEL` | Chat model | `gpt-4o-mini` |
| `WAV2LIP_CHECKPOINT` | Wav2Lip checkpoint path; downloaded automatically if it is the default path | `Wav2Lip-master/checkpoints/wav2lip_gan.pth` |
| `FACE_VIDEO` | Default face for command-line runs (the web app uses the uploaded face) | `assets/face.mp4` |
| `WAV2LIP_ARGS` | Extra Wav2Lip flags for every run | (empty) |

`.env`, `assets/` and `uploads/` are gitignored. Never commit your API key.

## How it works

```
topic + details + length + voice
  │
  ├─ 1. slide_audio_gen/main.py
  │     • OpenAI writes the script as JSON (title + narration per slide)
  │     • slide images are rendered (Pillow)
  │     • narration is synthesized sentence by sentence (SpeechT5)
  │     • per-slide clips are joined into presentation.mp4 (ffmpeg)
  │       and the start/end time of each slide goes to timings.json
  │
  ├─ 2. Wav2Lip: the face is shrunk to ≤720 px and lip-synced to the narration
  │
  ├─ 3. Export: slides | presenter, composited into a 1280×720 MP4 (ffmpeg)
  │
  └─ 4. results/<run>/ is written and copied to results/latest/ for the web app
```

Each run writes these to `results/<run>/`:

| File | Contents |
|---|---|
| `presentation_final.mp4` | The shareable export (slides + presenter) |
| `lipsynced.mp4` | The talking-presenter video |
| `presentation_audio.mp4` | Slides with narration, no presenter |
| `slides/` | Slide images |
| `manifest.json` | Topic, settings, and per-slide title, narration and `start`/`end` times, read by the web app |

## Project structure

```
serve.py                 web app server: static files + upload/generate API
pipeline.py              runs the steps above end to end
weights.py               downloads and verifies the Wav2Lip and face-detector weights
web/                     viewer and "Create a presentation" UI (plain HTML/CSS/JS)
slide_audio_gen/
  main.py                script, slides, narration, presentation.mp4, timings.json
  voices/                narrator voice embeddings (female.npy, male.npy)
  fonts/                 slide font (Tinos, SIL OFL)
Wav2Lip-master/          Wav2Lip (third-party, lightly patched; see License)
.env.example             configuration template
results/                 generated presentations (gitignored)
LICENSE                  MIT license for BearEd's own code
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Preflight failed: OpenAI key missing` | Set `OPENAI_API_KEY` in `.env`. |
| `OpenAI API error 401/429` | Check the key, and check that the OpenAI account has credit. |
| `Face not detected!` | Use a photo or video where one face is clearly visible and front-facing in every frame. |
| Mouth area looks off or cropped | Try `--w2l-args "--pads 0 20 0 0"`. For jittery video, add `--nosmooth`. |
| `ffmpeg not found` | Install ffmpeg and make sure it is on your `PATH`. |
| Video won't seek in the browser | Open the app through `python serve.py`, not `python -m http.server` (which lacks HTTP Range support). |
| `A generation is already running` | Wait for the current job to finish; its progress is shown in the form. |

## License

BearEd's own code is released under the [MIT License](LICENSE). It also bundles and downloads third-party components that keep their own licenses, listed below. The MIT License does not apply to them. **Wav2Lip is licensed for non-commercial use only, so a setup that includes it, as BearEd does by default, may not be used commercially.**

| Component | License / terms |
|---|---|
| BearEd's own code: everything outside `Wav2Lip-master/` except the items below | [MIT](LICENSE) |
| [Wav2Lip](https://github.com/Rudrabha/Wav2Lip) code and model weights (`Wav2Lip-master/`, `wav2lip_gan.pth`) | **Personal, research and non-commercial use only.** The models were trained on the LRS2 dataset, and any commercial use is prohibited. See `Wav2Lip-master/README.md`; commercial requests go to the Wav2Lip authors. |
| S3FD face detector (`s3fd.pth`, from [face-alignment](https://github.com/1adrianb/face-alignment)) | BSD 3-Clause |
| [SpeechT5 TTS](https://huggingface.co/microsoft/speecht5_tts) and [HiFi-GAN vocoder](https://huggingface.co/microsoft/speecht5_hifigan) | MIT |
| Narrator voices (`slide_audio_gen/voices/`) | Speaker embeddings derived from the [CMU ARCTIC](http://festvox.org/cmu_arctic/) speakers `slt` and `bdl`, via [Matthijs/cmu-arctic-xvectors](https://huggingface.co/datasets/Matthijs/cmu-arctic-xvectors). CMU ARCTIC is distributed under a permissive BSD-style license. |
| Slide font [Tinos](https://fonts.google.com/specimen/Tinos) (`slide_audio_gen/fonts/Tinos-Bold.ttf`) | SIL Open Font License 1.1 (`slide_audio_gen/fonts/OFL-Tinos.txt`) |
| Generated scripts | Produced with the OpenAI API, subject to [OpenAI's terms](https://openai.com/policies/terms-of-use). |

**Responsible use:** only upload faces you have permission to use. Don't use BearEd to impersonate real people or to make deceptive content, and make it clear to viewers that the presenter is AI-generated.
