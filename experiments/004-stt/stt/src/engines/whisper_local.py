from faster_whisper import WhisperModel
from ..stt_base import STTEngine, STTResult

class WhisperLocalEngine(STTEngine):
    name = "whisper_local"

    def __init__(self, model_size: str = "small"):
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio_path, lang = None) -> STTResult:
        segments, info = self.model.transcribe(audio_path, language=lang)

        segs = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
        text = " ".join(s["text"].strip() for s in segs).strip()

        return STTResult(
            text=text,
            language=getattr(info, "language", None),
            segments=segs,
            meta={"info": str(info), "engine": self.name},
        )
    