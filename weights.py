"""Download the Wav2Lip model weights on first use.

Files come from a pinned revision of a Hugging Face mirror and are verified
against their SHA-256, so every user gets byte-identical, known-good weights
without any manual download. Run directly to pre-fetch:  python weights.py
"""
import hashlib
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = 'camenduru/Wav2Lip'
REVISION = 'bfcd9263d1ccb60ab724f074e7c1b3555f6cb162'

WAV2LIP_GAN = os.path.join(ROOT, 'Wav2Lip-master', 'checkpoints',
                           'wav2lip_gan.pth')
S3FD = os.path.join(ROOT, 'Wav2Lip-master', 'face_detection', 'detection',
                    'sfd', 's3fd.pth')

# local path -> (path in repo, size in bytes, sha256)
FILES = {
    WAV2LIP_GAN: (
        'checkpoints/wav2lip_gan.pth', 435801865,
        'ca9ab7b7b812c0e80a6e70a5977c545a1e8a365a6c49d5e533023c034d7ac3d8'),
    S3FD: (
        'checkpoints/s3fd-619a316812.pth', 89843225,
        '619a31681264d3f7f7fc7a16a42cbbe8b23f31a256f75a366e5a1bcd59b33543'),
}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _download(dest, repo_path, size, sha):
    url = f'https://huggingface.co/{REPO}/resolve/{REVISION}/{repo_path}'
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + '.part'
    name = os.path.basename(dest)
    print(f'Downloading {name} ({size / 1e6:.0f} MB) from {REPO}...',
          flush=True)
    h = hashlib.sha256()
    done, last_pct = 0, -1
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, 'wb') as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            pct = done * 100 // size
            if pct >= last_pct + 10:
                print(f'  {name}: {pct}%', flush=True)
                last_pct = pct
    if h.hexdigest() != sha:
        os.remove(tmp)
        raise RuntimeError(f'{name}: checksum mismatch, download discarded')
    os.replace(tmp, dest)
    print(f'  {name}: verified', flush=True)


def ensure_weights(paths=None):
    """Download any missing/corrupt weight files among `paths` (default all)."""
    for dest in (paths or FILES):
        if dest not in FILES:
            continue  # user-supplied custom checkpoint; leave it alone
        repo_path, size, sha = FILES[dest]
        if os.path.isfile(dest) and os.path.getsize(dest) == size:
            continue
        _download(dest, repo_path, size, sha)


if __name__ == '__main__':
    ensure_weights()
    for p in FILES:
        ok = _sha256(p) == FILES[p][2]
        print(f'{"OK " if ok else "BAD"} {os.path.relpath(p, ROOT)}')
    sys.exit(0)
