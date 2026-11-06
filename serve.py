"""Local web app: viewer + "upload a face and generate" backend.

    python serve.py [port]   ->  http://localhost:8000/web/

Static files are served with HTTP Range support (needed for video seeking;
`python -m http.server` lacks it). The API runs pipeline.py as a background
job, one at a time, since the generators share working directories:

    POST /api/generate   multipart form: topic, details, minutes, voice,
                         reuse, face
    GET  /api/jobs/<id>      job status + log tail
    GET  /api/current        the running/most recent job, if any

Binds to 127.0.0.1 only: it runs jobs on this machine.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from email.parser import BytesParser
from email.policy import HTTP
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(ROOT, 'uploads')
VENV_PY = os.path.join(ROOT, '.venv', 'bin', 'python')
PYTHON = VENV_PY if os.path.exists(VENV_PY) else sys.executable
MAX_UPLOAD = 200 * 1024 * 1024
FACE_EXTS = {'.mp4', '.mov', '.m4v', '.webm', '.avi', '.jpg', '.jpeg', '.png'}

JOBS = {}
CURRENT = {'id': None}
LOCK = threading.Lock()


def _run_job(job, cmd):
    proc = subprocess.Popen(
        cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,  # text mode turns tqdm's \r into lines
        env={**os.environ, 'PYTHONUNBUFFERED': '1'},
    )
    for line in proc.stdout:
        line = line.rstrip()
        if not line or line.startswith('W1') or 'Warning' in line:
            continue
        job['log'].append(line)
        # remember the most useful failure reason (e.g. "Face not detected!")
        m = re.match(r'(?:\w+Error|Preflight failed): ?(.*)', line)
        if m and not line.startswith('RuntimeError: Command failed'):
            job['error'] = m.group(1) or line
        m = re.match(r'Step (\d)/(\d): (.*)', line)
        if m:
            job['step'] = f'Step {m.group(1)}/{m.group(2)} — {m.group(3)}'
        elif line.startswith(('Planning ', 'Got ', 'Converting slide',
                              'Voice: ')):
            job['step'] = 'Step 1/4 — ' + line
        elif line.startswith('Downloading '):
            job['step'] = line
    proc.wait()
    job['status'] = 'done' if proc.returncode == 0 else 'failed'
    job['finished'] = time.time()


VOICES = {f[:-4] for f in os.listdir(os.path.join(ROOT, 'slide_audio_gen',
                                                  'voices'))
          if f.endswith('.npy')}


def start_job(topic, details, minutes, voice, face_path, reuse):
    job_id = time.strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:4]
    cmd = [PYTHON, '-u', os.path.join(ROOT, 'pipeline.py'),
           '--topic', topic, '--details', details, '--minutes', str(minutes),
           '--voice', voice,
           '--face', face_path, '--run-name', job_id]
    if reuse:
        cmd.append('--skip-slides')
    job = {'id': job_id, 'topic': topic, 'status': 'running',
           'step': 'Starting…', 'error': None, 'log': deque(maxlen=300),
           'started': time.time(), 'finished': None}
    JOBS[job_id] = job
    CURRENT['id'] = job_id
    threading.Thread(target=_run_job, args=(job, cmd), daemon=True).start()
    return job


def parse_form(content_type, body):
    """multipart/form-data -> {name: str | (filename, bytes)}"""
    msg = BytesParser(policy=HTTP).parsebytes(
        f'Content-Type: {content_type}\r\n\r\n'.encode() + body)
    form = {}
    for part in msg.iter_parts():
        name = part.get_param('name', header='content-disposition')
        filename = part.get_filename()
        data = part.get_payload(decode=True) or b''
        form[name] = (filename, data) if filename else data.decode('utf-8')
    return form


def job_view(job):
    return {k: (list(v)[-40:] if k == 'log' else v) for k, v in job.items()}


class Handler(SimpleHTTPRequestHandler):
    # ---------- API ----------
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/current':
            job = JOBS.get(CURRENT['id'])
            return self._json(200, job_view(job) if job else None)
        if path.startswith('/api/jobs/'):
            job = JOBS.get(path.rsplit('/', 1)[-1])
            if not job:
                return self._json(404, {'error': 'unknown job'})
            return self._json(200, job_view(job))
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != '/api/generate':
            return self._json(404, {'error': 'not found'})
        length = int(self.headers.get('Content-Length') or 0)
        ctype = self.headers.get('Content-Type', '')
        if not ctype.startswith('multipart/form-data'):
            return self._json(400, {'error': 'Expected a form upload.'})
        if not 0 < length <= MAX_UPLOAD:
            self.rfile.read(min(length, MAX_UPLOAD))
            return self._json(400, {'error': 'Upload is empty or larger '
                                    'than 200 MB.'})
        form = parse_form(ctype, self.rfile.read(length))

        topic = str(form.get('topic', '')).strip()
        details = str(form.get('details', '')).strip()
        reuse = form.get('reuse') == '1'
        voice = str(form.get('voice', 'female'))
        filename, face = form.get('face') or ('', b'')
        ext = os.path.splitext(filename or '')[1].lower()
        try:
            minutes = float(form.get('minutes', 3))
        except ValueError:
            minutes = 0

        error = None
        if not topic or len(topic) > 200:
            error = 'Enter a topic (max 200 characters).'
        elif len(details) > 2000:
            error = 'Details are limited to 2000 characters.'
        elif not 0.5 <= minutes <= 15:
            error = 'Length must be between 0.5 and 15 minutes.'
        elif voice not in VOICES:
            error = 'Unknown voice.'
        elif ext not in FACE_EXTS or not face:
            error = 'Face must be a video (mp4/mov/webm) or image (jpg/png).'
        elif reuse and not os.path.exists(
                os.path.join(ROOT, 'slide_audio_gen', 'presentation.mp4')):
            error = 'No previous narration to reuse; untick "reuse".'
        if error:
            return self._json(400, {'error': error})

        with LOCK:
            running = JOBS.get(CURRENT['id'])
            if running and running['status'] == 'running':
                return self._json(409, {'error': 'A generation is already '
                                        'running.', 'job': running['id']})
            job_dir = os.path.join(UPLOAD_DIR, uuid.uuid4().hex)
            os.makedirs(job_dir)
            face_path = os.path.join(job_dir, 'face' + ext)
            with open(face_path, 'wb') as f:
                f.write(face)
            job = start_job(topic, details, minutes, voice, face_path, reuse)
        return self._json(202, job_view(job))

    # ---------- static files with Range support ----------
    def send_head(self):
        rng = self.headers.get('Range')
        path = self.translate_path(self.path)
        m = re.match(r'bytes=(\d*)-(\d*)$', rng or '')
        if not m or not os.path.isfile(path):
            return super().send_head()

        size = os.path.getsize(path)
        start_s, end_s = m.groups()
        if start_s:
            start = int(start_s)
            end = min(int(end_s), size - 1) if end_s else size - 1
        else:  # suffix range: last N bytes
            start, end = max(0, size - int(end_s or 0)), size - 1
        if start >= size or start > end:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.end_headers()
            return None

        f = open(path, 'rb')
        f.seek(start)
        self._remaining = end - start + 1
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(self._remaining))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        remaining = getattr(self, '_remaining', None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        self._remaining = None
        while remaining > 0:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)

    def end_headers(self):
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, fmt, *args):
        if '/api/' not in self.path:  # keep polling noise out of the console
            super().log_message(fmt, *args)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    os.chdir(ROOT)
    print(f'Serving on http://localhost:{port}/web/  (jobs run with {PYTHON})')
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
