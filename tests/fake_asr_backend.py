"""Test-only ASR backend: no model, no network, deterministic output."""
from __future__ import annotations

from core.asr import RawTranscription


class FakeBackend:
    """Injectable backend for ``ASREngine`` tests."""

    def __init__(
        self,
        segments=None,
        language="en",
        language_probability=1.0,
        duration=10.0,
        duration_after_vad=9.0,
        audio_format="fake/wav",
        load_error=None,
        transcribe_error=None,
    ):
        self.segments = (
            [
                {"start": 0.0, "end": 2.0, "text": " hello"},
                {"start": 2.0, "end": 4.0, "text": " world"},
            ]
            if segments is None
            else segments
        )
        self.language = language
        self.language_probability = language_probability
        self.duration = duration
        self.duration_after_vad = duration_after_vad
        self.audio_format = audio_format
        self.load_error = load_error
        self.transcribe_error = transcribe_error
        self.load_calls = 0
        self.transcribe_calls = 0

    def load(self, config) -> None:
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error

    def transcribe(self, audio_path: str, config) -> RawTranscription:
        self.transcribe_calls += 1
        if self.transcribe_error is not None:
            raise self.transcribe_error
        return RawTranscription(
            segments=self.segments,
            language=self.language,
            language_probability=self.language_probability,
            duration=self.duration,
            duration_after_vad=self.duration_after_vad,
            audio_format=self.audio_format,
        )
