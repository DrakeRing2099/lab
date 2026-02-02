import type { Song, SearchMethod, SearchResult } from "../types";
import { haystack, normalizeTokens } from "../index";

function levenshtein(a: string, b: string): number {
  const m = a.length, n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0));
  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(
        dp[i - 1][j] + 1,
        dp[i][j - 1] + 1,
        dp[i - 1][j - 1] + cost
      );
    }
  }
  return dp[m][n];
}

function bestEditDistance(token: string, field: string): { best: number; bestWord: string } {
  const words = field.split(/\s+/).filter(Boolean);
  let best = Infinity;
  let bestWord = "";
  for (const w of words) {
    const d = levenshtein(token, w);
    if (d < best) {
      best = d;
      bestWord = w;
    }
  }
  return { best, bestWord };
}

export const levenshteinMethod: SearchMethod<Song> = {
  id: "levenshtein",
  label: "Edit distance (Levenshtein)",
  run(items, query, ctx) {
    const tokens = normalizeTokens(query);
    if (tokens.length === 0) return items.slice(0, ctx.limit).map((item) => ({ item, score: 1 }));

    // allow up to ~30% edits, at least 1
    const out: SearchResult<Song>[] = [];
    for (const s of items) {
      const h = haystack(s);

      const tokenDebug: any[] = [];
      let matchedCount = 0;
      let score = 0;

      for (const t of tokens) {
        const titleBest = bestEditDistance(t, h.title);
        const artistBest = bestEditDistance(t, h.artist);
        const best = titleBest.best <= artistBest.best
          ? { field: "title", ...titleBest }
          : { field: "artist", ...artistBest };

        const maxAllowed = Math.max(1, Math.floor(t.length * 0.3));
        const ok = best.best <= maxAllowed;

        tokenDebug.push({ token: t, ...best, maxAllowed, ok });
        if (ok) {
          matchedCount++;
          // smaller distance => higher score
          const fieldWeight = best.field === "title" ? 3 : 2;
          score += fieldWeight * (1 / (1 + best.best));
        }
      }

      const okAll = ctx.mode === "AND" ? matchedCount === tokens.length : matchedCount > 0;
      if (!okAll) continue;

      out.push({ item: s, score, debug: { tokenDebug, mode: ctx.mode } });
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, ctx.limit);
  },
};
