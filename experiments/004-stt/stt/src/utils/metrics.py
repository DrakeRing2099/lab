from jiwer import wer

def compute_wer(reference: str, hypothesis: str) -> float:
    return wer(reference, hypothesis)
