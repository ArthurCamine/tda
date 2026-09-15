(() => {
  const artDirectionStylesheet = document.createElement('link');
  artDirectionStylesheet.rel = 'stylesheet';
  artDirectionStylesheet.href = 'yllith-art-direction.css';
  artDirectionStylesheet.dataset.yllithArtDirection = 'directors-cut';
  document.head.append(artDirectionStylesheet);

  const hqFixesStylesheet = document.createElement('link');
  hqFixesStylesheet.rel = 'stylesheet';
  hqFixesStylesheet.href = 'yllith-hq-fixes.css';
  hqFixesStylesheet.dataset.yllithHqFixes = 'quality-first';
  document.head.append(hqFixesStylesheet);

  const hq = {
    hero: 'https://media.dnd.faysk.dev/lore/yllith/384d17c645ce923a5fc1bb6526bb213d50f9e5c4ea0a6e90e8320d6aa33cc73f/yllith-hq.png',
    journeyCharacter: 'https://media.dnd.faysk.dev/lore/yllith/2c810a111ee7b946d95aad965366c85bce1ce0880bf81e771d4f0a2ea063a1ec/yllith-jornada-hq.png',
    parents: 'https://media.dnd.faysk.dev/lore/yllith/99041fe8c1a46cb5be28e02e4a9f801ebe2835dd961a9b8be432cfddcee8d363/despedida-pais-hq.png',
    uncles: 'https://media.dnd.faysk.dev/lore/yllith/be6afe09d0092661d9e14374548bad5a28e31693a7dceae173e3ae1068c064ee/despedida-tios-hq.png',
    dream: 'https://media.dnd.faysk.dev/lore/yllith/c128f9446018b979aaa2080c3a068d21ede2426946c0ee7608c31385104ceb9b/sonho-hq.png',
    map: 'https://media.dnd.faysk.dev/lore/yllith/2b06647874d9fe8ac121979ad1336ef935ad79022d36629d72de286b65eea4b6/mapa-hq.png',
    journey: 'https://media.dnd.faysk.dev/lore/yllith/803e8e16fa7042dc4cb71a0708f22243e369f35981f86c0a50fba06edfe14c67/jornada-hq.png',
  };

  const useHqSource = (selector, src) => {
    const image = document.querySelector(selector);
    if (image instanceof HTMLImageElement) image.src = src;
  };

  useHqSource('.hero-character', hq.hero);
  useHqSource('#infancia .story-media img', hq.journeyCharacter);
  useHqSource('.farewell-bg', hq.parents);
  useHqSource('section[aria-labelledby="tios-title"] .story-media img:first-child', hq.uncles);
  useHqSource('.dream-stage > img:first-child', hq.dream);
  useHqSource('.map-background', hq.map);
  useHqSource('.departure-art img', hq.journey);
  useHqSource('.future-art img', hq.journeyCharacter);

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

  if (!progressBar) return;

  if (!reduceMotion && 'IntersectionObserver' in window) {
    const revealObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          revealObserver.unobserve(entry.target);
        }
      }
    }, { rootMargin: '0px 0px -9% 0px', threshold: 0.08 });
    revealEls.forEach((element) => {
      revealObserver.observe(element);
    });
  } else {
    revealEls.forEach((element) => {
      element.classList.add('is-visible');
    });
  }

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
    sections.forEach((section) => {
      sectionObserver.observe(section);
    });
  }

  let ticking = false;

  function sceneProgress(element) {
    const rect = element.getBoundingClientRect();
    const viewportHeight = window.innerHeight || 1;
    return clamp((viewportHeight - rect.top) / (viewportHeight + rect.height), 0, 1);
  }

  function updateScroll() {
    ticking = false;
    const scrollY = window.scrollY;
    const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const progress = clamp(scrollY / maxScroll, 0, 1);
    progressBar.style.transform = `scaleX(${progress})`;
    document.documentElement.style.setProperty('--scroll', progress.toFixed(4));

    if (reduceMotion) return;

    sceneLayers.forEach((layer) => {
      const stage = layer.closest('[data-scene]');
      if (!stage || getComputedStyle(layer).display === 'none') return;
      const rect = stage.getBoundingClientRect();
      if (rect.bottom < -200 || rect.top > window.innerHeight + 200) return;
      const local = sceneProgress(stage) - 0.5;
      const speed = Number(layer.dataset.speed || 0);
      const travel = Math.min(window.innerHeight * 0.15, 108);
      layer.style.setProperty('--sy', `${local * speed * travel * 3.2}px`);
    });

    if (identityStage) {
      const identityProgress = sceneProgress(identityStage);
      const phase = clamp((identityProgress - 0.22) / 0.56, 0, 1);
      const oldOpacity = lerp(1, 0.10, phase);
      const newOpacity = clamp((phase - 0.18) / 0.64, 0, 1);
      identityStage.style.setProperty('--old-opacity', oldOpacity.toFixed(3));
      identityStage.style.setProperty('--old-y', `${lerp(0, -28, phase)}px`);
      identityStage.style.setProperty('--old-scale', lerp(1, 0.94, phase).toFixed(3));
      identityStage.style.setProperty('--new-opacity', newOpacity.toFixed(3));
      identityStage.style.setProperty('--new-y', `${lerp(38, 0, newOpacity)}px`);
      identityStage.style.setProperty('--new-scale', lerp(0.88, 1, newOpacity).toFixed(3));
      identityStage.style.setProperty('--slash-scale', clamp(phase * 1.35, 0, 1).toFixed(3));
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

  if (!reduceMotion && heroCharacter && window.matchMedia('(pointer:fine)').matches) {
    const hero = document.querySelector('.hero');
    hero?.addEventListener('pointermove', (event) => {
      const rect = hero.getBoundingClientRect();
      const nx = (event.clientX - rect.left) / rect.width - 0.5;
      const ny = (event.clientY - rect.top) / rect.height - 0.5;
      heroCharacter.style.setProperty('--px', `${nx * -7}px`);
      heroCharacter.style.setProperty('--py', `${ny * -4}px`);
    }, { passive: true });
    hero?.addEventListener('pointerleave', () => {
      heroCharacter.style.setProperty('--px', '0px');
      heroCharacter.style.setProperty('--py', '0px');
    });
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Tab') document.documentElement.classList.add('using-keyboard');
  }, { once: true });
})();
