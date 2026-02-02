import { useMemo, useState } from "react";
import "./App.css";

import { SONGS } from "./data/songs";
import { METHODS } from "./search";
import type { SearchMode, SearchResult, Song } from "./search/types";

export default function App() {
  const [query, setQuery] = useState("");
  const [methodId, setMethodId] = useState(METHODS[0].id);
  const [mode, setMode] = useState<SearchMode>("AND");
  const [limit, setLimit] = useState(10);

  const method = METHODS.find((m) => m.id === methodId) ?? METHODS[0];

  const results = useMemo<SearchResult<Song>[]>(() => {
    return method.run(SONGS, query, { mode, limit });
  }, [method, query, mode, limit]);

  return (
    <div style={{ padding: 24, fontFamily: "sans-serif", maxWidth: 900 }}>
      <h2 style={{ margin: 0 }}>Search Playground</h2>
      <div style={{ opacity: 0.8, marginTop: 6, marginBottom: 16 }}>
        Compare different search strategies on the same dataset.
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Try: weeknd, blndng lghts, sad late night, eminem..."
          style={{ flex: "1 1 320px", padding: 10, borderRadius: 8, border: "1px solid #ddd" }}
        />

        <select
          value={methodId}
          onChange={(e) => setMethodId(e.target.value)}
          style={{ padding: 10, borderRadius: 8, border: "1px solid #ddd" }}
        >
          {METHODS.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>

        <select
          value={mode}
          onChange={(e) => setMode(e.target.value as SearchMode)}
          style={{ padding: 10, borderRadius: 8, border: "1px solid #ddd" }}
        >
          <option value="AND">AND tokens</option>
          <option value="OR">OR tokens</option>
        </select>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ opacity: 0.8 }}>Top</span>
          <input
            type="number"
            min={1}
            max={50}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            style={{ width: 80, padding: 10, borderRadius: 8, border: "1px solid #ddd" }}
          />
        </div>
      </div>

      <div style={{ opacity: 0.85, marginBottom: 12 }}>
        Method: <b>{method.label}</b> • Results: <b>{results.length}</b>
      </div>

      {results.length === 0 ? (
        <div style={{ padding: 12, opacity: 0.8 }}>No matches.</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {results.map((r) => (
            <ResultCard key={r.item.id} r={r} />
          ))}
        </div>
      )}
    </div>
  );
}

function ResultCard({ r }: { r: SearchResult<Song> }) {
  return (
    <div
      style={{
        padding: 12,
        borderRadius: 12,
        border: "1px solid #eee",
        boxShadow: "0 1px 6px rgba(0,0,0,0.04)",
      }}
    >
      <div style={{ fontWeight: 600 }}>
        {r.item.title} <span style={{ opacity: 0.7, fontWeight: 400 }}>— {r.item.artist}</span>
      </div>
      {r.item.album ? <div style={{ opacity: 0.7, marginTop: 4 }}>Album: {r.item.album}</div> : null}

      <div style={{ marginTop: 8, opacity: 0.9 }}>
        Score: <b>{Number(r.score.toFixed(4))}</b>
      </div>

      {r.debug ? (
        <details style={{ marginTop: 8 }}>
          <summary style={{ cursor: "pointer" }}>debug</summary>
          <pre style={{ marginTop: 8, whiteSpace: "pre-wrap", fontSize: 12, opacity: 0.9 }}>
            {JSON.stringify(r.debug, null, 2)}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
