(() => {
  'use strict';

  const body = document.body;
  const toggle = document.querySelector('#loreModeToggle');
  const cinematicView = document.querySelector('[data-lore-view="cinematic"]');
  const cinematicTargets = [...document.querySelectorAll('[data-lore-view="cinematic"]')];
  const readingView = document.querySelector('#reading-view');
  const content = document.querySelector('#reading-content');
  const navigation = document.querySelector('#readingNavigation');
  const hint = document.querySelector('#modeHint');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  if (!toggle || !cinematicView || !readingView || !content || !navigation) return;

  const heroTitle = document.querySelector('#hero-title');
  const heroArt = document.querySelector('.hero-character');
  heroTitle?.classList.add('shared-lore-title');
  heroArt?.classList.add('shared-lore-art');

  toggle.className = 'lore-mode-toggle';
  toggle.innerHTML = `
    <span aria-hidden="true" class="mode-icon mode-icon-cinematic">
      <svg focusable="false" viewBox="0 0 24 24"><rect height="14" rx="2" width="18" x="3" y="5"></rect><path d="M7 5v14M17 5v14M3 9h4M3 15h4M17 9h4M17 15h4"></path></svg>
    </span>
    <span aria-hidden="true" class="mode-toggle-thumb"></span>
    <span aria-hidden="true" class="mode-icon mode-icon-reading">
      <svg focusable="false" viewBox="0 0 24 24"><path d="M4 5.5A3.5 3.5 0 0 1 7.5 2H11v17H7.5A3.5 3.5 0 0 0 4 22V5.5Z"></path><path d="M20 5.5A3.5 3.5 0 0 0 16.5 2H13v17h3.5A3.5 3.5 0 0 1 20 22V5.5Z"></path></svg>
    </span>
    <span class="sr-only">Alternar entre modo Cinemático e modo Leitura</span>`;

  if (hint) {
    hint.innerHTML = '<strong>Quer todos os detalhes?</strong><span>Experimente o modo Leitura.</span>';
    hint.setAttribute('role', 'status');
    hint.setAttribute('aria-live', 'polite');
  }

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

  const storyMap = [
    { cinematic: '#yllith', reading: 'read-nascida-para-conquistar' },
    { cinematic: '#infancia', reading: 'read-a-infancia-de-sequoia-vermelha' },
    { cinematic: '#pais', reading: 'read-a-morte-de-seus-pais' },
    { cinematic: '#eco', reading: 'read-nem-tudo-era-perfeito' },
    { cinematic: '#mundo', reading: 'read-a-vontade-de-criar-algo-novo' },
    { cinematic: '#partida', reading: 'read-partida' },
    { cinematic: '#nome', reading: 'read-sequoia-vermelha-fica-para-tras' },
    { cinematic: '#futuro', reading: 'read-a-futura-lider' },
  ];

  let mounted = false;
  let loading = null;
  let currentMode = 'cinematic';
  let readingObserver = null;
  let hintTimer = 0;

  function escapeHtml(value) {
    return value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function inlineMarkup(value) {
    let html = escapeHtml(value);
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+?)\*/g, '<em>$1</em>');
    return html;
  }

  function headingText(value) {
    return value.replace(/\*+/g, '').trim();
  }

  function slugify(value) {
    return value
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  function parseStory(markdown) {
    const lines = markdown.replace(/\r\n?/g, '\n').split('\n');
    const chapters = [];
    let current = null;
    let paragraph = [];
    let quote = [];

    const flushParagraph = () => {
      if (!current || paragraph.length === 0) return;
      current.blocks.push({ type: 'p', text: paragraph.join(' ').trim() });
      paragraph = [];
    };

    const flushQuote = () => {
      if (!current || quote.length === 0) return;
      current.blocks.push({ type: 'quote', text: quote.join(' ').trim() });
      quote = [];
    };

    const flushBlocks = () => {
      flushParagraph();
      flushQuote();
    };

    for (const rawLine of lines) {
      const line = rawLine.trim();

      if (line.startsWith('# ')) {
        flushBlocks();
        const title = headingText(line.slice(2));
        current = { title, slug: slugify(title), blocks: [] };
        chapters.push(current);
        continue;
      }

      if (!current) continue;
      if (/^-{3,}$/.test(line)) {
        flushBlocks();
        continue;
      }
      if (!line) {
        flushBlocks();
        continue;
      }
      if (line.startsWith('>')) {
        flushParagraph();
        quote.push(line.replace(/^>\s?/, ''));
        continue;
      }
      if (quote.length) flushQuote();
      paragraph.push(line);
    }

    flushBlocks();
    return chapters;
  }

  function ensureReadingChrome() {
    if (readingView.querySelector('.reading-hero')) return;

    readingView.insertAdjacentHTML('afterbegin', `
      <div class="reading-progress" aria-hidden="true"><span id="reading-progress-bar"></span></div>
      <header class="reading-hero" id="reading-top">
        <div class="reading-hero-copy">
          <p class="reading-eyebrow">HISTÓRIA COMPLETA</p>
          <h1 class="reading-title shared-lore-title">Yllith.</h1>
          <p class="reading-subtitle">Nascida para <em>conquistar.</em></p>
          <p class="reading-deck">A história completa de Sequoia Vermelha — e da líder que escolheu se tornar.</p>
          <a class="reading-start" href="#read-nascida-para-conquistar">Começar a leitura <span aria-hidden="true">↓</span></a>
        </div>
        <div class="reading-hero-art">
          <div class="reading-halo" aria-hidden="true"></div>
          <img class="shared-lore-art" src="https://media.dnd.faysk.dev/lore/yllith/77ec8886af074c15310ec9f078c530d24d9fbe29cb1ff12fe9ab27b8b031538f/yllith.webp" alt="Yllith">
        </div>
      </header>`);
  }

  function renderStory(chapters) {
    content.replaceChildren();
    navigation.replaceChildren();

    for (const [index, chapter] of chapters.entries()) {
      const section = document.createElement('section');
      section.className = 'reading-chapter';
      section.id = `read-${chapter.slug}`;
      section.dataset.readingChapter = '';
      section.setAttribute('aria-labelledby', `${section.id}-title`);

      const eyebrow = document.createElement('p');
      eyebrow.className = 'reading-chapter-number';
      eyebrow.textContent = String(index + 1).padStart(2, '0');

      const title = document.createElement('h2');
      title.id = `${section.id}-title`;
      title.textContent = chapter.title;
      section.append(eyebrow, title);

      for (const block of chapter.blocks) {
        const element = document.createElement(block.type === 'quote' ? 'blockquote' : 'p');
        element.innerHTML = inlineMarkup(block.text);
        section.append(element);
      }

      content.append(section);

      const link = document.createElement('a');
      link.href = `#${section.id}`;
      link.dataset.readingLink = section.id;
      link.innerHTML = `<span>${String(index + 1).padStart(2, '0')}</span>${escapeHtml(chapter.title)}`;
      navigation.append(link);
    }

    if (chapters.length !== 10) {
      console.warn(`Yllith reading source has ${chapters.length} chapters; expected 10.`);
    }
  }

  async function mountReading() {
    if (mounted) return;
    if (loading) return loading;

    ensureReadingChrome();
    content.innerHTML = '<p class="reading-loading" role="status">Abrindo a história completa…</p>';
    loading = fetch('historia.md', { cache: 'no-store' })
      .then((response) => {
        if (!response.ok) throw new Error(`historia.md returned ${response.status}`);
        return response.text();
      })
      .then((markdown) => {
        const chapters = parseStory(markdown);
        if (!chapters.length) throw new Error('historia.md has no chapters');
        renderStory(chapters);
        mounted = true;
        observeReadingChapters();
      })
      .catch((error) => {
        console.error('Unable to render Yllith reading source', error);
        content.innerHTML = '<div class="reading-error"><h2>A história continua disponível</h2><p>O modo de leitura não conseguiu montar o texto agora.</p><a href="historia.md">Abrir a fonte narrativa em Markdown</a></div>';
        throw error;
      })
      .finally(() => {
        loading = null;
      });

    return loading;
  }

  function nearestCinematicEntry() {
    const headerOffset = 96;
    let best = storyMap[0];
    let bestDistance = Number.POSITIVE_INFINITY;

    for (const entry of storyMap) {
      const element = document.querySelector(entry.cinematic);
      if (!element) continue;
      const rect = element.getBoundingClientRect();
      const distance = rect.bottom < headerOffset
        ? Math.abs(rect.bottom - headerOffset) + 180
        : Math.abs(rect.top - headerOffset);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = entry;
      }
    }
    return best;
  }

  function nearestReadingEntry() {
    const hero = readingView.querySelector('.reading-hero');
    if (hero && window.scrollY < hero.offsetTop + hero.offsetHeight * 0.72) return storyMap[0];

    const chapters = [...readingView.querySelectorAll('[data-reading-chapter]')];
    const headerOffset = 110;
    let active = chapters[0];
    let bestDistance = Number.POSITIVE_INFINITY;

    for (const chapter of chapters) {
      const rect = chapter.getBoundingClientRect();
      const distance = rect.bottom < headerOffset
        ? Math.abs(rect.bottom - headerOffset) + 180
        : Math.abs(rect.top - headerOffset);
      if (distance < bestDistance) {
        bestDistance = distance;
        active = chapter;
      }
    }

    const activeIndex = chapters.indexOf(active);
    let best = null;
    for (const item of storyMap) {
      const target = document.getElementById(item.reading);
      const targetIndex = chapters.indexOf(target);
      if (targetIndex < 0 || activeIndex < 0) continue;
      const distance = Math.abs(targetIndex - activeIndex);
      if (!best || distance < best.distance) best = { item, distance };
    }
    return best?.item || storyMap[0];
  }

  function setToggleState(mode) {
    const reading = mode === 'reading';
    body.dataset.loreMode = mode;
    toggle.setAttribute('aria-checked', String(reading));
    toggle.setAttribute('aria-label', reading ? 'Ativar modo Cinemático' : 'Ativar modo Leitura');
    toggle.title = reading
      ? 'Modo Leitura — trocar para Cinemático'
      : 'Modo Cinemático — trocar para Leitura';
  }

  function jumpTo(element) {
    element?.scrollIntoView({ block: 'start', behavior: 'auto' });
  }

  function swapView(nextMode, entry) {
    if (nextMode === 'reading') {
      for (const element of cinematicTargets) element.hidden = true;
      readingView.hidden = false;
      readingView.removeAttribute('aria-hidden');
      setToggleState('reading');
      jumpTo(document.getElementById(entry.reading) || readingView.querySelector('#reading-top'));
      updateReadingProgress();
    } else {
      readingView.hidden = true;
      readingView.setAttribute('aria-hidden', 'true');
      for (const element of cinematicTargets) element.hidden = false;
      setToggleState('cinematic');
      jumpTo(document.querySelector(entry.cinematic) || cinematicView);
    }
    currentMode = nextMode;
  }

  async function changeMode(nextMode) {
    if (nextMode === currentMode || body.classList.contains('is-switching')) return;
    hideModeHint();
    body.classList.add('is-switching');
    toggle.setAttribute('aria-busy', 'true');

    try {
      if (nextMode === 'reading') await mountReading();
      const entry = currentMode === 'cinematic' ? nearestCinematicEntry() : nearestReadingEntry();

      if (!reduceMotion.matches && document.startViewTransition) {
        const transition = document.startViewTransition(() => swapView(nextMode, entry));
        await transition.finished;
      } else {
        swapView(nextMode, entry);
      }
    } catch (error) {
      console.error(error);
    } finally {
      body.classList.remove('is-switching');
      toggle.removeAttribute('aria-busy');
      toggle.focus({ preventScroll: true });
    }
  }

  function updateReadingCurrent(id) {
    for (const link of readingView.querySelectorAll('[data-reading-link]')) {
      link.classList.toggle('active', link.dataset.readingLink === id);
      if (link.dataset.readingLink === id) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    }
  }

  function observeReadingChapters() {
    if (!('IntersectionObserver' in window) || readingObserver) return;
    readingObserver = new IntersectionObserver((entries) => {
      if (currentMode !== 'reading') return;
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => Math.abs(a.boundingClientRect.top - 130) - Math.abs(b.boundingClientRect.top - 130));
      if (visible.length) updateReadingCurrent(visible[0].target.id);
    }, { rootMargin: '-18% 0px -68% 0px', threshold: 0 });

    for (const chapter of content.querySelectorAll('[data-reading-chapter]')) {
      readingObserver.observe(chapter);
    }
  }

  function updateReadingProgress() {
    if (currentMode !== 'reading') return;
    const bar = readingView.querySelector('#reading-progress-bar');
    if (!bar) return;
    const start = readingView.offsetTop;
    const end = start + readingView.scrollHeight - window.innerHeight;
    const progress = end <= start ? 1 : Math.min(1, Math.max(0, (window.scrollY - start) / (end - start)));
    bar.style.width = `${progress * 100}%`;
  }

  function hideModeHint() {
    if (!hint || hint.hidden) return;
    hint.hidden = true;
    if (hintTimer) window.clearTimeout(hintTimer);
    try {
      sessionStorage.setItem('yllith-mode-hint-seen', '1');
    } catch {}
  }

  toggle.addEventListener('click', () => {
    void changeMode(currentMode === 'cinematic' ? 'reading' : 'cinematic');
  });

  readingView.addEventListener('click', (event) => {
    const link = event.target.closest?.('[data-reading-link]');
    if (!link) return;
    const target = document.getElementById(link.dataset.readingLink || '');
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView({ block: 'start', behavior: reduceMotion.matches ? 'auto' : 'smooth' });
  });

  window.addEventListener('scroll', updateReadingProgress, { passive: true });
  window.addEventListener('resize', updateReadingProgress, { passive: true });

  try {
    if (hint && !sessionStorage.getItem('yllith-mode-hint-seen')) {
      window.setTimeout(() => {
        if (currentMode !== 'cinematic') return;
        hint.hidden = false;
        hintTimer = window.setTimeout(hideModeHint, 6500);
      }, 2600);
    }
  } catch {}

  hint?.addEventListener('click', hideModeHint);
  window.addEventListener('beforeunload', () => {
    if (hintTimer) window.clearTimeout(hintTimer);
  }, { once: true });

  setToggleState('cinematic');
})();
