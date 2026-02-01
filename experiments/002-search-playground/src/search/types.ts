export type Song = {
    id: number;
    title: string;
    artist: string;
    album?: string;
};

export type SearchMode = "AND" | "OR"

export type SearchResult <T> = {
    item: T;
    score: number;
    debug?: Record<string, unknown>;
};

export type SearchContext = {
    mode: SearchMode;
    limit: number;
};

export type SearchMethod<T> = {
    id: string;
    label: string;
    run: (items: T[], query: string, ctx: SearchContext) => SearchResult<T>[];
};