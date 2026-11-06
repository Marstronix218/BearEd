import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

import weights


ROOT = os.path.dirname(os.path.abspath(__file__))
SLIDE_GEN_DIR = os.path.join(ROOT, 'slide_audio_gen')
W2L_DIR = os.path.join(ROOT, 'Wav2Lip-master')
S3FD_PATH = os.path.join(W2L_DIR, 'face_detection', 'detection', 'sfd',
                         's3fd.pth')
RESULTS_DIR = os.path.join(ROOT, 'results')


def load_dotenv(path):
    """Minimal .env loader (KEY=VALUE lines); real env vars take priority."""
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)


load_dotenv(os.path.join(ROOT, '.env'))


def from_root(path):
    return os.path.join(ROOT, path) if path and not os.path.isabs(path) else path


def natural_key(s):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]


def run(cmd, cwd=None, env=None):
    print(f"$ {' '.join(cmd)}")
    completed = subprocess.run(cmd, cwd=cwd, env=env)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with code {completed.returncode}: "
            f"{' '.join(cmd)}"
        )


def ensure_dir(path, clear=False):
    if clear and os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def preflight(args):
    """Fail fast with a clear message instead of minutes into the run."""
    problems = []
    if not shutil.which('ffmpeg'):
        problems.append('ffmpeg not found on PATH (brew install ffmpeg)')
    if not args.skip_slides:
        key = os.getenv('OPENAI_API_KEY', '')
        has_cfg = os.path.exists(os.path.join(SLIDE_GEN_DIR, 'config.json'))
        if (not key or key.startswith('sk-your')) and not has_cfg:
            problems.append('OpenAI key missing: set OPENAI_API_KEY in .env')
    if not args.skip_lipsync:
        if not args.face or not os.path.isfile(args.face):
            problems.append(f'--face video not found: {args.face}')
        if not args.checkpoint:
            args.checkpoint = weights.WAV2LIP_GAN
        if (not os.path.isfile(args.checkpoint)
                and os.path.abspath(args.checkpoint) not in weights.FILES):
            problems.append(f'--checkpoint not found: {args.checkpoint}')
    if problems:
        sys.exit('Preflight failed:\n  - ' + '\n  - '.join(problems))
    if not args.skip_lipsync:
        # fetch the default checkpoint / face detector on first use
        weights.ensure_weights([os.path.abspath(args.checkpoint), S3FD_PATH])


FACE_MAX = 720  # px; Wav2Lip only edits a 96px mouth crop, so more is waste
IMAGE_EXTS = ('.jpg', '.jpeg', '.png')


def ffmpeg(*args):
    run(['ffmpeg', '-y', '-loglevel', 'error', *args])


def prepare_face(face, work_dir):
    """Shrink the face input to fit in FACE_MAX x FACE_MAX (even dims).

    Phone photos/videos are often 2-4K, which makes Wav2Lip slow and the
    output video huge.
    """
    ext = os.path.splitext(face)[1].lower()
    fit = (f"scale='min({FACE_MAX},iw)':'min({FACE_MAX},ih)'"
           ':force_original_aspect_ratio=decrease,'
           'scale=trunc(iw/2)*2:trunc(ih/2)*2')
    if ext in IMAGE_EXTS:
        out = os.path.join(work_dir, 'face_input.png')
        ffmpeg('-i', face, '-vf', fit, '-frames:v', '1', out)
    else:
        out = os.path.join(work_dir, 'face_input.mp4')
        ffmpeg('-i', face, '-vf', fit, '-an', '-c:v', 'libx264',
               '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', out)
    return out


def export_mp4(slides_video, presenter_video, out):
    """One shareable 1280x720 MP4: slide (960x720) | presenter column."""
    if presenter_video is None:
        ffmpeg('-i', slides_video, '-vf',
               'scale=960:720,pad=1280:720:160:0:color=0x0f1115,setsar=1',
               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
               '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
               '-movflags', '+faststart', out)
        return
    graph = (
        '[0:v]scale=960:720,setsar=1[s];'
        # crop presenter to 3:4 around the centre, fit a 320px column
        "[1:v]crop='min(iw,ih*3/4)':'min(ih,iw*4/3)',scale=320:426,"
        'pad=320:720:0:(oh-ih)/2:color=0x0f1115,setsar=1[p];'
        '[s][p]hstack=inputs=2,format=yuv420p[v]'
    )
    ffmpeg('-i', slides_video, '-i', presenter_video,
           '-filter_complex', graph, '-map', '[v]', '-map', '1:a',
           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
           '-c:a', 'aac', '-b:a', '128k', '-shortest',
           '-movflags', '+faststart', out)


def build_manifest(topic, slides_out, timings_path, video_name):
    timings = {}
    if os.path.exists(timings_path):
        with open(timings_path) as f:
            timings = {t['image']: t for t in json.load(f)['slides']}

    slide_files = sorted(
        (f for f in os.listdir(slides_out)
         if f.lower().endswith(('.png', '.jpg', '.jpeg'))),
        key=natural_key,
    )
    slides = []
    for f in slide_files:
        t = timings.get(f, {})
        slides.append({
            'image': f'slides/{f}',
            'title': t.get('title', ''),
            'line': t.get('line', ''),
            'start': t.get('start'),
            'end': t.get('end'),
        })
    return {
        'topic': topic,
        'generated_at': datetime.now().isoformat(),
        'video': video_name,
        'source_audio': 'presentation_audio.mp4',
        'slides': slides,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            'End-to-end pipeline: generate slides+audio and lip-sync '
            'to a face video, then prepare web assets.'
        )
    )
    parser.add_argument('--topic', required=True,
                        help='Topic for the generated presentation')
    parser.add_argument('--details', default='',
                        help='What the presentation should specifically '
                             'cover (passed to the script writer)')
    parser.add_argument('--minutes', type=float, default=3.0,
                        help='Target video length in minutes (default 3)')
    parser.add_argument('--voice', default='female',
                        help='Narrator voice: female or male')
    parser.add_argument('--face', default=from_root(os.getenv('FACE_VIDEO')),
                        help='Face video (mp4) or image used by Wav2Lip '
                             '(default: FACE_VIDEO in .env)')
    parser.add_argument('--checkpoint',
                        default=from_root(os.getenv('WAV2LIP_CHECKPOINT')),
                        help='Path to Wav2Lip checkpoint (.pth) '
                             '(default: WAV2LIP_CHECKPOINT in .env)')
    parser.add_argument('--run-name', default=None,
                        help='Optional name for this run (default timestamp)')
    parser.add_argument('--skip-lipsync', action='store_true',
                        help='Skip Wav2Lip; the web UI plays the plain '
                             'slides+narration video instead')
    parser.add_argument('--skip-slides', action='store_true',
                        help='Reuse existing slide_audio_gen outputs '
                             '(presentation.mp4, slides/, timings.json)')
    parser.add_argument('--w2l-args', default=os.getenv('WAV2LIP_ARGS', ''),
                        help='Extra Wav2Lip flags, e.g. "--pads 0 20 0 0 '
                             '--resize_factor 2 --nosmooth"')
    args = parser.parse_args()
    preflight(args)

    presentation_mp4 = os.path.join(SLIDE_GEN_DIR, 'presentation.mp4')
    slides_dir = os.path.join(SLIDE_GEN_DIR, 'slides')
    timings_path = os.path.join(SLIDE_GEN_DIR, 'timings.json')

    # 1) Slide + narration generation
    if args.skip_slides:
        print('Step 1/4: Reusing existing slides and narration.')
    else:
        print('Step 1/4: Writing script, slides and narration...')
        env = os.environ.copy()
        env['KEEP_SLIDES'] = '1'  # preserve slides for the web UI
        run([sys.executable, 'main.py', args.topic,
             '--details', args.details, '--minutes', str(args.minutes),
             '--voice', args.voice],
            cwd=SLIDE_GEN_DIR, env=env)

    for path in (presentation_mp4, slides_dir):
        if not os.path.exists(path):
            raise FileNotFoundError(
                f'{path} not found. Slide/audio generation may have failed.')

    out_name = args.run_name or datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(RESULTS_DIR, out_name)
    ensure_dir(run_dir, clear=True)

    # 2) Lip-sync
    if args.skip_lipsync:
        print('Step 2/4: Skipping Wav2Lip (--skip-lipsync).')
        video_name = 'presentation_audio.mp4'
        presenter = None
    else:
        print('Step 2/4: Lip-syncing the presenter (slowest step)...')
        video_name = 'lipsynced.mp4'
        lipsync_out = os.path.join(run_dir, video_name)
        temp_dir = os.path.join(W2L_DIR, 'temp')
        ensure_dir(temp_dir)  # Wav2Lip writes here
        face = prepare_face(os.path.abspath(args.face), temp_dir)
        run([
            sys.executable, os.path.join(W2L_DIR, 'inference.py'),
            '--checkpoint_path', os.path.abspath(args.checkpoint),
            '--face', face,
            '--audio', os.path.abspath(presentation_mp4),
            '--outfile', os.path.abspath(lipsync_out),
            *args.w2l_args.split(),
        ], cwd=W2L_DIR)
        # inference.py doesn't propagate ffmpeg failures; check the output
        if not os.path.isfile(lipsync_out):
            raise RuntimeError('Wav2Lip finished but produced no video.')
        presenter = lipsync_out

    # 3) Shareable MP4
    print('Step 3/4: Exporting the final MP4...')
    export_name = 'presentation_final.mp4'
    export_mp4(presentation_mp4, presenter, os.path.join(run_dir, export_name))

    # 3) Web assets
    print('Step 4/4: Preparing web assets...')
    slides_out = os.path.join(run_dir, 'slides')
    shutil.copytree(slides_dir, slides_out)
    shutil.copy2(presentation_mp4,
                 os.path.join(run_dir, 'presentation_audio.mp4'))

    manifest = build_manifest(args.topic, slides_out, timings_path,
                              video_name)
    manifest.update(export=export_name, details=args.details,
                    minutes=args.minutes, voice=args.voice)
    if not any(s['start'] is not None for s in manifest['slides']):
        print('Warning: no timings.json found; slides will not auto-sync.')
    with open(os.path.join(run_dir, 'manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=2)

    latest_dir = os.path.join(RESULTS_DIR, 'latest')
    if run_dir != latest_dir:
        ensure_dir(latest_dir, clear=True)
        shutil.copytree(run_dir, latest_dir, dirs_exist_ok=True)

    print('\nDone!')
    print(f'- Video:    {os.path.join(run_dir, video_name)}')
    print(f'- Export:   {os.path.join(run_dir, export_name)}')
    print(f'- Slides:   {slides_out}')
    print(f"- Manifest: {os.path.join(run_dir, 'manifest.json')}")
    print('- View:     python serve.py 8000  ->  '
          'http://localhost:8000/web/')


if __name__ == '__main__':
    main()
