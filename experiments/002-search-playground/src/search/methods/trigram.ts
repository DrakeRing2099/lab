import type { Song, SearchMethod, SearchResult } from "../types";
import { haystack } from "../index";

function trigrams(s: string): Set<string> {
  const x = `  ${s.toLowerCase()}  `;
  const out = new Set<string>();
  for (let i = 0; i + 3 <= x.length; i++) out.add(x.slice(i, i + 3));
  return out;
}

function jaccard(a: Set<string>, b: Set<string>): number {
  let inter = 0;
  for (const t of a) if (b.has(t)) inter++;
  const union = a.size + b.size - inter;
  return union === 0 ? 0 : inter / union;
}

export const trigramMethod: SearchMethod<Song> = {
  id: "trigram",
  label: "Trigram similarity",
  run(items, query, ctx) {
    const q = query.trim().toLowerCase();
    if (!q) return items.slice(0, ctx.limit).map((item) => ({ item, score: 1 }));

    const q3 = trigrams(q);
    const out: SearchResult<Song>[] = [];

    for (const s of items) {
      const h = haystack(s);
      const tScore = jaccard(q3, trigrams(h.title));
      const aScore = jaccard(q3, trigrams(h.artist));
      const score = Math.max(tScore * 3, aScore * 2); // title bias

      // threshold keeps it from matching everything
      if (score < 0.35) continue;

      out.push({
        item: s,
        score,
        debug: { titleSim: tScore, artistSim: aScore, threshold: 0.35 },
      });
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, ctx.limit);
  },
};
