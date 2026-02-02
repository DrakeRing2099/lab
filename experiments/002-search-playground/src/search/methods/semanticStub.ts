import type { Song, SearchMethod, SearchResult } from "../types";
import { haystack } from "../index";

// Stub: pretend "mood" queries map to artists/titles.
// This covers the "semantic" category without real embeddings yet.
function semanticScore(query: string, s: Song): { score: number; reason: string } {
  const q = query.toLowerCase();
  const h = haystack(s);

  if (q.includes("sad") || q.includes("late night")) {
    if (h.artist.includes("frank ocean")) return { score: 2.5, reason: "mood→Frank Ocean" };
    if (h.title.includes("nights")) return { score: 2.2, reason: "mood→Nights" };
  }

  if (q.includes("gym") || q.includes("workout") || q.includes("hype")) {
    if (h.artist.includes("eminem")) return { score: 2.6, reason: "hype→Eminem" };
    if (h.title.includes("lose yourself")) return { score: 2.4, reason: "hype→Lose Yourself" };
    if (h.artist.includes("kendrick")) return { score: 2.3, reason: "hype→Kendrick" };
  }

  // fallback: tiny bump if query contains any word in title/artist
  const words = q.split(/\s+/).filter(Boolean);
  let hits = 0;
  for (const w of words) if (h.all.includes(w)) hits++;
  return { score: hits * 0.3, reason: hits ? "weak overlap" : "none" };
}

export const semanticStubMethod: SearchMethod<Song> = {
  id: "semanticStub",
  label: "Semantic (stub)",
  run(items, query, ctx) {
    const q = query.trim();
    if (!q) return items.slice(0, ctx.limit).map((item) => ({ item, score: 1 }));

    const out: SearchResult<Song>[] = [];
    for (const s of items) {
      const { score, reason } = semanticScore(q, s);
      if (score <= 0) continue;
      out.push({ item: s, score, debug: { reason } });
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, ctx.limit);
  },
};
