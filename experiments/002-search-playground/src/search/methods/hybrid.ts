import type { Song, SearchMethod, SearchResult } from "../types";
import { normalizeTokens, haystack } from "../index";

// Hybrid: keyword gate → semantic-ish rerank.
// Here semantic is approximated by a simple "title/artist phrase bonus".
function semanticRerankBonus(query: string, s: Song): number {
  const q = query.toLowerCase().trim();
  const h = haystack(s);
  if (!q) return 0;
  // phrase bonus for title match
  if (h.title.includes(q)) return 1.5;
  // softer bonus for artist match
  if (h.artist.includes(q)) return 1.0;
  return 0;
}

export const hybridMethod: SearchMethod<Song> = {
  id: "hybrid",
  label: "Hybrid (keyword gate → rerank)",
  run(items, query, ctx) {
    const tokens = normalizeTokens(query);
    if (tokens.length === 0) return items.slice(0, ctx.limit).map((item) => ({ item, score: 1 }));

    // Gate: strict-ish keyword filter (contains)
    const gated: Song[] = [];
    for (const s of items) {
      const h = haystack(s);
      const matches = tokens.filter((t) => h.all.includes(t));
      const ok = ctx.mode === "AND" ? matches.length === tokens.length : matches.length > 0;
      if (ok) gated.push(s);
    }

    // Rerank with bonus
    const out: SearchResult<Song>[] = [];
    for (const s of gated) {
      const h = haystack(s);
      const tokenHits = tokens.filter((t) => h.all.includes(t));
      const base = tokenHits.length;
      const bonus = semanticRerankBonus(query, s);

      out.push({ item: s, score: base + bonus, debug: { tokenHits, bonus } });
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, ctx.limit);
  },
};
