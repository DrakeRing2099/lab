from dataclasses import dataclass
from typing import Optional, Dict, Any, List


@dataclass
class STTResult:
    text: str
    language: Optional[str] = None
    segments: Optional[List[dict]] = None
    meta: Optional[Dict[str, Any]] = None


class STTEngine:
    name: str = "base"

    def transcribe(self, audio_path: str, lang: Optional[str] = None) -> STTResult:
        raise NotImplementedError
