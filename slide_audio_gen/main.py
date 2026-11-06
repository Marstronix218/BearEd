"""Generate a narrated slide presentation for a topic.

Steps: OpenAI script (JSON, one call) -> slide images -> TTS audio per slide
-> per-slide videos -> presentation.mp4, plus timings.json describing when
each slide starts/ends in the narration (used by the web UI to sync slides
with the lip-synced video).

Usage: python main.py "<topic>" [--details "..."] [--minutes 3] [--voice male]
Env:   OPENAI_API_KEY (repo-root .env, env var, or config.json), OPENAI_MODEL (default gpt-4o-mini),
       KEEP_SLIDES=1 to keep slide images after cleanup.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import wave

import requests
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(HERE, 'audio')
MERGED_DIR = os.path.join(AUDIO_DIR, 'merged')
SLIDE_DIR = os.path.join(HERE, 'slides')
VIDEO_DIR = os.path.join(HERE, 'video')
FONT_PATH = os.path.join(HERE, 'fonts', 'times new roman bold.ttf')
PRESENTATION_PATH = os.path.join(HERE, 'presentation.mp4')
TIMINGS_PATH = os.path.join(HERE, 'timings.json')


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


load_dotenv(os.path.join(os.path.dirname(HERE), '.env'))
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

SLIDE_WIDTH, SLIDE_HEIGHT = 800, 600
FONT_SIZE = 60
OPENAI_ENDPOINT = 'https://api.openai.com/v1/chat/completions'


def natural_key(s):
    """Sort 'slide2' before 'slide10' and 'part_2' before 'part_10'."""
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]


def load_api_key():
    key = os.getenv('OPENAI_API_KEY')
    if key and not key.startswith('sk-your'):
        return key
    cfg = os.path.join(HERE, 'config.json')
    if os.path.exists(cfg):
        with open(cfg) as f:
            key = json.load(f).get('OPENAI_API_KEY')
    if not key or key.startswith('sk-your'):
        sys.exit('OpenAI API key missing: set OPENAI_API_KEY or fill '
                 'slide_audio_gen/config.json (see config.example.json).')
    return key


def chat(messages, json_mode=False):
    data = {'model': OPENAI_MODEL, 'messages': messages}
    if json_mode:
        data['response_format'] = {'type': 'json_object'}
    resp = requests.post(
        OPENAI_ENDPOINT, json=data, timeout=180,
        headers={'Authorization': 'Bearer ' + load_api_key()},
    )
    if resp.status_code != 200:
        sys.exit(f'OpenAI API error {resp.status_code}: {resp.text[:500]}')
    return resp.json()['choices'][0]['message']['content']


# measured SpeechT5 speaking rates (words/min); the male voice is faster
WORDS_PER_MINUTE = {'female': 165, 'male': 195}


def plan_length(minutes, voice='female'):
    """Slide count and words per slide for a target video length."""
    total_words = int(minutes * WORDS_PER_MINUTE.get(voice, 165))
    n_slides = max(2, min(12, round(minutes * 1.5) + 1))
    return n_slides, max(25, total_words // n_slides)


def generate_slides_json(topic, details='', minutes=3.0, voice='female'):
    """One OpenAI call -> {"slides": [{"slide", "title", "line"}]}."""
    n_slides, words = plan_length(minutes, voice)
    print(f'Planning {n_slides} slides x ~{words} words '
          f'(~{minutes:g} min of narration)...')
    focus = (f'\nThe presenter wants it to cover specifically:\n{details}\n'
             if details.strip() else '')
    prompt = f"""
You are an experienced teacher and presenter writing the spoken script for a
presentation about: {topic}
{focus}
Audience: high school students. Be clear and engaging; rhetorical questions
and light humor are welcome. The script is read aloud by a text-to-speech
engine, so:
- write numbers, symbols and abbreviations out as full words
- no markdown, bullet points, emojis or stage directions
- use normal sentence punctuation (. ? !)

Write exactly {n_slides} slides. Each slide's spoken text must be about
{words} words (this controls the video length, so stick to it closely).

Return JSON only, in this exact format:
{{"slides": [{{"slide": 1, "title": "<slide title, 5 words at most>",
"line": "<what the presenter says on this slide>"}}]}}
"""
    content = chat([{'role': 'user', 'content': prompt}], json_mode=True)
    slides_JSON = json.loads(content)
    if not slides_JSON.get('slides'):
        sys.exit(f'OpenAI returned no slides: {content[:500]}')
    # renumber 1..N so filenames are always consistent
    for i, s in enumerate(slides_JSON['slides'], start=1):
        s['slide'] = i
    total = sum(len(s['line'].split()) for s in slides_JSON['slides'])
    print(f'Got {len(slides_JSON["slides"])} slides, {total} words '
          f'(~{total / WORDS_PER_MINUTE.get(voice, 165):.1f} min)')
    return slides_JSON


def split_sentences(text):
    pieces = [p.strip() for p in re.split(r'(?<=[.!?])\s+', text.strip())]
    return [p for p in pieces if p]


def speak(synthesiser, speaker_embedding, text, slide_num):
    import numpy as np
    import soundfile as sf

    pieces = split_sentences(text)
    for i, piece in enumerate(pieces):
        print(f'  sentence {i + 1}/{len(pieces)}', end='\r')
        speech = synthesiser(
            piece, forward_params={'speaker_embeddings': speaker_embedding})
        audio = np.asarray(speech['audio'], dtype=np.float32).squeeze()
        peak = float(np.abs(audio).max()) or 1.0
        audio = audio * (0.9 / peak)  # loud but without clipping
        sf.write(os.path.join(AUDIO_DIR, f'slide{slide_num}_part_{i}.wav'),
                 audio, samplerate=speech['sampling_rate'], subtype='PCM_16')
    print()


VOICES_DIR = os.path.join(HERE, 'voices')


def available_voices():
    return sorted(f[:-4] for f in os.listdir(VOICES_DIR) if f.endswith('.npy'))


def convert_transcript_to_audio(slides_JSON, voice='female'):
    print('Loading text-to-speech model...')
    import torch
    from transformers import pipeline

    synthesiser = pipeline('text-to-speech', 'microsoft/speecht5_tts')
    # Speaker voice: a SpeechT5 x-vector stored in voices/<name>.npy
    import numpy as np
    xvec = np.load(os.path.join(VOICES_DIR, f'{voice}.npy'))
    print(f'Voice: {voice}')
    speaker_embedding = torch.tensor(xvec).unsqueeze(0)

    for slide in slides_JSON['slides']:
        print(f"Converting slide {slide['slide']} to audio...")
        speak(synthesiser, speaker_embedding, slide['line'], slide['slide'])
    print('All slides have been converted to audio')


def wrap_text(draw, text, font, max_width):
    lines, current = [], ''
    for word in text.split():
        trial = f'{current} {word}'.strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_slides(slides_JSON):
    """Render each slide title as black text centred on a white slide."""
    print('Generating slides...')
    margin = 40
    max_w = SLIDE_WIDTH - 2 * margin
    for slide in slides_JSON['slides']:
        img = Image.new('RGB', (SLIDE_WIDTH, SLIDE_HEIGHT), color='white')
        d = ImageDraw.Draw(img)
        size = FONT_SIZE
        while True:  # shrink until every wrapped line fits
            font = ImageFont.truetype(FONT_PATH, size)
            lines = wrap_text(d, slide['title'], font, max_w)
            if size <= 20 or all(
                    d.textlength(ln, font=font) <= max_w for ln in lines):
                break
            size -= 4
        line_h = size + 10
        y = (SLIDE_HEIGHT - line_h * len(lines)) / 2
        for line in lines:
            w = d.textlength(line, font=font)
            d.text(((SLIDE_WIDTH - w) / 2, y), line, font=font, fill='black')
            y += line_h
        img.save(os.path.join(SLIDE_DIR, f"slide_{slide['slide']}.png"))
    print('All slides have been generated')


def merge_audio_files():
    """Concatenate sentence clips into one wav per slide; return durations."""
    print('Merging audio files...')
    files = sorted((f for f in os.listdir(AUDIO_DIR) if f.endswith('.wav')),
                   key=natural_key)
    slides = {}
    for f in files:
        slides.setdefault(f.split('_')[0], []).append(f)

    durations = {}
    for slide_name, parts in slides.items():
        out_path = os.path.join(MERGED_DIR, slide_name + '.wav')
        with wave.open(out_path, 'wb') as out:
            params = None
            for part in parts:
                with wave.open(os.path.join(AUDIO_DIR, part), 'rb') as w:
                    if params is None:
                        params = w.getparams()
                        out.setparams(params)
                    out.writeframes(w.readframes(w.getnframes()))
        with wave.open(out_path, 'rb') as w:
            durations[int(slide_name[len('slide'):])] = (
                w.getnframes() / float(w.getframerate()))
    print('All audio files have been merged')
    return durations


def ffmpeg(*args):
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', *args]
    if subprocess.run(cmd).returncode != 0:
        sys.exit('ffmpeg failed: ' + ' '.join(cmd))


def generate_video(slides_JSON, durations):
    """Build one clip per slide (still image + narration) and concatenate.

    Each clip is cut to the exact narration length with -t; `-shortest`
    overshoots by ~1-2 s per clip with a looped image, which made slides
    drift out of sync with the video.
    """
    print('Generating video...')
    clips = []
    for slide in slides_JSON['slides']:
        n = slide['slide']
        clip = os.path.join(VIDEO_DIR, f'slide_{n}.mp4')
        dur = f'{durations[n]:.3f}'
        ffmpeg('-loop', '1', '-i', os.path.join(SLIDE_DIR, f'slide_{n}.png'),
               '-i', os.path.join(MERGED_DIR, f'slide{n}.wav'),
               '-c:v', 'libx264', '-tune', 'stillimage', '-pix_fmt', 'yuv420p',
               '-r', '25', '-c:a', 'aac', '-ar', '44100', '-ac', '1',
               '-t', dur, clip)
        clips.append(clip)

    list_path = os.path.join(VIDEO_DIR, 'video_list.txt')
    with open(list_path, 'w') as f:
        for clip in clips:
            f.write("file '" + clip.replace("'", "'\\''") + "'\n")
    ffmpeg('-f', 'concat', '-safe', '0', '-i', list_path, '-c', 'copy',
           PRESENTATION_PATH)


def write_timings(slides_JSON, durations):
    """Slide start/end times (seconds) within presentation.mp4."""
    t, timings = 0.0, []
    for slide in slides_JSON['slides']:
        d = durations.get(slide['slide'], 0.0)
        timings.append({
            'slide': slide['slide'],
            'image': f"slide_{slide['slide']}.png",
            'title': slide['title'],
            'line': slide['line'],
            'start': round(t, 3),
            'end': round(t + d, 3),
        })
        t += d
    with open(TIMINGS_PATH, 'w') as f:
        json.dump({'slides': timings}, f, indent=2)


def prepare_dirs():
    """Remove artifacts from previous runs so they never leak into this one."""
    for d in (AUDIO_DIR, SLIDE_DIR, VIDEO_DIR):
        shutil.rmtree(d, ignore_errors=True)
    for p in (PRESENTATION_PATH, TIMINGS_PATH):
        if os.path.exists(p):
            os.remove(p)
    for d in (AUDIO_DIR, MERGED_DIR, SLIDE_DIR, VIDEO_DIR):
        os.makedirs(d, exist_ok=True)


def cleanup():
    print('Cleaning up...')
    keep_slides = os.getenv('KEEP_SLIDES', '0') == '1'
    shutil.rmtree(AUDIO_DIR, ignore_errors=True)
    shutil.rmtree(VIDEO_DIR, ignore_errors=True)
    if not keep_slides:
        shutil.rmtree(SLIDE_DIR, ignore_errors=True)
    print(f'Cleanup complete. Slides preserved: {keep_slides}')


def main():
    import argparse
    ap = argparse.ArgumentParser(description='Generate a narrated slide deck')
    ap.add_argument('topic')
    ap.add_argument('--details', default='',
                    help='What the presentation should specifically cover')
    ap.add_argument('--minutes', type=float, default=3.0,
                    help='Target narration length in minutes (default 3)')
    ap.add_argument('--voice', default='female',
                    help='Narrator voice: a name from voices/*.npy '
                         '(female, male)')
    args = ap.parse_args()
    if args.voice not in available_voices():
        sys.exit(f'Unknown voice {args.voice!r}; choose from '
                 f'{", ".join(available_voices())}')
    if not 0.5 <= args.minutes <= 15:
        sys.exit('--minutes must be between 0.5 and 15')
    load_api_key()  # fail fast before loading any models
    prepare_dirs()

    print(f'Generating script for a presentation about {args.topic}...')
    slides_JSON = generate_slides_json(args.topic, args.details, args.minutes,
                                       args.voice)

    generate_slides(slides_JSON)
    convert_transcript_to_audio(slides_JSON, args.voice)
    durations = merge_audio_files()
    generate_video(slides_JSON, durations)
    write_timings(slides_JSON, durations)
    cleanup()
    print('All done! Presentation video has been generated')


if __name__ == '__main__':
    main()
