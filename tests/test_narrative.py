"""Tests for the macro/micro narrative feature (mock mode, no model calls)."""
from __future__ import annotations

import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from core.cleanup import clean_narrative_output
from core.pathology_schema import (
    ColoStructExtraction,
    FullClinicalReport,
    NarrativeSection,
)
from core.pipeline import process_full_report
from core.validate import NarrativeValidationError, validate_narrative


def _write_tone(path: Path) -> None:
    """Write a short 16 kHz mono WAV so audio_merge has something to stitch."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        frames = bytearray()
        for index in range(1_600):
            sample = int(2_000 * math.sin(2 * math.pi * 440 * index / 16_000))
            frames.extend(struct.pack("<h", sample))
        handle.writeframes(bytes(frames))


class NarrativeCleanupTests(unittest.TestCase):
    def test_strips_fences_and_preamble_but_keeps_numbering(self):
        raw = (
            "好的，以下是大体检查：\n"
            "```markdown\n"
            "1) Cut opened specimen.\n"
            "2) Distal margin negative.\n"
            "```\n"
            "希望以上对您有帮助。"
        )
        self.assertEqual(
            clean_narrative_output(raw),
            "1) Cut opened specimen.\n2) Distal margin negative.",
        )

    def test_strips_english_preamble(self):
        raw = (
            "Here is the polished report:\n"
            "```\n"
            "1&2) Sections show adenocarcinoma.\n"
            "```\n"
            "Hope this helps."
        )
        self.assertEqual(
            clean_narrative_output(raw),
            "1&2) Sections show adenocarcinoma.",
        )

    def test_keeps_clinical_heading(self):
        raw = "MACROSCOPIC EXAMINATION:\n1) Cut opened specimen."
        self.assertEqual(clean_narrative_output(raw), raw)

    def test_rejects_non_string(self):
        with self.assertRaises(TypeError):
            clean_narrative_output(123)  # type: ignore[arg-type]


class NarrativeValidationTests(unittest.TestCase):
    def test_accepts_up_to_twenty_percent_growth(self):
        raw = "a" * 100
        self.assertTrue(validate_narrative("a" * 120, raw))

    def test_rejects_more_than_twenty_percent_growth(self):
        with self.assertRaises(NarrativeValidationError):
            validate_narrative("a" * 121, "a" * 100)

    def test_rejects_empty_inputs(self):
        with self.assertRaises(NarrativeValidationError):
            validate_narrative("text", "")
        with self.assertRaises(NarrativeValidationError):
            validate_narrative("", "text")

    def test_rejects_non_strings(self):
        with self.assertRaises(TypeError):
            validate_narrative(None, "text")  # type: ignore[arg-type]


class FullClinicalReportTests(unittest.TestCase):
    def test_defaults_are_absent(self):
        report = FullClinicalReport(diagnosis=ColoStructExtraction())
        self.assertEqual(report.macro.status, "absent")
        self.assertIsNone(report.macro.text)
        self.assertEqual(report.micro.status, "absent")
        self.assertEqual(len(report.diagnosis.fields), 15)

    def test_section_status_and_text(self):
        section = NarrativeSection(text="1) Sample.", status="success")
        self.assertEqual(section.text, "1) Sample.")
        self.assertEqual(section.status, "success")


class FullReportMockTests(unittest.TestCase):
    def test_mock_report_uses_36800_text(self):
        with tempfile.TemporaryDirectory(prefix="colostruct-narrative-test-") as tmp:
            tone = Path(tmp) / "tone.wav"
            _write_tone(tone)
            with mock.patch.dict(
                os.environ, {"COLOSTRUCT_NARRATIVE_MOCK": "1"}, clear=False
            ), mock.patch(
                "core.pipeline.STORAGE_AUDIO_DIR", Path(tmp) / "storage" / "audio"
            ), mock.patch(
                # This test only covers the narrative mock path; keep the
                # diagnosis side on the deterministic mock pipeline even when
                # the real process_case_real is available.
                "core.pipeline.process_case_real",
                None,
            ):
                report = process_full_report(str(tone), str(tone), str(tone))

        self.assertEqual(len(report.diagnosis.fields), 15)
        self.assertFalse(report.diagnosis.has_block)
        self.assertEqual(report.macro.status, "success")
        self.assertEqual(report.micro.status, "success")
        self.assertIn("1) Cut opened large intestine", report.macro.text or "")
        self.assertIn("1&2) Sections on the sigmoid tumour", report.micro.text or "")


if __name__ == "__main__":
    unittest.main()
