(function () {
  const base = new URL('../results/latest/', window.location.href);
  const $ = (id) => document.getElementById(id);

  const topicEl = $('topic');
  const video = $('video');
  const view = $('slide-view');
  const counter = $('counter');
  const caption = $('caption');
  const syncBadge = $('sync');
  const thumbs = $('thumbs');

  // ---------------- Viewer ----------------
  let slides = [];
  let synced = false;
  let idx = -1;

  function show(i) {
    if (!slides.length) {
      view.removeAttribute('src');
      view.alt = 'No slides available';
      counter.textContent = '0 / 0';
      caption.textContent = '';
      return;
    }
    if (i === idx) return;
    idx = i;
    const s = slides[i];
    view.src = new URL(s.image, base).toString();
    view.alt = s.title || `Slide ${i + 1}`;
    counter.textContent = `${i + 1} / ${slides.length}`;
    caption.textContent = s.line || '';
    thumbs.querySelectorAll('img').forEach((img, j) => {
      img.classList.toggle('active', j === i);
    });
  }

  // User navigation: move the slide and, when timings exist, seek the video.
  function goTo(i) {
    if (!slides.length) return;
    const n = (i + slides.length) % slides.length;
    show(n);
    if (synced) video.currentTime = slides[n].start + 0.1;
  }

  function slideAt(t) {
    for (let i = slides.length - 1; i >= 0; i--) {
      if (t >= slides[i].start) return i;
    }
    return 0;
  }

  const follow = () => { if (synced) show(slideAt(video.currentTime)); };
  video.addEventListener('timeupdate', follow);
  video.addEventListener('seeked', follow);
  $('prev').addEventListener('click', () => goTo(idx - 1));
  $('next').addEventListener('click', () => goTo(idx + 1));
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('video, input, textarea, select')) return;
    if (e.key === 'ArrowLeft') goTo(idx - 1);
    if (e.key === 'ArrowRight') goTo(idx + 1);
  });

  async function loadManifest(initial = false) {
    let manifest;
    try {
      const res = await fetch(new URL('manifest.json', base), { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      manifest = await res.json();
    } catch (e) {
      topicEl.textContent = 'Nothing generated yet. Create a presentation above.';
      $('create').open = true;
      return;
    }

    topicEl.textContent = `Topic: ${manifest.topic}`;
    if (initial) $('create').open = false; // viewer first when revisiting
    const dl = $('download');
    if (manifest.export) {
      dl.href = new URL(manifest.export, base).toString();
      const safe = (manifest.topic || 'presentation').replace(/[^\w-]+/g, '_').slice(0, 60);
      dl.download = `${safe}.mp4`;
      dl.hidden = false;
    } else {
      dl.hidden = true;
    }
    if (!$('gen-topic').value) $('gen-topic').value = manifest.topic || '';
    // cache-bust so a new run with the same filename reloads
    const stamp = encodeURIComponent(manifest.generated_at || Date.now());
    video.src = `${new URL(manifest.video, base)}?v=${stamp}`;

    // Older manifests list slides as plain path strings without timings.
    slides = (manifest.slides || []).map((s) =>
      typeof s === 'string' ? { image: s } : s
    ).map((s) => ({ ...s, image: `${s.image}?v=${stamp}` }));
    synced = slides.length > 0 && slides.every((s) => typeof s.start === 'number');
    syncBadge.textContent = synced ? 'Synced to video' : 'Manual (no timings)';
    syncBadge.classList.toggle('on', synced);

    thumbs.replaceChildren();
    slides.forEach((s, i) => {
      const img = document.createElement('img');
      img.src = new URL(s.image, base).toString();
      img.alt = s.title || `Slide ${i + 1}`;
      img.title = s.title || '';
      img.addEventListener('click', () => goTo(i));
      thumbs.appendChild(img);
    });
    idx = -1;
    show(0);
  }

  // ---------------- Generate ----------------
  const form = $('gen-form');
  const btn = $('gen-btn');
  const statusBox = $('gen-status');
  const stepEl = $('gen-step');
  const timeEl = $('gen-time');
  const logEl = $('gen-log');
  let pollTimer = null;

  function renderJob(job) {
    statusBox.hidden = false;
    if (job.status === 'running') $('create').open = true;
    statusBox.className = `gen-status ${job.status}`;
    const secs = Math.round(((job.finished || Date.now() / 1000) - job.started));
    timeEl.textContent = `${Math.floor(secs / 60)}m ${secs % 60}s`;
    if (job.status === 'running') stepEl.textContent = job.step;
    else if (job.status === 'done') stepEl.textContent = 'Done: showing the new presentation below.';
    else stepEl.textContent = `Failed: ${job.error || 'open the log for details.'}`;
    logEl.textContent = (job.log || []).join('\n');
    logEl.scrollTop = logEl.scrollHeight;
    btn.disabled = job.status === 'running';
  }

  function poll(jobId) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`, { cache: 'no-store' });
        const job = await res.json();
        renderJob(job);
        if (job.status === 'running') return poll(jobId);
        if (job.status === 'done') loadManifest();
      } catch (e) {
        poll(jobId); // server hiccup: keep trying
      }
    }, 1500);
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = $('gen-face').files[0];
    const topic = $('gen-topic').value.trim();
    if (!file || !topic) return;
    btn.disabled = true;
    statusBox.hidden = false;
    statusBox.className = 'gen-status running';
    stepEl.textContent = 'Uploading face…';
    timeEl.textContent = '';
    const body = new FormData();
    body.append('topic', topic);
    body.append('details', $('gen-details').value.trim());
    body.append('minutes', $('gen-minutes').value);
    body.append('voice', $('gen-voice').value);
    body.append('reuse', $('gen-reuse').checked ? '1' : '0');
    body.append('face', file);
    try {
      const res = await fetch('/api/generate', { method: 'POST', body });
      const data = await res.json();
      if (!res.ok) {
        statusBox.className = 'gen-status failed';
        stepEl.textContent = data.error || `Error ${res.status}`;
        btn.disabled = res.status === 409;
        if (data.job) poll(data.job);
        return;
      }
      renderJob(data);
      poll(data.id);
    } catch (err) {
      statusBox.className = 'gen-status failed';
      stepEl.textContent = 'Could not reach the server. Start it with: python serve.py';
      btn.disabled = false;
    }
  });

  // Resume showing a job that's still running after a page reload.
  async function resume() {
    try {
      const res = await fetch('/api/current', { cache: 'no-store' });
      if (!res.ok) return;
      const job = await res.json();
      if (job && job.status === 'running') { renderJob(job); poll(job.id); }
    } catch (e) {
      // static hosting without serve.py: viewer still works, generate won't
    }
  }

  loadManifest(true).then(resume);
})();
