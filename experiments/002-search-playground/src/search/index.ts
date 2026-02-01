import type { Song, SearchMethod } from "./types"

import { containsMethod } from "./methods/contains";
import { prefixMethod } from "./methods/prefix";
import { fieldWeightedMethod } from "./methods/fieldWeighted";
import { bm25LiteMethod } from "./methods/bm25Lite";
import { fuzzySubsequenceMethod } from "./methods/fuzzySubsequence";
import { levenshteinMethod } from "./methods/levenshtein";
import { trigramMethod } from "./methods/trigram";
import { semanticStubMethod } from "./methods/semanticStub";
import { hybridMethod } from "./methods/hybrid";

export const METHODS: SearchMethod<Song>[] = [
  containsMethod,
  prefixMethod,
  fieldWeightedMethod,
  bm25LiteMethod,
  fuzzySubsequenceMethod,
  levenshteinMethod,
  trigramMethod,
  semanticStubMethod,
  hybridMethod,
];

export function normalizeTokens(query: string): string[] {
    return query 
    .toLowerCase()
    .trim()
    .split(/\s+/)
    .filter(Boolean);  
}

export function haystack(song: Song): { title: string; artist: string; album: string; all: string } {
  const title = (song.title ?? "").toLowerCase();
  const artist = (song.artist ?? "").toLowerCase();
  const album = (song.album ?? "").toLowerCase();
  const all = `${title} ${artist} ${album}`.trim();
  return { title, artist, album, all };
}

export function clampLimit(n: number): number {
  if (n < 1) return 1;
  if (n > 50) return 50;
  return n;
}