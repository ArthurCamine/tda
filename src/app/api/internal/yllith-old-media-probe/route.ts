export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const urls = [
  "https://media.dnd.faysk.dev/lore/yllith/025d9245cb769525756e7fc9511257d22617905524c4c1c6764dce4fc4cbed86/despedida_pais_destaque.avif",
  "https://media.dnd.faysk.dev/lore/yllith/04ae4968021a938e8a8e738bbe84fea20f8e0900bba0be2b6cba70bc635e06b5/backgroud_jornada.avif",
  "https://media.dnd.faysk.dev/lore/yllith/0a6d758ad05a37b84040e7548dbf693612fd55c4272f1f0a018a902213e1cca2/sonho-paralax_personagem.avif",
  "https://media.dnd.faysk.dev/lore/yllith/3b01721eadeeed0d0c89a72b3a9ed4131f4b3bfc1a7fe936b9a5de2817733258/social-yllith.jpg",
  "https://media.dnd.faysk.dev/lore/yllith/585df10d13dfbb442d9a12daafe22b1589c99c4397fd560f2b7911e8e3a3d4de/maos_sobre_mapa_matilha.avif",
  "https://media.dnd.faysk.dev/lore/yllith/650c460bad660ecb35184f1208771ec8659103735bdd797d1a7583369d7756da/sonho_paralax_espirito.avif",
  "https://media.dnd.faysk.dev/lore/yllith/6e094723afb19b7be52115ecccfc291d699ead15e66bdea688befef07638c803/despedida_tios_backgroud.avif",
  "https://media.dnd.faysk.dev/lore/yllith/84e87577d93d06b69e9b5d9ff644e2d860cae32ee4542b8e0a7c523124c6850c/mapa_matilha_sem_mao.avif",
  "https://media.dnd.faysk.dev/lore/yllith/92b5a5922c776170d251afa3190e33e62aab1fb6e1cd9465df437129608a8cad/yllith_jornada.avif",
  "https://media.dnd.faysk.dev/lore/yllith/b065a145edf1f07651a49624bbd3be0740e0e167557a23fcba3a47990460f2bc/despedida_tios_destaque-personagem.avif",
  "https://media.dnd.faysk.dev/lore/yllith/bcf5985f7f43bb50e40d36fc40a6e35192343cf39d9159a479ad0a62f3bab655/sonho_paralax_backgroud.avif",
  "https://media.dnd.faysk.dev/lore/yllith/d8d2f723883922f2b31682d946e4278bbe178c7ad769b69cf08cd2ed4eaca288/yllith.avif",
  "https://media.dnd.faysk.dev/lore/yllith/dcfd8cfb7c1ab21a47a4441e34497935de06865140e0f79a56a9c0d63ea5cbb2/sonho_paralax_nevoa.avif",
  "https://media.dnd.faysk.dev/lore/yllith/f096873034fe4cd14c1cfd24849dcf2fa127bcd65964dc9dd244846a7487421e/despedida_pais_background.avif",
] as const;

export async function GET() {
  const results = await Promise.all(urls.map(async (url) => {
    try {
      const response = await fetch(url, { method: "HEAD", cache: "no-store", signal: AbortSignal.timeout(8000) });
      return {
        name: url.slice(url.lastIndexOf("/") + 1),
        ok: response.ok,
        status: response.status,
        bytes: response.headers.get("content-length"),
        type: response.headers.get("content-type"),
        cache: response.headers.get("cache-control"),
      };
    } catch (error) {
      return {
        name: url.slice(url.lastIndexOf("/") + 1),
        ok: false,
        status: 0,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }));
  return Response.json({ ok: results.every((result) => result.ok), count: results.length, results }, { headers: { "Cache-Control": "no-store" } });
}
