(() => {
  const artDirectionStylesheet = document.createElement('link');
  artDirectionStylesheet.rel = 'stylesheet';
  artDirectionStylesheet.href = 'yllith-art-direction.css';
  artDirectionStylesheet.dataset.yllithArtDirection = 'directors-cut';
  document.head.append(artDirectionStylesheet);

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
    revealEls.forEach((element) => {
      revealObserver.observe(element);
    });
  } else {
    revealEls.forEach((element) => {
      element.classList.add('is-visible');
    });
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

    // Scene layer parallax is intentionally restrained. The sources are authored
    // as registered canvases, so depth must never destroy their alignment.
    sceneLayers.forEach((layer) => {
      const stage = layer.closest('[data-scene]');
      if (!stage) return;
      const rect = stage.getBoundingClientRect();
      if (rect.bottom < -200 || rect.top > window.innerHeight + 200) return;
      const local = sceneProgress(stage) - 0.5;
      const speed = Number(layer.dataset.speed || 0);
      const travel = Math.min(window.innerHeight * 0.15, 108);
      layer.style.setProperty('--sy', `${local * speed * travel * 3.2}px`);
    });

    if (dreamStage) {
      const dreamProgress = sceneProgress(dreamStage);
      const opacity = clamp(
        lerp(0.40, 0.90, Math.sin(dreamProgress * Math.PI) * 0.92 + 0.08),
        0.40,
        0.90,
      );
      dreamStage.style.setProperty('--spirit-opacity', opacity.toFixed(3));
    }

    if (farewellStage) {
      const farewellProgress = sceneProgress(farewellStage);
      const separation = lerp(-6, 10, farewellProgress);
      farewellStage.style.setProperty('--farewell-x', `${separation}px`);
    }

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

    if (mapStage && mapSurface) {
      const mapProgress = sceneProgress(mapStage);
      mapSurface.style.setProperty('--hand-y', `${lerp(7, -3, mapProgress)}px`);
      mapSurface.style.setProperty('--map-bg-y', `${lerp(-2, 3, mapProgress)}px`);
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

  // Pointer parallax on the hero: physical weight, not UI spectacle.
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

  // The map is a physical object. Motion is deliberately tiny so the two
  // authored layers (map + hands) remain registered to each other.
  if (!reduceMotion && mapSurface && window.matchMedia('(pointer:fine)').matches) {
    mapSurface.addEventListener('pointermove', (event) => {
      const rect = mapSurface.getBoundingClientRect();
      const x = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      const y = clamp((event.clientY - rect.top) / rect.height, 0, 1);
      const nx = x - 0.5;
      const ny = y - 0.5;
      mapSurface.style.setProperty('--map-ry', `${nx * 1.15}deg`);
      mapSurface.style.setProperty('--map-rx', `${ny * -0.8}deg`);
      mapSurface.style.setProperty('--hand-x', `${nx * 3.5}px`);
      mapSurface.style.setProperty('--map-bg-x', `${nx * -1.5}px`);
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

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Tab') document.documentElement.classList.add('using-keyboard');
  }, { once: true });
})();
