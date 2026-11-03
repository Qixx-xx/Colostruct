"""Offline contract tests; no Ollama service or clinical data required."""
import unittest

from core.llm.preprocessing import run_pass_a
from core.llm.extraction import run_pass_b
from core.llm.client import LLMError
from core.pathology_schema import PATHOLOGY_FIELD_KEYS, ColoStructExtraction


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate_json(self, *, system, user):
        return self.responses.pop(0)


class AGroupContractTests(unittest.TestCase):
    def test_pass_a_preserves_ids_and_checks_verbatim_override(self):
        segments = [
            {"segment_id": "s1", "text": "tumour in sigmoid", "start": 0, "end": 2},
            {"segment_id": "s2", "text": "sorry, tumour in rectum", "start": 2, "end": 4},
        ]
        response = {
            "corrected_segments": [
                {"segment_id": "s1", "corrected_text": "tumour in sigmoid"},
                {"segment_id": "s2", "corrected_text": "sorry, tumour in rectum"},
            ],
            "override_logs": [{
                "field_name": "tumour_site",
                "old_evidence": {"segment_id": "s1", "quote": "tumour in sigmoid"},
                "new_evidence": {"segment_id": "s2", "quote": "tumour in rectum"},
            }],
        }
        result = run_pass_a(segments, FakeClient([response]))
        self.assertEqual(len(result["corrected_segments"]), 2)
        self.assertEqual(result["override_logs"][0]["new_evidence"]["segment_id"], "s2")
        self.assertEqual(segments[0]["text"], "tumour in sigmoid")

    def test_pass_a_rejects_fabricated_quote(self):
        segments = [{"segment_id": "s1", "text": "tumour in rectum"}]
        response = {
            "corrected_segments": [{"segment_id": "s1", "corrected_text": "tumour in rectum"}],
            "override_logs": [{
                "field_name": "tumour_site",
                "old_evidence": {"segment_id": "s1", "quote": "tumour in sigmoid"},
                "new_evidence": {"segment_id": "s1", "quote": "tumour in rectum"},
            }],
        }
        with self.assertRaises(LLMError):
            run_pass_a(segments, FakeClient([response]))

    def test_pass_b_requires_all_15_fields_and_no_timestamps(self):
        fields = {key: {"value": None, "evidence": []} for key in PATHOLOGY_FIELD_KEYS}
        fields["tumour_site"] = {
            "value": "rectum",
            "evidence": [{"segment_id": "s1", "quote": "tumour in rectum"}],
        }
        result = run_pass_b(
            [{"segment_id": "s1", "text": "tumour in rectum", "start": 0, "end": 1}],
            [{"segment_id": "s1", "corrected_text": "tumour in rectum"}],
            FakeClient([{"fields": fields}]),
        )
        self.assertIsInstance(result, ColoStructExtraction)
        self.assertEqual(len(result.fields), 15)
        self.assertEqual(result.fields["tumour_site"].value, "rectum")

    def test_pass_b_rejects_llm_timestamps(self):
        fields = {key: {"value": None, "evidence": []} for key in PATHOLOGY_FIELD_KEYS}
        fields["tumour_site"] = {
            "value": "rectum",
            "evidence": [{"segment_id": "s1", "quote": "rectum", "start": 0, "end": 1}],
        }
        with self.assertRaises(LLMError):
            run_pass_b([], [], FakeClient([{"fields": fields}]))


if __name__ == "__main__":
    unittest.main()
