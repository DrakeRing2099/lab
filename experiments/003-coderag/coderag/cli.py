from __future__ import annotations

import argparse
from pathlib import Path

from .ingest import ingest
from .query import query_lexical
from .hybrid_query import query_hybrid

from .vector_query import query_vector


def main() -> None:
    parser = argparse.ArgumentParser(prog="coderag")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="Index a folder into SQLite")
    p_ingest.add_argument("path", type=str, help="Path to repo/folder")
    p_ingest.add_argument("--db", type=str, default="data/coderag.sqlite", help="SQLite db path")

    """
    p_ask = sub.add_parser("ask", help="Ask a question (lexical retrieval v1)")
    p_ask.add_argument("path", type=str, help="Same path you ingested (repo root)")
    p_ask.add_argument("question", type=str, help="Question to retrieve context for")
    p_ask.add_argument("--db", type=str, default="data/coderag.sqlite", help="SQLite db path")
    p_ask.add_argument("--k", type=int, default=6, help="Top K chunks")
    """
    
    p_askv = sub.add_parser("askv", help="Ask a question (vector retrieval v2)")
    p_askv.add_argument("path", type=str, help="Repo/folder root that was ingested")
    p_askv.add_argument("question", type=str)
    p_askv.add_argument("--db", type=str, default="data/coderag.sqlite")
    p_askv.add_argument("--k", type=int, default=6)
    

    p_askh = sub.add_parser("askh", help="Ask a question (hybrid: vector + lexical rerank)")
    p_askh.add_argument("path", type=str)
    p_askh.add_argument("question", type=str)
    p_askh.add_argument("--db", type=str, default="data/coderag.sqlite")
    p_askh.add_argument("--k", type=int, default=6)
    p_askh.add_argument("--cand", type=int, default=30)


    args = parser.parse_args()

    if args.cmd == "ingest":
        repo = Path(args.path)
        db = Path(args.db)
        n_files, n_changed, n_skipped, n_removed = ingest(repo, db)
        print(f"Seen {n_files} files | updated {n_changed} | skipped {n_skipped} | removed {n_removed} | db={db}")

        return

    if args.cmd == "ask":
        print("This command has been depreciated. Use askv instead")
        return 
        repo = Path(args.path).resolve()
        db = Path(args.db)
        hits = query_lexical(db, repo_root=str(repo), question=args.question, k=args.k)

        if not hits:
            print("No hits.")
            return

        for i, h in enumerate(hits, start=1):
            print("=" * 80)
            print(f"[{i}] score={h.score:.2f}  chunk_id={h.chunk_id}")
            print(f"    {h.path}:{h.start_line}-{h.end_line}")
            print(f"    why: {h.why}")
            print("-" * 80)
            print(h.preview)
        return
    
    if args.cmd == "askv":
        repo = Path(args.path).resolve()
        db = Path(args.db)
        hits = query_vector(db, repo_root=str(repo), question=args.question, k=args.k)
        if not hits:
            print("No vector hits (did you re-ingest after adding embeddings?)")
            return
        for i, h in enumerate(hits, start=1):
            print("=" * 80)
            print(f"[{i}] cos={h.score:.3f}  chunk_id={h.chunk_id}")
            print(f"    {h.path}:{h.start_line}-{h.end_line}")
            print("-" * 80)
            print(h.preview)
        return
    
    if args.cmd == "askh":
        repo = Path(args.path).resolve()
        db = Path(args.db)
        hits = query_hybrid(db, repo_root=str(repo), question=args.question, k=args.k, cand=args.cand)
        if not hits:
            print("No hybrid hits.")
            return
        for i, h in enumerate(hits, start=1):
            print("=" * 80)
            print(f"[{i}] score={h.score:.3f}  cos={h.cos:.3f}  lex={h.lex:.1f}  chunk_id={h.chunk_id}")
            print(f"    {h.path}:{h.start_line}-{h.end_line}")
            print(f"    why: {h.why}")
            print("-" * 80)
            print(h.preview)
        return



if __name__ == "__main__":
    main()
