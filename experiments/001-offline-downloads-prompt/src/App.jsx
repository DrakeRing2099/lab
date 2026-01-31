import { useEffect, useMemo, useState } from "react";

const downloads = [
  { id: 1, title: "Starboy", artist: "The Weeknd" },
  { id: 2, title: "Blinding Lights", artist: "The Weeknd" },
  { id: 3, title: "Nights", artist: "Frank Ocean" },
  { id: 4, title: "Lose Yourself", artist: "Eminem" },
  { id: 5, title: "Believer", artist: "Imagine Dragons" },
  { id: 6, title: "HUMBLE.", artist: "Kendrick Lamar" },
  { id: 7, title: "One Dance", artist: "Drake" },
  { id: 8, title: "Yellow", artist: "Coldplay" },
];

const onlineResults = [
  { id: 101, title: "Starboy (Remix)", artist: "The Weeknd" },
  { id: 102, title: "Blinding Lights (Live)", artist: "The Weeknd" },
  { id: 103, title: "After Hours", artist: "The Weeknd" },
  { id: 104, title: "Thinking Out Loud", artist: "Ed Sheeran" },
  { id: 105, title: "Shape of You", artist: "Ed Sheeran" },
  { id: 106, title: "Someone Like You", artist: "Adele" },
  { id: 107, title: "Rolling in the Deep", artist: "Adele" },
  { id: 108, title: "Smells Like Teen Spirit", artist: "Nirvana" },
  { id: 109, title: "Bohemian Rhapsody", artist: "Queen" },
  { id: 110, title: "Lose Yourself (Clean)", artist: "Eminem" },
  { id: 111, title: "God's Plan", artist: "Drake" },
  { id: 112, title: "One Dance (Radio Edit)", artist: "Drake" },
  { id: 113, title: "Viva La Vida", artist: "Coldplay" },
  { id: 114, title: "Paradise", artist: "Coldplay" },
  { id: 115, title: "HUMBLE. (Skrillex Remix)", artist: "Kendrick Lamar" },
  { id: 116, title: "Believer (Acoustic)", artist: "Imagine Dragons" },
  { id: 117, title: "Radioactive", artist: "Imagine Dragons" },
  { id: 118, title: "Nights (Extended)", artist: "Frank Ocean" },
  { id: 119, title: "Self Control", artist: "Frank Ocean" },
  { id: 120, title: "Take Me To Church", artist: "Hozier" },
];

function normalizeQuery(q) {
  return q
    .toLowerCase()
    .trim()
    .split(/\s+/)
    .filter(Boolean);
}

function filterAndRank(list, query) {
  const q = query.trim().toLowerCase();
  const tokens = normalizeQuery(query);

  // If no query, show top 10 (or fewer)
  if (tokens.length === 0) return list.slice(0, 10);

  const scored = [];

  for (const item of list) {
    const title = (item.title ?? "").toLowerCase();
    const artist = (item.artist ?? "").toLowerCase();
    const haystack = `${title} ${artist}`.trim();

    // AND match: every token must appear somewhere
    const allTokensMatch = tokens.every((t) => haystack.includes(t));
    if (!allTokensMatch) continue;

    // Cheap ranking
    let score = 0;
    if (q && title.startsWith(q)) score += 3;
    if (q && title.includes(q)) score += 2;
    if (q && artist.includes(q)) score += 1;

    // Small bonus for matching more tokens (ties)
    score += tokens.length * 0.1;

    scored.push({ item, score });
  }

  scored.sort((a, b) => b.score - a.score);
  return scored.map((s) => s.item);
}

export default function App() {
  const [isPoor, setIsPoor] = useState(false);
  // auto-switchback: do NOT persist this
  const [useDownloads, setUseDownloads] = useState(false);
  const [query, setQuery] = useState("");

  // ---- network heuristic ----
  useEffect(() => {
    function evaluateNetwork() {
      if (!navigator.onLine) {
        setIsPoor(true);
        return;
      }

      const conn = navigator.connection;
      if (conn) {
        if (
          conn.effectiveType === "slow-2g" ||
          conn.effectiveType === "2g" ||
          conn.rtt > 1000
        ) {
          setIsPoor(true);
          return;
        }
      }

      setIsPoor(false);
    }

    evaluateNetwork();
    window.addEventListener("online", evaluateNetwork);
    window.addEventListener("offline", evaluateNetwork);

    return () => {
      window.removeEventListener("online", evaluateNetwork);
      window.removeEventListener("offline", evaluateNetwork);
    };
  }, []);

  // ---- auto switchback ----
  useEffect(() => {
    if (!isPoor && useDownloads) {
      setUseDownloads(false);
    }
  }, [isPoor, useDownloads]);

  const sourceList = useDownloads ? downloads : onlineResults;

  const results = useMemo(() => {
    return filterAndRank(sourceList, query);
  }, [sourceList, query]);

  const modeLabel = useDownloads ? "Downloads" : "Online";
  const emptyLabel = useDownloads
    ? "No matches in downloads."
    : "No matches online.";

  return (
    <div style={{ padding: 24, fontFamily: "sans-serif", maxWidth: 520 }}>
      <h2 style={{ margin: 0 }}>Music Search</h2>
      <div style={{ marginTop: 6, marginBottom: 12, opacity: 0.8 }}>
        Mode: <b>{modeLabel}</b> {isPoor ? "(connection weak)" : "(connection ok)"}
      </div>

      {isPoor && !useDownloads && (
        <div style={{ padding: 12, background: "#ffeeba", marginBottom: 12 }}>
          Connection is weak.
          <button
            style={{ marginLeft: 12 }}
            onClick={() => setUseDownloads(true)}
          >
            Use downloads
          </button>
        </div>
      )}

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search songs or artists..."
        style={{
          width: "100%",
          padding: 10,
          marginBottom: 12,
          borderRadius: 8,
          border: "1px solid #ddd",
        }}
      />

      {results.length === 0 ? (
        <div style={{ padding: 12, opacity: 0.8 }}>{emptyLabel}</div>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {results.map((r) => (
            <li key={r.id} style={{ marginBottom: 6 }}>
              <span>{r.title}</span>
              {r.artist ? <span style={{ opacity: 0.7 }}> — {r.artist}</span> : null}
            </li>
          ))}
        </ul>
      )}

      {/* Optional manual toggle for testing */}
      <div style={{ marginTop: 16, opacity: 0.8 }}>
        <button onClick={() => setUseDownloads((v) => !v)}>
          Toggle mode (debug)
        </button>
      </div>
    </div>
  );
}
