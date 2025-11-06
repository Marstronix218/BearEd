import argparse
import os
import shutil
import subprocess
import sys
import json
from datetime import datetime


ROOT = os.path.dirname(os.path.abspath(__file__))
SLIDE_GEN_DIR = os.path.join(ROOT, 'slide_audio_gen')
W2L_DIR = os.path.join(ROOT, 'Wav2Lip-master')
RESULTS_DIR = os.path.join(ROOT, 'results')


def run(cmd, cwd=None, env=None):
    print(f"$ {' '.join(cmd)}")
    completed = subprocess.run(cmd, cwd=cwd, env=env)
    if completed.returncode != 0:
        joined = ' '.join(cmd)
        raise RuntimeError(
            f"Command failed with code {completed.returncode}: {joined}"
        )


def ensure_dir(path, clear=False):
    if clear and os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def copytree(src, dst):
    if not os.path.exists(src):
        return
    ensure_dir(dst)
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)


def main():
    parser = argparse.ArgumentParser(
        description=(
            'End-to-end pipeline: generate slides+audio and lip-sync '
            'to a face video, then prepare web assets.'
        )
    )
    parser.add_argument(
        '--topic', required=True,
        help='Topic for the generated presentation transcript'
    )
    parser.add_argument(
        '--face', required=True,
        help='Path to the face video (mp4) used by Wav2Lip'
    )
    parser.add_argument(
        '--checkpoint', required=True,
        help='Path to Wav2Lip checkpoint (.pth)'
    )
    parser.add_argument(
        '--run-name', default=None,
        help='Optional name for this run. Defaults to timestamp'
    )
    args = parser.parse_args()

    # 1) Run slide+audio generation
    env = os.environ.copy()
    env['KEEP_SLIDES'] = '1'  # preserve slides for the web UI

    print('Step 1/3: Generating slides and narration audio...')
    run([sys.executable, 'main.py', args.topic], cwd=SLIDE_GEN_DIR, env=env)

    presentation_mp4 = os.path.join(SLIDE_GEN_DIR, 'presentation.mp4')
    slides_dir = os.path.join(SLIDE_GEN_DIR, 'slides')
    if not os.path.exists(presentation_mp4):
        raise FileNotFoundError(
            'presentation.mp4 not found. Slide/audio generation may have '
            'failed.'
        )
    if not os.path.isdir(slides_dir):
        raise FileNotFoundError(
            'slides/ directory not found. Ensure KEEP_SLIDES=1 and successful '
            'slide generation.'
        )

    # 2) Run Wav2Lip inference
    print('Step 2/3: Running Wav2Lip inference...')
    out_name = args.run_name or datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(RESULTS_DIR, out_name)
    latest_dir = os.path.join(RESULTS_DIR, 'latest')
    ensure_dir(run_dir, clear=True)

    lipsync_out = os.path.join(run_dir, 'lipsynced.mp4')
    run([
        sys.executable,
        os.path.join(W2L_DIR, 'inference.py'),
        '--checkpoint_path', args.checkpoint,
        '--face', os.path.abspath(args.face),
        '--audio', os.path.abspath(presentation_mp4),
        '--outfile', os.path.abspath(lipsync_out),
    ], cwd=W2L_DIR)

    # 3) Prepare web assets (copy slides and create manifest)
    print('Step 3/3: Preparing web assets...')
    slides_out = os.path.join(run_dir, 'slides')
    copytree(slides_dir, slides_out)

    # also copy presentation audio+slides video for reference
    shutil.copy2(
        presentation_mp4,
        os.path.join(run_dir, 'presentation_audio.mp4')
    )

    # Write manifest.json with relative paths from run_dir
    slide_files = sorted([
        f for f in os.listdir(slides_out)
        if f.lower().endswith(('.png', '.jpg', '.jpeg'))
    ])
    manifest = {
        'topic': args.topic,
        'generated_at': datetime.now().isoformat(),
        'video': 'lipsynced.mp4',
        'slides': [os.path.join('slides', f) for f in slide_files],
        'source_audio': 'presentation_audio.mp4'
    }
    with open(os.path.join(run_dir, 'manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=2)

    # Update results/latest for the web UI
    ensure_dir(latest_dir, clear=True)
    copytree(run_dir, latest_dir)

    print('\nDone!')
    print('Artifacts:')
    print(f"- Lipsynced video: {lipsync_out}")
    print(f"- Slides copied to: {slides_out}")
    print(f"- Manifest: {os.path.join(run_dir, 'manifest.json')}")
    print(
        f"- Web UI reads: "
        f"{os.path.join(RESULTS_DIR, 'latest', 'manifest.json')}"
    )


if __name__ == '__main__':
    main()
