(() => {
	"use strict";
	const chapters = window.DIARY_CHAPTERS || [];
	const $ = (id) => document.getElementById(id);
	const mobile = matchMedia("(max-width: 760px)");
	const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
	const storageKey = "diario_astel_leitura_v1";
	let pages = [],
		chapterStarts = [],
		current = 0,
		opened = false,
		turning = false,
		timer;
	let saved = null,
		fontStep = 0;
	try {
		saved = JSON.parse(localStorage.getItem(storageKey));
	} catch {
		/* Storage can be disabled. */
	}
	if (
		!saved ||
		typeof saved.chapter !== "string" ||
		!Number.isInteger(saved.paragraph) ||
		!Number.isInteger(saved.offset)
	)
		saved = null;
	if (saved && !chapters.some((c) => c.id === saved.chapter)) saved = null;
	if (
		saved &&
		Number.isInteger(saved.fontStep) &&
		saved.fontStep >= 0 &&
		saved.fontStep <= 2
	)
		fontStep = saved.fontStep;
	const roman = (n) => {
		let result = "";
		for (const [value, symbol] of [
			[1000, "M"],
			[900, "CM"],
			[500, "D"],
			[400, "CD"],
			[100, "C"],
			[90, "XC"],
			[50, "L"],
			[40, "XL"],
			[10, "X"],
			[9, "IX"],
			[5, "V"],
			[4, "IV"],
			[1, "I"],
		]) {
			while (n >= value) {
				result += symbol;
				n -= value;
			}
		}
		return result;
	};
	const escapeHtml = (text) =>
		text.replace(
			/[&<>"']/g,
			(c) =>
				({
					"&": "&amp;",
					"<": "&lt;",
					">": "&gt;",
					'"': "&quot;",
					"'": "&#39;",
				})[c],
		);
	const countVisible = () => (mobile.matches ? 1 : 2);

	function pageShell(page, number) {
		if (!page)
			return '<div class="page-body end-note"><p>A história continua.</p><span>DIÁRIO DE ASTEL</span></div>';
		return `<div class="page-running">${escapeHtml(chapters[page.chapter].title)}</div><div class="page-body">${page.html}</div><span class="page-number">${number}</span>`;
	}

	// The same page geometry measures and displays the text. Every token belongs to
	// exactly one fragment, including when a paragraph spans two physical pages.
	function paginate() {
		const anchor = opened ? getAnchor() : saved;
		document.documentElement.style.setProperty(
			"--page-font",
			`${18 + fontStep * 2}px`,
		);
		const measure = $("measurement");
		measure.style.width = `${$("book").getBoundingClientRect().width / countVisible()}px`;
		measure.innerHTML = '<div class="page-body"></div>';
		const body = measure.firstElementChild;
		const height = body.clientHeight;
		const lineHeight = parseFloat(getComputedStyle(body).lineHeight);
		const fits = () => body.scrollHeight <= height + 1;
		pages = [];
		chapterStarts = [];
		chapters.forEach((chapter, chapterIndex) => {
			chapterStarts.push(pages.length);
			body.innerHTML = `<div class="chapter-start"><span class="chapter-number">Capítulo ${roman(chapter.number)}</span><h2>${escapeHtml(chapter.title)}</h2></div>`;
			let fragments = [];
			function flush() {
				if (!body.children.length) return;
				pages.push({ chapter: chapterIndex, html: body.innerHTML, fragments });
				body.innerHTML = "";
				fragments = [];
			}
			chapter.paragraphs.forEach((paragraph, paragraphIndex) => {
				if (paragraph === "***") {
					const hr = document.createElement("hr");
					body.append(hr);
					if (!fits()) {
						hr.remove();
						flush();
						body.append(hr);
					}
					fragments.push({ paragraph: paragraphIndex, start: 0, end: 1 });
					return;
				}
				const words = paragraph.match(/\S+\s*/g) || [];
				let offset = 0;
				while (offset < words.length) {
					const p = document.createElement("p");
					if (offset) p.className = "continuation";
					p.textContent = words.slice(offset).join("");
					body.append(p);
					if (fits()) {
						fragments.push({
							paragraph: paragraphIndex,
							start: offset,
							end: words.length,
						});
						offset = words.length;
						continue;
					}
					// Find the longest word boundary that fits in the remaining space.
					let low = 0,
						high = words.length - offset;
					while (low < high) {
						const mid = Math.ceil((low + high) / 2);
						p.textContent = words.slice(offset, offset + mid).join("");
						if (fits()) low = mid;
						else high = mid - 1;
					}
					let take = low;
					p.textContent = words.slice(offset, offset + take).join("");
					const fragmentHeight = p.getBoundingClientRect().height;
					const hasPriorText = fragments.length > 0;
					// Keep a minimum of two lines on each side of a paragraph break.
					if (take > 0 && fragmentHeight >= lineHeight * 1.9) {
						const tail = document.createElement("p");
						tail.style.cssText =
							"position:absolute;visibility:hidden;width:100%";
						body.append(tail);
						tail.textContent = words.slice(offset + take).join("");
						while (
							take > 0 &&
							tail.getBoundingClientRect().height < lineHeight * 1.9
						) {
							take--;
							tail.textContent = words.slice(offset + take).join("");
						}
						tail.remove();
						p.textContent = words.slice(offset, offset + take).join("");
					}
					if (
						!take ||
						(hasPriorText &&
							p.getBoundingClientRect().height < lineHeight * 1.9)
					) {
						p.remove();
						if (body.children.length) {
							flush();
							continue;
						}
						throw new Error(
							"A página está pequena demais para exibir o texto.",
						);
					}
					fragments.push({
						paragraph: paragraphIndex,
						start: offset,
						end: offset + take,
					});
					offset += take;
					flush();
				}
			});
			flush();
		});
		current = anchor ? findAnchor(anchor) : 0;
		current -= current % countVisible();
	}

	function getAnchor() {
		const page = pages[current];
		if (!page) return saved;
		const fragment = page.fragments[0];
		return {
			chapter: chapters[page.chapter].id,
			paragraph: fragment?.paragraph || 0,
			offset: fragment?.start || 0,
			fontStep,
		};
	}
	function findAnchor(anchor) {
		const chapterIndex = chapters.findIndex(
			(chapter) => chapter.id === anchor.chapter,
		);
		const index = pages.findIndex(
			(page) =>
				page.chapter === chapterIndex &&
				page.fragments.some(
					(f) =>
						f.paragraph === anchor.paragraph &&
						f.start <= anchor.offset &&
						f.end > anchor.offset,
				),
		);
		return index >= 0 ? index : chapterStarts[Math.max(0, chapterIndex)] || 0;
	}
	function render() {
		$("left-page").innerHTML = pageShell(pages[current], current + 1);
		$("right-page").innerHTML = pageShell(pages[current + 1], current + 2);
		$("left-page").setAttribute("aria-label", `Página ${current + 1}`);
		$("right-page").setAttribute("aria-label", `Página ${current + 2}`);
		const last = Math.min(current + countVisible(), pages.length);
		$("page-status").textContent =
			countVisible() === 1 || last === current + 1
				? `Página ${current + 1} de ${pages.length}`
				: `Páginas ${current + 1}–${last} de ${pages.length}`;
		$("chapter-label").textContent =
			`${roman(chapters[pages[current].chapter].number)} · ${chapters[pages[current].chapter].title}`;
		$("progress").style.width = `${(last / pages.length) * 100}%`;
		$("previous").disabled = $("edge-prev").disabled = current === 0;
		$("next").disabled = $("edge-next").disabled = last >= pages.length;
		saved = getAnchor();
		try {
			localStorage.setItem(storageKey, JSON.stringify(saved));
		} catch {
			/* Reading remains available. */
		}
	}
	function openBook(anchor = null, chapterIndex = null) {
		$("cover-scene").hidden = true;
		$("reader").hidden = false;
		$("font-size").hidden = false;
		$("fullscreen").hidden = !document.fullscreenEnabled;
		if (!opened) {
			try {
				if (!chapters.length) throw new Error("Capítulos indisponíveis.");
				paginate();
				$("reader-error").hidden = true;
			} catch {
				$("reader").hidden = true;
				$("cover-scene").hidden = false;
				$("reader-error").hidden = false;
				$("font-size").hidden = $("fullscreen").hidden = true;
				return;
			}
		}
		opened = true;
		current =
			chapterIndex !== null
				? chapterStarts[chapterIndex]
				: anchor
					? findAnchor(anchor)
					: 0;
		current -= current % countVisible();
		render();
		$("book").focus({ preventScroll: true });
	}
	function turn(direction) {
		if (!opened || turning || $("contents-dialog").open) return;
		const target = current + direction * countVisible();
		if (target < 0 || target >= pages.length) return;
		const overlay = $("turning-page");
		overlay.replaceChildren();
		if (!reducedMotion.matches) {
			const leaf = (
				direction > 0 && !mobile.matches ? $("right-page") : $("left-page")
			).cloneNode(true);
			leaf.removeAttribute("id");
			leaf.removeAttribute("aria-label");
			overlay.append(leaf);
			overlay.className = `turning-page active${direction < 0 ? " backward" : ""}`;
			turning = true;
			setTimeout(() => {
				overlay.className = "turning-page";
				overlay.replaceChildren();
				turning = false;
			}, 490);
		}
		current = target;
		render();
	}
	$("chapter-count").textContent = `${chapters.length} CAPÍTULOS`;
	chapters.forEach((chapter, index) => {
		const li = document.createElement("li");
		const button = document.createElement("button");
		button.innerHTML = `<span>${roman(chapter.number)}</span><b>${escapeHtml(chapter.title)}</b><em aria-hidden="true">↗</em>`;
		button.addEventListener("click", () => {
			$("contents-dialog").close();
			openBook(null, index);
		});
		li.append(button);
		$("chapter-list").append(li);
	});
	$("open-book").addEventListener("click", () => openBook());
	$("resume").hidden = !saved;
	$("resume").addEventListener("click", () => openBook(saved));
	$("home").addEventListener("click", () => {
		$("reader").hidden = true;
		$("cover-scene").hidden = false;
		$("font-size").hidden = $("fullscreen").hidden = true;
		$("resume").hidden = !saved;
		opened = false;
		$("open-book").focus({ preventScroll: true });
	});
	$("contents").addEventListener("click", () =>
		$("contents-dialog").showModal(),
	);
	$("close-contents").addEventListener("click", () =>
		$("contents-dialog").close(),
	);
	$("contents-dialog").addEventListener("click", (event) => {
		const rect = event.currentTarget.getBoundingClientRect();
		if (
			event.clientX < rect.left ||
			event.clientX > rect.right ||
			event.clientY < rect.top ||
			event.clientY > rect.bottom
		)
			event.currentTarget.close();
	});
	$("previous").addEventListener("click", () => turn(-1));
	$("edge-prev").addEventListener("click", () => turn(-1));
	$("next").addEventListener("click", () => turn(1));
	$("edge-next").addEventListener("click", () => turn(1));
	document.addEventListener("keydown", (event) => {
		if (
			!opened ||
			$("contents-dialog").open ||
			event.altKey ||
			event.ctrlKey ||
			event.metaKey
		)
			return;
		if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
			event.preventDefault();
			turn(event.key === "ArrowRight" ? 1 : -1);
		}
	});
	let touchStart = null;
	$("book").addEventListener(
		"touchstart",
		(event) => {
			const t = event.touches[0];
			touchStart = { x: t.clientX, y: t.clientY };
		},
		{ passive: true },
	);
	$("book").addEventListener(
		"touchend",
		(event) => {
			if (!touchStart || window.getSelection()?.toString()) return;
			const t = event.changedTouches[0],
				x = t.clientX - touchStart.x,
				y = t.clientY - touchStart.y;
			touchStart = null;
			if (Math.abs(x) > 55 && Math.abs(x) > Math.abs(y) * 1.5)
				turn(x < 0 ? 1 : -1);
		},
		{ passive: true },
	);
	$("font-size").addEventListener("click", () => {
		fontStep = (fontStep + 1) % 3;
		paginate();
		render();
		$("font-size").setAttribute(
			"aria-label",
			fontStep === 2
				? "Restaurar tamanho do texto"
				: "Aumentar tamanho do texto",
		);
	});
	$("fullscreen").addEventListener("click", async () => {
		try {
			if (document.fullscreenElement) await document.exitFullscreen();
			else await document.documentElement.requestFullscreen();
		} catch {
			$("fullscreen").hidden = true;
		}
	});
	document.addEventListener("fullscreenchange", () =>
		$("fullscreen").setAttribute(
			"aria-label",
			document.fullscreenElement
				? "Sair da tela cheia"
				: "Entrar em tela cheia",
		),
	);
	window.addEventListener("resize", () => {
		clearTimeout(timer);
		timer = setTimeout(() => {
			if (opened) {
				paginate();
				render();
			}
		}, 180);
	});
})();
