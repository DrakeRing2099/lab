import argparse 
from pathlib import Path

from src.engines.whisper_local import WhisperLocalEngine


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", default="whisper_local")
    p.add_argument("--audio", required=True)
    p.add_argument("--lang", default=None, help="hi, ta, bnm gu, mr, te, kn, ml, ...")
    p.add_argument("--model", default="small", help="tiny, base, small, medium, large-v3")
    args = p.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        raise SystemExit(f"Audio file not found: {audio_path}")
    
    if args.engine == "whisper_local":
        eng = WhisperLocalEngine(model_size=args.model)
    else:
        raise SystemExit(f"Unknown Engine: {args.engine}")
    
    out = eng.transcribe(str(audio_path), lang=args.lang)
    print(out.text)


if __name__ == "__main__":
    main()