"""ASR offline tests: file errors, container probing and config edges (no model)."""
from __future__ import annotations

import os
import tempfile
import unittest
import uuid
import wave

from pydantic import ValidationError

from core.asr import (
    ASRConfig,
    ASREngine,
    AudioNotFoundError,
    DecodeError,
    UnsupportedFormatError,
    _probe_audio,
)


class ASROfflineTests(unittest.TestCase):
    def make_temp(self, data=b"x", suffix=".wav"):
        handle, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_missing_path(self):
        engine = ASREngine()  # real backend, but path checks happen first
        result = engine.transcribe(os.path.join(tempfile.gettempdir(), "definitely-missing-asr.wav"))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "AUDIO_NOT_FOUND")
        self.assertEqual(result.segments, [])

    def test_missing_path_error_does_not_leak_path(self):
        token = "case-" + uuid.uuid4().hex
        path = os.path.join(tempfile.gettempdir(), token + ".wav")
        result = ASREngine().transcribe(path)
        self.assertEqual(result.error_code, "AUDIO_NOT_FOUND")
        self.assertNotIn(token, result.error or "")
        self.assertNotIn(path, result.error or "")

    def test_empty_file(self):
        path = self.make_temp(data=b"")
        result = ASREngine().transcribe(path)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "EMPTY_AUDIO")

    def test_probe_missing_file(self):
        with self.assertRaises(AudioNotFoundError):
            _probe_audio(os.path.join(tempfile.gettempdir(), "missing-probe.wav"))

    def test_probe_corrupt_file(self):
        path = self.make_temp(data=b"this is not audio at all", suffix=".wav")
        with self.assertRaises((UnsupportedFormatError, DecodeError)):
            _probe_audio(path)

    def test_probe_valid_generated_wav(self):
        path = self.make_temp(data=b"", suffix=".wav")
        with wave.open(path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\x00\x00" * 800)  # 0.1 s of silence
        audio_format, duration = _probe_audio(path)
        self.assertIsNotNone(audio_format)
        self.assertTrue(audio_format.startswith("wav/"), audio_format)
        self.assertIsNotNone(duration)
        self.assertGreater(duration, 0.05)
        self.assertLess(duration, 0.2)

    def test_result_metadata_does_not_store_path_or_text(self):
        path = self.make_temp(data=b"")
        result = ASREngine().transcribe(path)
        metadata = result.run_metadata
        self.assertNotIn("audio_path", metadata)
        self.assertNotIn("text", metadata)
        self.assertIn("audio_sha256", metadata)


class ASRConfigLanguageTests(unittest.TestCase):
    def test_language_none_allowed(self):
        self.assertIsNone(ASRConfig(language=None).language)

    def test_non_empty_language_allowed(self):
        self.assertEqual(ASRConfig(language="en").language, "en")

    def test_empty_language_rejected(self):
        with self.assertRaises(ValidationError):
            ASRConfig(language="")


if __name__ == "__main__":
    unittest.main()
