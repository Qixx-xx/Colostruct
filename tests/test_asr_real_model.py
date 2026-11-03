"""Real-model tests. Disabled by default; R2 requires explicit authorisation.

No patient audio path is hardcoded: R2 only runs when ``ASR_REAL_AUDIO`` points
to an existing file chosen by the operator.
"""
from __future__ import annotations

import os
import unittest

RUN_LOAD = os.environ.get("ASR_RUN_REAL_MODEL") == "1"
RUN_TRANSCRIBE = os.environ.get("ASR_RUN_REAL_TRANSCRIBE") == "1"
AUDIO = os.environ.get("ASR_REAL_AUDIO", "").strip()
HAS_AUDIO = bool(AUDIO) and os.path.isfile(AUDIO)


@unittest.skipUnless(RUN_LOAD, "R1 disabled; set ASR_RUN_REAL_MODEL=1 with authorisation")
class RealModelLoadTests(unittest.TestCase):
    def test_model_loads_offline(self):
        from core.asr import ASRConfig, ASREngine

        engine = ASREngine(ASRConfig())
        self.assertIsNone(engine._ensure_loaded())


@unittest.skipUnless(
    RUN_TRANSCRIBE and HAS_AUDIO,
    "R2 disabled; set ASR_RUN_REAL_TRANSCRIBE=1 and ASR_REAL_AUDIO to an existing audio file",
)
class RealModelTranscribeTests(unittest.TestCase):
    def test_transcribe_returns_structured_result(self):
        from core.asr import ASRConfig, ASREngine

        result = ASREngine(ASRConfig()).transcribe(AUDIO)
        self.assertIn(result.status, {"success", "partial", "failed"})
        self.assertEqual(result.schema_version, "asr_result/v1")


if __name__ == "__main__":
    unittest.main()
