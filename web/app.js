(async function () {
  const manifestUrl = new URL('../results/latest/manifest.json', window.location.href).toString();
  let manifest;
  try {
    const res = await fetch(manifestUrl, { cache: 'no-store' });
    manifest = await res.json();
  } catch (e) {
    console.error('Failed to load manifest', e);
    document.getElementById('topic').textContent = 'No manifest found. Run the pipeline first.';
    return;
  }

  // Set topic & video
  document.getElementById('topic').textContent = `Topic: ${manifest.topic}`;
  const video = document.getElementById('video');
  video.src = `../results/latest/${manifest.video}`;

  // Slides
  const slides = manifest.slides || [];
  let idx = 0;
  const view = document.getElementById('slide-view');
  const counter = document.getElementById('counter');
  const prevBtn = document.getElementById('prev');
  const nextBtn = document.getElementById('next');
  const thumbs = document.getElementById('thumbs');

  function update() {
    if (!slides.length) {
      view.alt = 'No slides available';
      counter.textContent = '0 / 0';
      return;
    }
    view.src = `../results/latest/${slides[idx]}`;
    counter.textContent = `${idx + 1} / ${slides.length}`;
    Array.from(thumbs.querySelectorAll('img')).forEach((img, i) => {
      img.classList.toggle('active', i === idx);
    });
  }

  prevBtn.addEventListener('click', () => {
    idx = (idx - 1 + slides.length) % slides.length;
    update();
  });
  nextBtn.addEventListener('click', () => {
    idx = (idx + 1) % slides.length;
    update();
  });

  // Thumbnails
  slides.forEach((rel, i) => {
    const img = document.createElement('img');
    img.src = `../results/latest/${rel}`;
    img.alt = `Slide ${i + 1}`;
    img.addEventListener('click', () => {
      idx = i;
      update();
    });
    thumbs.appendChild(img);
  });

  update();
})();
