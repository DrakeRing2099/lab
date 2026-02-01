import type { Song, SearchMethod, SearchResult } from "../types";
import { haystack, normalizeTokens } from "../index";

function startsWithWord(field: string, token: string): boolean {
  // match token at word boundary
  // e.g. "blinding lights" -> token "bli" matches
  return field.split(/\s+/).some((w) => w.startsWith(token));
}

export const prefixMethod: SearchMethod<Song> = {
  id: "prefix",
  label: "Prefix (typeahead)",
  run(items, query, ctx) {
    const tokens = normalizeTokens(query);
    if (tokens.length === 0) {
      return items.slice(0, ctx.limit).map((item) => ({ item, score: 1 }));
    }

    const out: SearchResult<Song>[] = [];
    for (const s of items) {
      const h = haystack(s);

      const titleHits = tokens.filter((t) => startsWithWord(h.title, t));
      const artistHits = tokens.filter((t) => startsWithWord(h.artist, t));
      const hits = Array.from(new Set([...titleHits, ...artistHits]));

      const ok = ctx.mode === "AND" ? hits.length === tokens.length : hits.length > 0;
      if (!ok) continue;

      const score = titleHits.length * 3 + artistHits.length * 2;
      out.push({ item: s, score, debug: { titleHits, artistHits, mode: ctx.mode } });
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, ctx.limit);
  },
};
