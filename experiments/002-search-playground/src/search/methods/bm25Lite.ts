import type { Song, SearchMethod, SearchResult } from "../types";
import { haystack, normalizeTokens } from "../index";

// BM25-lite: IDF-ish weighting without full term frequencies.
// score = sum_t idf(t) * fieldWeight(if t appears in field)
function buildDf(items: Song[]): Map<string, number> {
  const df = new Map<string, number>();
  for (const s of items) {
    const h = haystack(s);
    const tokens = new Set(h.all.split(/\s+/).filter(Boolean));
    for (const t of tokens) df.set(t, (df.get(t) ?? 0) + 1);
  }
  return df;
}

export const bm25LiteMethod: SearchMethod<Song> = {
  id: "bm25Lite",
  label: "BM25-lite (IDF-ish)",
  run(items, query, ctx) {
    const qTokens = normalizeTokens(query);
    if (qTokens.length === 0) return items.slice(0, ctx.limit).map((item) => ({ item, score: 1 }));

    const N = items.length;
    const df = buildDf(items);

    const out: SearchResult<Song>[] = [];
    for (const s of items) {
      const h = haystack(s);

      const tokenHits: string[] = [];
      let score = 0;

      for (const t of qTokens) {
        const dft = df.get(t) ?? 0;
        const idf = Math.log(1 + (N - dft + 0.5) / (dft + 0.5)); // stable-ish

        let w = 0;
        if (h.title.includes(t)) w = Math.max(w, 3);
        if (h.artist.includes(t)) w = Math.max(w, 2);
        if (h.album.includes(t)) w = Math.max(w, 1);

        if (w > 0) {
          tokenHits.push(t);
          score += idf * w;
        }
      }

      const ok = ctx.mode === "AND" ? tokenHits.length === qTokens.length : tokenHits.length > 0;
      if (!ok) continue;

      out.push({ item: s, score, debug: { tokenHits, mode: ctx.mode } });
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, ctx.limit);
  },
};
