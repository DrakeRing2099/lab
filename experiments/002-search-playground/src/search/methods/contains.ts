import type { Song, SearchResult, SearchMethod } from "../types";
import { haystack, normalizeTokens } from "../index";

export const containsMethod: SearchMethod<Song> = {
  id: "contains",
  label: "Contains (baseline)",
  run(items, query, ctx) {
    const tokens = normalizeTokens(query);
    if (tokens.length === 0) {
      return items.slice(0, ctx.limit).map((item) => ({ item, score: 1 }));
    }

    const out: SearchResult<Song>[] = [];
    for (const s of items) {
      const h = haystack(s);
      const matches = tokens.filter((t) => h.all.includes(t));
      const ok = ctx.mode === "AND" ? matches.length === tokens.length : matches.length > 0;
      if (!ok) continue;

      // simple score: more matched tokens + title bias
      let score = matches.length;
      if (h.title.includes(tokens.join(" "))) score += 2;

      out.push({
        item: s,
        score,
        debug: { matches, mode: ctx.mode },
      });
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, ctx.limit);
  },
};
