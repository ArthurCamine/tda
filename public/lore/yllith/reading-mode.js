(() => {
  'use strict';

  const toggle = document.querySelector('#loreModeToggle');
  const readingView = document.querySelector('#reading-view');
  const content = document.querySelector('#reading-content');
  const navigation = document.querySelector('#readingNavigation');
  const hint = document.querySelector('#modeHint');
  if (!toggle || !readingView || !content || !navigation) return;

  const cinematicTargets = [...document.querySelectorAll('[data-lore-view="cinematic"]')];
  const chapterRail = document.querySelector('.chapter-rail');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
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

  let mounted = false;
  let loading = null;
  let cinematicScrollY = 0;
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
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    return html;
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
        const title = line.slice(2).trim();
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
      link.textContent = chapter.title;
      navigation.append(link);
    }

    if (chapters.length !== 10) {
      console.warn(`Yllith reading source has ${chapters.length} chapters; expected 10.`);
    }
  }

  async function mountReading() {
    if (mounted) return;
    if (loading) return loading;

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
        content.innerHTML = '';
        const fallback = document.createElement('div');
        fallback.className = 'reading-error';
        fallback.innerHTML = '<h2>A história continua disponível</h2><p>O modo de leitura não conseguiu montar o texto agora.</p><a href="historia.md">Abrir a fonte narrativa em Markdown</a>';
        content.append(fallback);
        throw error;
      })
      .finally(() => {
        loading = null;
      });

    return loading;
  }

  function activeCinematicChapter() {
    const active = chapterRail?.querySelector('[aria-current="true"]');
    return active?.dataset.nav || 'yllith';
  }

  function updateToggle(reading) {
    toggle.setAttribute('aria-checked', reading ? 'true' : 'false');
    toggle.setAttribute('aria-label', reading ? 'Ativar modo Cinemático' : 'Ativar modo Leitura');
    toggle.title = reading
      ? 'Modo Leitura — trocar para Cinemático'
      : 'Modo Cinemático — trocar para Leitura';
  }

  function updateReadingCurrent(id) {
    document.querySelectorAll('[data-reading-link]').forEach((link) => {
      if (link.dataset.readingLink === id) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
  }

  function scrollToReading(id, pushHash = false) {
    const target = document.getElementById(id);
    if (!target) return;
    const url = new URL(window.location.href);
    url.hash = id;
    const nextUrl = url.pathname + url.search + url.hash;
    if (pushHash) history.pushState(history.state, '', nextUrl);
    else history.replaceState(history.state, '', nextUrl);
    target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
    updateReadingCurrent(id);
  }

  function observeReadingChapters() {
    if (!('IntersectionObserver' in window) || readingObserver) return;
    readingObserver = new IntersectionObserver((entries) => {
      if (!document.body.classList.contains('reading-mode')) return;
      const active = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (active) updateReadingCurrent(active.target.id);
    }, { rootMargin: '-18% 0px -62% 0px', threshold: [0, .08, .2] });

    content.querySelectorAll('[data-reading-chapter]').forEach((chapter) => readingObserver.observe(chapter));
  }

  async function enterReading() {
    cinematicScrollY = window.scrollY;
    const targetId = cinematicToReading[activeCinematicChapter()] || 'read-nascida-para-conquistar';

    document.body.classList.add('reading-mode');
    cinematicTargets.forEach((element) => element.setAttribute('aria-hidden', 'true'));
    readingView.hidden = false;
    readingView.removeAttribute('aria-hidden');
    updateToggle(true);
    if (hint) hint.hidden = true;
    sessionStorage.setItem('yllith-reading-mode-seen', '1');

    try {
      await mountReading();
      window.requestAnimationFrame(() => scrollToReading(targetId));
    } catch {
      // The accessible fallback produced by mountReading remains visible.
    }
  }

  function leaveReading() {
    document.body.classList.remove('reading-mode');
    cinematicTargets.forEach((element) => element.removeAttribute('aria-hidden'));
    readingView.hidden = true;
    readingView.setAttribute('aria-hidden', 'true');
    updateToggle(false);
    history.replaceState(history.state, '', window.location.pathname + window.location.search);
    window.scrollTo({ top: cinematicScrollY, behavior: reduceMotion ? 'auto' : 'smooth' });
  }

  toggle.addEventListener('click', () => {
    if (toggle.getAttribute('aria-checked') === 'true') leaveReading();
    else void enterReading();
  });

  document.addEventListener('click', (event) => {
    const link = event.target.closest?.('[data-reading-link]');
    if (!link || !document.body.classList.contains('reading-mode')) return;
    const id = link.dataset.readingLink;
    if (!id) return;
    event.preventDefault();
    scrollToReading(id, true);
    const details = link.closest('details');
    if (details) details.open = false;
  });

  if (hint && !sessionStorage.getItem('yllith-reading-mode-seen')) {
    hintTimer = window.setTimeout(() => {
      if (toggle.getAttribute('aria-checked') === 'false') {
        hint.hidden = false;
        window.setTimeout(() => {
          hint.hidden = true;
        }, 6500);
      }
    }, 5500);
    window.addEventListener('beforeunload', () => window.clearTimeout(hintTimer), { once: true });
  }
})();
