import type { Song, SearchMethod, SearchResult } from "../types";
import { haystack, normalizeTokens } from "../index";

export const fieldWeightedMethod: SearchMethod<Song> = {
  id: "fieldWeighted",
  label: "Field-weighted tokens",
  run(items, query, ctx) {
    const tokens = normalizeTokens(query);
    if (tokens.length === 0) return items.slice(0, ctx.limit).map((item) => ({ item, score: 1 }));

    const out: SearchResult<Song>[] = [];
    for (const s of items) {
      const h = haystack(s);
      const titleMatches = tokens.filter((t) => h.title.includes(t));
      const artistMatches = tokens.filter((t) => h.artist.includes(t));
      const albumMatches = tokens.filter((t) => h.album.includes(t));

      const union = Array.from(new Set([...titleMatches, ...artistMatches, ...albumMatches]));
      const ok = ctx.mode === "AND" ? union.length === tokens.length : union.length > 0;
      if (!ok) continue;

      const score = titleMatches.length * 3 + artistMatches.length * 2 + albumMatches.length * 1;
      out.push({
        item: s,
        score,
        debug: { titleMatches, artistMatches, albumMatches, mode: ctx.mode },
      });
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, ctx.limit);
  },
};
