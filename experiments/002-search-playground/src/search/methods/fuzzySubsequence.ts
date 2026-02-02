import type { Song, SearchMethod, SearchResult } from "../types";
import { haystack, normalizeTokens } from "../index";

// fast fuzzy: query token is a subsequence of a word (not necessarily contiguous)
// e.g. "blndng" matches "blinding"
function isSubsequence(needle: string, hay: string): boolean {
  let i = 0;
  for (let j = 0; j < hay.length && i < needle.length; j++) {
    if (needle[i] === hay[j]) i++;
  }
  return i === needle.length;
}

function bestSubsequenceHit(token: string, field: string): { ok: boolean; bestWord?: string } {
  const words = field.split(/\s+/).filter(Boolean);
  for (const w of words) {
    if (token.length <= 2) {
      if (w.startsWith(token)) return { ok: true, bestWord: w };
    } else {
      if (isSubsequence(token, w)) return { ok: true, bestWord: w };
    }
  }
  return { ok: false };
}

export const fuzzySubsequenceMethod: SearchMethod<Song> = {
  id: "fuzzySubsequence",
  label: "Fuzzy subsequence (fast typos)",
  run(items, query, ctx) {
    const tokens = normalizeTokens(query);
    if (tokens.length === 0) return items.slice(0, ctx.limit).map((item) => ({ item, score: 1 }));

    const out: SearchResult<Song>[] = [];
    for (const s of items) {
      const h = haystack(s);

      const hits: Array<{ token: string; field: "title" | "artist"; word: string }> = [];
      for (const t of tokens) {
        const tHit = bestSubsequenceHit(t, h.title);
        if (tHit.ok) {
          hits.push({ token: t, field: "title", word: tHit.bestWord! });
          continue;
        }
        const aHit = bestSubsequenceHit(t, h.artist);
        if (aHit.ok) hits.push({ token: t, field: "artist", word: aHit.bestWord! });
      }

      const ok = ctx.mode === "AND" ? hits.length === tokens.length : hits.length > 0;
      if (!ok) continue;

      // score: title hits more, longer tokens more
      let score = 0;
      for (const hit of hits) score += (hit.field === "title" ? 3 : 2) + hit.token.length * 0.05;

      out.push({ item: s, score, debug: { hits, mode: ctx.mode } });
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, ctx.limit);
  },
};
