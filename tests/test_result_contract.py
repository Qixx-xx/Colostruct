"""Contract tests for core.llm.result using the real backend schema."""
from __future__ import annotations

import unittest

from pydantic import ValidationError

from core.pathology_schema import ColoStructExtraction
from core.llm import result


def make_extraction():
    """Construct a minimal real backend extraction object."""
    return ColoStructExtraction(fields={}, override_logs=[], has_block=False)


def make_candidate(**overrides):
    payload = {
        "candidate_type": "normalization",
        "risk_level": "low",
        "original_span": "a",
        "suggested_span": "b",
        "evidence_segment_ids": ["seg-0001"],
    }
    payload.update(overrides)
    return result.CorrectionCandidate(**payload)


def make_result(**overrides):
    payload = {
        "extraction": make_extraction(),
        "pass_a_result": result.PassAResult(),
        "diagnostics": result.Diagnostics(),
    }
    payload.update(overrides)
    return result.AGroupResult(**payload)


class AGroupResultStructureTests(unittest.TestCase):
    def test_minimal_valid_has_exactly_five_parts(self):
        value = make_result()
        self.assertEqual(
            set(value.model_dump().keys()),
            {"extraction", "pass_a_result", "field_uncertainties", "diagnostics", "schema_version"},
        )
        self.assertEqual(value.schema_version, "a_group_result/v1")

    def test_required_parts_cannot_be_missing(self):
        for field in ("extraction", "pass_a_result", "diagnostics"):
            with self.subTest(field=field):
                payload = {
                    "extraction": make_extraction(),
                    "pass_a_result": result.PassAResult(),
                    "diagnostics": result.Diagnostics(),
                }
                payload.pop(field)
                with self.assertRaises(ValidationError):
                    result.AGroupResult(**payload)

    def test_extraction_must_not_be_none(self):
        with self.assertRaises(ValidationError):
            make_result(extraction=None)

    def test_schema_version_is_literal(self):
        with self.assertRaises(ValidationError):
            make_result(schema_version="a_group_result/v2")

    def test_unknown_top_level_field_is_rejected(self):
        with self.assertRaises(ValidationError):
            make_result(unexpected_field="x")

    def test_json_roundtrip(self):
        value = make_result()
        restored = result.AGroupResult.model_validate_json(value.model_dump_json())
        self.assertEqual(restored.model_dump(), value.model_dump())


class StageDiagnosticTests(unittest.TestCase):
    def test_stage_status_vocabulary(self):
        for status in ("success", "partial", "failed", "skipped"):
            stage = result.StageDiagnostic(stage="pass_b", status=status)
            self.assertEqual(stage.status, status)

    def test_legacy_status_values_rejected(self):
        for status in ("ok", "degraded"):
            with self.subTest(status=status):
                with self.assertRaises(ValidationError):
                    result.StageDiagnostic(stage="pass_b", status=status)

    def test_asr_is_not_a_diagnostic_stage(self):
        with self.assertRaises(ValidationError):
            result.StageDiagnostic(stage="asr", status="success")

    def test_has_failed_stage_is_auxiliary(self):
        value = make_result(
            diagnostics=result.Diagnostics(
                stages=[result.StageDiagnostic(stage="pass_a", status="failed")]
            )
        )
        self.assertTrue(value.has_failed_stage)

        partial = make_result(
            diagnostics=result.Diagnostics(
                stages=[result.StageDiagnostic(stage="pass_b", status="partial")]
            )
        )
        self.assertFalse(partial.has_failed_stage)


class PassAResultTests(unittest.TestCase):
    def test_skipped_requires_reason_and_keeps_empty_list(self):
        with self.assertRaises(ValidationError):
            result.PassAResult(status="skipped")
        skipped = result.PassAResult(status="skipped", skip_reason="ASR-only mode")
        self.assertEqual(skipped.segments, [])
        self.assertEqual(skipped.status, "skipped")

    def test_default_status_is_success(self):
        self.assertEqual(result.PassAResult().status, "success")


class FieldUncertaintyTests(unittest.TestCase):
    def test_level_vocabulary(self):
        for level in ("low", "medium", "high"):
            self.assertEqual(result.FieldUncertainty(level=level, reason="r").level, level)

    def test_invalid_level_rejected(self):
        with self.assertRaises(ValidationError):
            result.FieldUncertainty(level="unknown", reason="r")

    def test_unknown_field_key_rejected(self):
        with self.assertRaises(ValidationError):
            make_result(
                field_uncertainties={
                    "not_a_real_field": result.FieldUncertainty(level="low", reason="r")
                }
            )

    def test_canonical_field_key_accepted(self):
        value = make_result(
            field_uncertainties={
                "tumour_site": result.FieldUncertainty(level="medium", reason="two sites")
            }
        )
        self.assertIn("tumour_site", value.field_uncertainties)


class CorrectionCandidateTests(unittest.TestCase):
    def test_candidate_type_vocabulary(self):
        for candidate_type in ("normalization", "suspected_asr_error", "doctor_self_correction"):
            with self.subTest(candidate_type=candidate_type):
                value = make_candidate(candidate_type=candidate_type)
                self.assertEqual(value.candidate_type, candidate_type)

    def test_invalid_candidate_type_rejected(self):
        with self.assertRaises(ValidationError):
            make_candidate(candidate_type="confirmed_fact")

    def test_risk_level_vocabulary(self):
        for risk_level in ("low", "medium", "high"):
            with self.subTest(risk_level=risk_level):
                self.assertEqual(make_candidate(risk_level=risk_level).risk_level, risk_level)

    def test_invalid_risk_level_rejected(self):
        with self.assertRaises(ValidationError):
            make_candidate(risk_level="critical")

    def test_evidence_segment_ids_accepts_string_list(self):
        value = make_candidate(evidence_segment_ids=["seg-0001", "seg-0002"])
        self.assertEqual(value.evidence_segment_ids, ["seg-0001", "seg-0002"])

    def test_evidence_segment_ids_rejects_non_list(self):
        with self.assertRaises(ValidationError):
            make_candidate(evidence_segment_ids="seg-0001")

    def test_confidence_bounds(self):
        for good in (0.0, 0.5, 1.0):
            with self.subTest(good=good):
                self.assertEqual(make_candidate(confidence=good).confidence, good)
        for bad in (-0.01, 1.01):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    make_candidate(confidence=bad)

    def test_candidate_rejects_override_fields(self):
        # AI candidates must not be shaped like a backend OverrideLog.
        with self.assertRaises(ValidationError):
            make_candidate(field_name="tumour_site")
        self.assertNotIn("old_evidence", make_candidate().model_dump())
        self.assertNotIn("new_evidence", make_candidate().model_dump())


if __name__ == "__main__":
    unittest.main()
