(() => {
  

  const clamp = (n, min = 0, max = 1) => Math.min(max, Math.max(min, n));
  const progressBar = document.getElementById('progressBar');
  const siteChrome = document.getElementById('siteChrome');
  const menuToggle = document.getElementById('menuToggle');
  const chapterNav = document.getElementById('chapterNav');
  const seasonIndicator = document.getElementById('seasonIndicator');
  const seasonLabels = [...document.querySelectorAll('[data-season-label]')];
  const navLinks = [...document.querySelectorAll('.chapter-nav a')];
  const observedScenes = [...document.querySelectorAll('.scene-observer')];
  const seasonMap = { origem: 0, amor: 1 / 3, ruptura: 2 / 3, voz: 1 };
  let activeChapter = 'topo';
  let activeSeason = 'origem';
  let ticking = false;

  function setSeason(season) {
    if (!season || season === activeSeason) return;
    activeSeason = season;
    const y = seasonMap[season] ?? 0;
    if (seasonIndicator) seasonIndicator.style.top = `calc(${y * 100}% - ${y * 7}px)`;
    seasonLabels.forEach((label) => { label.classList.toggle('active', label.dataset.seasonLabel === season); });
  }

  function setChapter(chapter) {
    if (!chapter || chapter === activeChapter) return;
    activeChapter = chapter;
    navLinks.forEach((link) => {
      const target = link.getAttribute('href')?.slice(1);
      link.classList.toggle('active', target === chapter);
    });
  }

  function scrollState() {
    ticking = false;
    const doc = document.documentElement;
    const scrollMax = Math.max(1, doc.scrollHeight - window.innerHeight);
    const progress = clamp(window.scrollY / scrollMax);
    if (progressBar) progressBar.style.transform = `scaleX(${progress})`;
    siteChrome?.classList.toggle('scrolled', window.scrollY > 24);
  }

  window.addEventListener('scroll', () => {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(scrollState);
    }
  }, { passive: true });
  window.addEventListener('resize', scrollState, { passive: true });
  scrollState();

  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) entry.target.classList.add('visible');
    });
  }, { threshold: .12, rootMargin: '0px 0px -7% 0px' });
  document.querySelectorAll('.reveal').forEach((el) => { revealObserver.observe(el); });

  const sceneObserver = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    setSeason(visible.target.dataset.season);
    setChapter(visible.target.dataset.chapter);
  }, { threshold: [.18, .35, .55], rootMargin: '-18% 0px -42% 0px' });
  observedScenes.forEach((scene) => { sceneObserver.observe(scene); });
  seasonLabels[0]?.classList.add('active');

  menuToggle?.addEventListener('click', () => {
    const open = menuToggle.getAttribute('aria-expanded') !== 'true';
    menuToggle.setAttribute('aria-expanded', String(open));
    chapterNav?.classList.toggle('open', open);
    document.body.classList.toggle('menu-open', open && window.innerWidth <= 1100);
  });

  navLinks.forEach((link) => { link.addEventListener('click', () => {
    menuToggle?.setAttribute('aria-expanded', 'false');
    chapterNav?.classList.remove('open');
    document.body.classList.remove('menu-open');
  }); });

  const lightbox = document.getElementById('lightbox');
  const lightboxImage = document.getElementById('lightboxImage');
  const lightboxCaption = document.getElementById('lightboxCaption');
  const lightboxClose = document.getElementById('lightboxClose');

  document.querySelectorAll('.archive-item').forEach((item) => {
    item.addEventListener('click', () => {
      if (!lightbox || !lightboxImage || !lightboxCaption) return;
      const img = item.querySelector('img');
      lightboxImage.src = item.dataset.full || img?.src || '';
      lightboxImage.alt = img?.alt || '';
      lightboxCaption.textContent = item.querySelector('span')?.textContent || '';
      if (typeof lightbox.showModal === 'function') lightbox.showModal();
    });
  });

  lightboxClose?.addEventListener('click', () => lightbox?.close());
  lightbox?.addEventListener('click', (event) => {
    if (event.target === lightbox) lightbox.close();
  });
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && lightbox?.open) lightbox.close();
  });
})();
