(() => {
  'use strict';

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const clamp = (n, min, max) => Math.min(max, Math.max(min, n));
  const lerp = (a, b, t) => a + (b - a) * t;

  const progressBar = document.querySelector('#scrollProgress');
  const navItems = [...document.querySelectorAll('[data-nav]')];
  const sections = [...document.querySelectorAll('[data-section]')];
  const revealEls = [...document.querySelectorAll('[data-reveal]')];
  const sceneLayers = [...document.querySelectorAll('[data-scene] [data-layer]')];
  const dreamStage = document.querySelector('[data-scene="dream"]');
  const farewellStage = document.querySelector('[data-scene="farewell"]');
  const identityStage = document.querySelector('[data-identity]');
  const mapStage = document.querySelector('[data-map-stage]');
  const mapSurface = document.querySelector('[data-map-surface]');
  const heroCharacter = document.querySelector('[data-parallax="hero"]');

  // Progressive reveal. Content remains visible when JS is disabled because the
  // static HTML is complete; JS simply adds cinematic entry timing.
  if (!reduceMotion && 'IntersectionObserver' in window) {
    const revealObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          revealObserver.unobserve(entry.target);
        }
      }
    }, { rootMargin: '0px 0px -9% 0px', threshold: 0.08 });
    revealEls.forEach((el) => revealObserver.observe(el));
  } else {
    revealEls.forEach((el) => el.classList.add('is-visible'));
  }

  // Active chapter rail.
  if ('IntersectionObserver' in window) {
    const sectionObserver = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      const id = visible.target.dataset.section;
      navItems.forEach((item) => {
        if (item.dataset.nav === id) item.setAttribute('aria-current', 'true');
        else item.removeAttribute('aria-current');
      });
    }, { threshold: [0.18, 0.35, 0.55], rootMargin: '-20% 0px -48% 0px' });
    sections.forEach((section) => sectionObserver.observe(section));
  }

  let scrollY = window.scrollY;
  let ticking = false;

  function sceneProgress(el) {
    const rect = el.getBoundingClientRect();
    const vh = window.innerHeight || 1;
    return clamp((vh - rect.top) / (vh + rect.height), 0, 1);
  }

  function updateScroll() {
    ticking = false;
    scrollY = window.scrollY;

    const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const p = clamp(scrollY / maxScroll, 0, 1);
    progressBar.style.transform = `scaleX(${p})`;
    document.documentElement.style.setProperty('--scroll', p.toFixed(4));

    if (reduceMotion) return;

    // Scene layer parallax: element-local, not global, avoiding giant transforms
    // on long documents and keeping composition stable.
    sceneLayers.forEach((layer) => {
      const stage = layer.closest('[data-scene]');
      if (!stage) return;
      const rect = stage.getBoundingClientRect();
      if (rect.bottom < -200 || rect.top > window.innerHeight + 200) return;
      const local = sceneProgress(stage) - 0.5;
      const speed = Number(layer.dataset.speed || 0);
      const travel = Math.min(window.innerHeight * 0.22, 160);
      layer.style.setProperty('--sy', `${local * speed * travel * 5}px`);
    });

    if (dreamStage) {
      const dp = sceneProgress(dreamStage);
      // Apparition emerges gently as the viewer enters the frame, then settles.
      const opacity = clamp(lerp(0.42, 0.93, Math.sin(dp * Math.PI) * 0.95 + 0.08), 0.42, 0.93);
      dreamStage.style.setProperty('--spirit-opacity', opacity.toFixed(3));
    }

    if (farewellStage) {
      const fp = sceneProgress(farewellStage);
      const separation = lerp(-10, 18, fp);
      farewellStage.style.setProperty('--farewell-x', `${separation}px`);
    }

    if (identityStage) {
      const ip = sceneProgress(identityStage);
      const phase = clamp((ip - 0.22) / 0.56, 0, 1);
      const oldOpacity = lerp(1, 0.10, phase);
      const newOpacity = clamp((phase - 0.18) / 0.64, 0, 1);
      identityStage.style.setProperty('--old-opacity', oldOpacity.toFixed(3));
      identityStage.style.setProperty('--old-y', `${lerp(0, -28, phase)}px`);
      identityStage.style.setProperty('--old-scale', lerp(1, .94, phase).toFixed(3));
      identityStage.style.setProperty('--new-opacity', newOpacity.toFixed(3));
      identityStage.style.setProperty('--new-y', `${lerp(38, 0, newOpacity)}px`);
      identityStage.style.setProperty('--new-scale', lerp(.88, 1, newOpacity).toFixed(3));
      identityStage.style.setProperty('--slash-scale', clamp(phase * 1.35, 0, 1).toFixed(3));
    }

    if (mapStage && mapSurface) {
      const mp = sceneProgress(mapStage);
      mapSurface.style.setProperty('--hand-y', `${lerp(10, -5, mp)}px`);
      mapSurface.style.setProperty('--map-bg-y', `${lerp(-3, 5, mp)}px`);
    }
  }

  function requestTick() {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(updateScroll);
    }
  }

  window.addEventListener('scroll', requestTick, { passive: true });
  window.addEventListener('resize', requestTick, { passive: true });
  updateScroll();

  // Pointer parallax on the hero. Very small range: depth, not a carnival ride.
  if (!reduceMotion && heroCharacter && window.matchMedia('(pointer:fine)').matches) {
    const hero = document.querySelector('.hero');
    hero?.addEventListener('pointermove', (event) => {
      const rect = hero.getBoundingClientRect();
      const nx = (event.clientX - rect.left) / rect.width - 0.5;
      const ny = (event.clientY - rect.top) / rect.height - 0.5;
      heroCharacter.style.setProperty('--px', `${nx * -12}px`);
      heroCharacter.style.setProperty('--py', `${ny * -8}px`);
    }, { passive: true });
    hero?.addEventListener('pointerleave', () => {
      heroCharacter.style.setProperty('--px', '0px');
      heroCharacter.style.setProperty('--py', '0px');
    });
  }

  // Physical-map illusion: perspective and foreground hand depth respond to
  // pointer location. The motion is capped aggressively so text stays legible.
  if (!reduceMotion && mapSurface && window.matchMedia('(pointer:fine)').matches) {
    mapSurface.addEventListener('pointermove', (event) => {
      const rect = mapSurface.getBoundingClientRect();
      const x = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      const y = clamp((event.clientY - rect.top) / rect.height, 0, 1);
      const nx = x - .5;
      const ny = y - .5;
      mapSurface.style.setProperty('--map-ry', `${nx * 2.2}deg`);
      mapSurface.style.setProperty('--map-rx', `${ny * -1.6}deg`);
      mapSurface.style.setProperty('--hand-x', `${nx * 7}px`);
      mapSurface.style.setProperty('--map-bg-x', `${nx * -3}px`);
      mapSurface.style.setProperty('--mx', `${x * 100}%`);
      mapSurface.style.setProperty('--my', `${y * 100}%`);
    }, { passive: true });
    mapSurface.addEventListener('pointerleave', () => {
      mapSurface.style.setProperty('--map-ry', '0deg');
      mapSurface.style.setProperty('--map-rx', '0deg');
      mapSurface.style.setProperty('--hand-x', '0px');
      mapSurface.style.setProperty('--map-bg-x', '0px');
      mapSurface.style.setProperty('--mx', '50%');
      mapSurface.style.setProperty('--my', '45%');
    });
  }

  // Respect anchor focus without leaving visual focus rings to browser defaults
  // only; the stylesheet relies on :focus-visible below when available.
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Tab') document.documentElement.classList.add('using-keyboard');
  }, { once: true });
})();
(() => {
  'use strict';

  const toggle = document.querySelector('#loreModeToggle');
  const readingView = document.querySelector('#reading-view');
  const template = document.querySelector('#reading-source');
  const content = document.querySelector('#reading-content');
  const hint = document.querySelector('#modeHint');
  if (!toggle || !readingView || !template || !content) return;

  const cinematicTargets = [...document.querySelectorAll('[data-lore-view="cinematic"]')];
  const chapterRail = document.querySelector('.chapter-rail');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let mounted = false;
  let cinematicScrollY = 0;
  let hintTimer = 0;

  const cinematicToReading = {
    yllith: 'read-nascida-para-conquistar',
    infancia: 'read-a-infancia-de-sequoia-vermelha',
    pais: 'read-a-morte-de-seus-pais',
    eco: 'read-nem-tudo-era-perfeito',
    mundo: 'read-a-vontade-de-criar-algo-novo',
    partida: 'read-partida',
    nome: 'read-sequoia-vermelha-fica-para-tras',
    futuro: 'read-a-futura-lider',
  };

  function mountReading() {
    if (mounted) return;
    content.append(template.content.cloneNode(true));
    mounted = true;
  }

  function activeCinematicChapter() {
    const active = chapterRail?.querySelector('[aria-current="true"]');
    return active?.dataset.nav || 'yllith';
  }

  function updateToggle(reading) {
    toggle.setAttribute('aria-checked', reading ? 'true' : 'false');
    toggle.setAttribute('aria-label', reading ? 'Ativar modo Cinemático' : 'Ativar modo Leitura');
    toggle.title = reading ? 'Modo Leitura — trocar para Cinemático' : 'Modo Cinemático — trocar para Leitura';
  }

  function updateReadingCurrent(id) {
    document.querySelectorAll('[data-reading-link]').forEach((link) => {
      if (link.dataset.readingLink === id) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
  }

  function scrollToReading(id, replaceHash = true) {
    const target = document.getElementById(id);
    if (!target) return;
    const url = new URL(window.location.href);
    url.hash = id;
    if (replaceHash) history.replaceState(history.state, '', url.pathname + url.search + url.hash);
    else history.pushState(history.state, '', url.pathname + url.search + url.hash);
    target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
    updateReadingCurrent(id);
  }

  function enterReading() {
    cinematicScrollY = window.scrollY;
    const targetId = cinematicToReading[activeCinematicChapter()] || 'read-nascida-para-conquistar';
    mountReading();
    document.body.classList.add('reading-mode');
    cinematicTargets.forEach((el) => el.setAttribute('aria-hidden', 'true'));
    readingView.hidden = false;
    readingView.removeAttribute('aria-hidden');
    updateToggle(true);
    window.requestAnimationFrame(() => scrollToReading(targetId));
    if (hint) hint.hidden = true;
    sessionStorage.setItem('yllith-reading-mode-seen', '1');
  }

  function leaveReading() {
    document.body.classList.remove('reading-mode');
    cinematicTargets.forEach((el) => el.removeAttribute('aria-hidden'));
    readingView.hidden = true;
    readingView.setAttribute('aria-hidden', 'true');
    updateToggle(false);
    history.replaceState(history.state, '', window.location.pathname + window.location.search);
    window.scrollTo({ top: cinematicScrollY, behavior: reduceMotion ? 'auto' : 'smooth' });
  }

  toggle.addEventListener('click', () => {
    if (toggle.getAttribute('aria-checked') === 'true') leaveReading();
    else enterReading();
  });

  document.addEventListener('click', (event) => {
    const link = event.target.closest?.('[data-reading-link]');
    if (!link || !document.body.classList.contains('reading-mode')) return;
    const id = link.dataset.readingLink;
    if (!id) return;
    event.preventDefault();
    scrollToReading(id, false);
    const details = link.closest('details');
    if (details) details.open = false;
  });

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      if (!document.body.classList.contains('reading-mode')) return;
      const active = entries.filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (active) updateReadingCurrent(active.target.id);
    }, { rootMargin: '-18% 0px -62% 0px', threshold: [0, .08, .2] });
    const observeMounted = () => {
      if (!mounted) return;
      content.querySelectorAll('[data-reading-chapter]').forEach((chapter) => observer.observe(chapter));
    };
    toggle.addEventListener('click', () => window.requestAnimationFrame(observeMounted), { once: true });
  }

  if (hint && !sessionStorage.getItem('yllith-reading-mode-seen')) {
    hintTimer = window.setTimeout(() => {
      if (toggle.getAttribute('aria-checked') === 'false') {
        hint.hidden = false;
        window.setTimeout(() => { hint.hidden = true; }, 6500);
      }
    }, 5500);
    window.addEventListener('beforeunload', () => window.clearTimeout(hintTimer), { once: true });
  }
})();
