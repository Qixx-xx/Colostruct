"""End-to-end orchestration for one ColoStruct case.

The production pipeline will eventually replace the mock ASR and mock LLM
stages with real providers.  This module fixes the sequencing and payload
contract now:

1. stitch uploaded audio with :mod:`core.audio_merge`;
2. produce ordered ASR segments (mock in this MVP);
3. de-noise them with :mod:`core.cleanup`;
4. obtain an extraction (mock or caller-supplied);
5. audit it with :mod:`core.validate`;
6. return the front-end payload.

The mock ASR transcript is intentionally fixed so the default mock extraction
can reference quotes that really exist.  A caller-supplied ``mock_llm_dict``
must reference the generated ``segment_id`` values and matching quotes, or the
audit will (correctly) flag it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

if __package__:
    from . import audio_merge, cleanup, validate
    from .pathology_schema import (
        ColoStructExtraction,
        Evidence,
        FieldModel,
    )
else:  # pragma: no cover - exercised when running ``python core/pipeline.py``
    import audio_merge
    import cleanup
    import validate
    from pathology_schema import (
        ColoStructExtraction,
        Evidence,
        FieldModel,
    )

__all__ = ["STORAGE_AUDIO_DIR", "process_case"]

logger = logging.getLogger(__name__)

#: Root of the project, resolved from this file so the pipeline does not depend
#: on the caller's current working directory.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: Stitched audio is persisted here; one sub-directory per case.
STORAGE_AUDIO_DIR: Final[Path] = PROJECT_ROOT / "storage" / "audio"


@dataclass(frozen=True)
class _MockCase:
    """One canned ASR/extraction pair used by the local MVP.

    Attributes:
        text: Raw ASR text for the segment, including fillers to exercise the
            cleanup layer.
        field_key: Canonical 15-field key supported by this segment.
        value: Mock extracted value.
        quote: Quote that must survive cleanup and support ``value``.
    """

    text: str
    field_key: str
    value: str
    quote: str


#: Ordered mock segments.  The first N cases are used for N uploaded segments;
#: additional segments cycle through the texts without duplicating fields.
_MOCK_ASR_CASES: Final[tuple[_MockCase, ...]] = (
    _MockCase(
        text="呃...呢個 tumour 呢，um...大概 3 cm 啦",
        field_key="tumour_dimension",
        value="3 cm",
        quote="大概 3 cm",
    ),
    _MockCase(
        text="但係我睇到 4 cm，其實 5 cm，遠端切緣 5 cm",
        field_key="proximal_and_distal_margins",
        value="5 cm",
        quote="遠端切緣 5 cm",
    ),
    _MockCase(
        text="淋巴結 2/14 有轉移",
        field_key="lymph_node_status",
        value="2/14",
        quote="淋巴結 2/14 有轉移",
    ),
)


def _mock_asr_from_offsets(offsets: list[dict]) -> list[dict]:
    """Build deterministic mock ASR segments from the audio offset table.

    One transcript segment is created per successfully merged audio segment.
    ``segment_id`` follows the original upload index (``seg-001`` for index 0),
    so skipped corrupt files leave visible gaps rather than renumbering the
    remaining segments.

    Args:
        offsets: Offset table returned by
            :func:`core.audio_merge.merge_audio_segments`.

    Returns:
        Ordered ASR-like segments with ``segment_id``, ``text``, ``start``, and
        ``end``.
    """
    segments: list[dict] = []

    for position, offset in enumerate(offsets):
        case = _MOCK_ASR_CASES[position % len(_MOCK_ASR_CASES)]
        segment_index = int(offset["segment_index"])
        start = float(offset["offset_sec"])
        duration = float(offset["duration_sec"])

        segments.append(
            {
                "segment_id": f"seg-{segment_index + 1:03d}",
                "text": case.text,
                "start": start,
                "end": round(start + duration, 3),
            }
        )

    return segments


def _default_mock_extraction(
    clean_segments: list[dict],
) -> ColoStructExtraction:
    """Build the local fallback extraction from the cleaned mock transcript.

    The mock deliberately omits ``status``: the Pydantic default is
    ``ABSENT``, and :func:`core.validate.audit_extraction` must promote verified
    fields to ``POPULATED``.  This mirrors the real LLM contract where final
    status is back-end-owned.

    Args:
        clean_segments: Cleaned ASR segments in timeline order.

    Returns:
        A partial :class:`ColoStructExtraction`; the schema fills the remaining
        fields as absent.
    """
    fields: dict[str, FieldModel] = {}

    for position, segment in enumerate(clean_segments):
        case = _MOCK_ASR_CASES[position % len(_MOCK_ASR_CASES)]
        if case.field_key in fields:
            continue

        fields[case.field_key] = FieldModel(
            value=case.value,
            evidence=[
                Evidence(
                    segment_id=str(segment["segment_id"]),
                    quote=case.quote,
                )
            ],
        )

    return ColoStructExtraction(fields=fields)


def process_case(
    audio_file_paths: list[str],
    mock_llm_dict: dict | None = None,
) -> dict:
    """Run the complete mock-backed ColoStruct pipeline for one case.

    Args:
        audio_file_paths: Uploaded audio files in submission order.
        mock_llm_dict: Optional extraction-shaped dictionary.  When it is
            non-empty, it is validated into a
            :class:`~core.pathology_schema.ColoStructExtraction`; otherwise a
            built-in mock extraction is used.  A supplied dictionary must use
            the generated ``segment_id`` values and quotes that occur in the
            cleaned mock transcript.

    Returns:
        The front-end payload::

            {
                "audio_url": str,
                "clean_segments": list[dict],
                "fields": dict,
                "override_logs": list[dict],
                "has_block": bool,
            }

    Raises:
        ValueError: If no audio paths are supplied or none can be merged.
        pydantic.ValidationError: If ``mock_llm_dict`` is not a valid
            extraction.
    """
    if not audio_file_paths:
        raise ValueError("audio_file_paths must contain at least one audio file")

    case_id = uuid.uuid4().hex
    stitched_path = STORAGE_AUDIO_DIR / case_id / "stitched.wav"

    offsets = audio_merge.merge_audio_segments(
        audio_file_paths,
        str(stitched_path),
    )
    mock_asr = _mock_asr_from_offsets(offsets)
    clean_segments = cleanup.clean_transcript(mock_asr)

    if mock_llm_dict:
        llm_result = ColoStructExtraction.model_validate(mock_llm_dict)
    else:
        llm_result = _default_mock_extraction(clean_segments)

    audited_result = validate.audit_extraction(llm_result, clean_segments)
    dumped = audited_result.model_dump(mode="json")

    logger.info(
        "Processed case %s: segments=%d fields=%d has_block=%s",
        case_id,
        len(clean_segments),
        len(dumped["fields"]),
        audited_result.has_block,
    )

    return {
        "audio_url": str(stitched_path),
        "clean_segments": clean_segments,
        "fields": dumped["fields"],
        "override_logs": dumped["override_logs"],
        "has_block": audited_result.has_block,
    }


if __name__ == "__main__":
    import json
    import math
    import struct
    import tempfile
    import wave

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    def _write_test_tone(
        path: Path,
        *,
        duration_sec: float,
        frequency: float,
        frame_rate: int,
        channels: int,
    ) -> None:
        """Write a short PCM WAV tone with a deliberately non-target format."""
        frame_count = round(duration_sec * frame_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(
                32767 * 0.2 * math.sin(2 * math.pi * frequency * index / frame_rate)
            )
            frames.extend(struct.pack("<h", sample) * channels)

        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(frame_rate)
            wav_file.writeframes(bytes(frames))

    with tempfile.TemporaryDirectory(prefix="colostruct-pipeline-") as tmp:
        work_dir = Path(tmp)
        first = work_dir / "segment-1.wav"
        second = work_dir / "segment-2.wav"

        _write_test_tone(
            first,
            duration_sec=0.8,
            frequency=440.0,
            frame_rate=44100,
            channels=2,
        )
        _write_test_tone(
            second,
            duration_sec=0.5,
            frequency=880.0,
            frame_rate=22050,
            channels=1,
        )

        payload = process_case([str(first), str(second)])

        print(
            json.dumps(
                {
                    "audio_url": payload["audio_url"],
                    "clean_segments": payload["clean_segments"],
                    "populated_fields": {
                        key: {
                            "value": value["value"],
                            "status": value["status"],
                            "evidence": value["evidence"],
                        }
                        for key, value in payload["fields"].items()
                        if value["value"] is not None
                    },
                    "override_logs": payload["override_logs"],
                    "has_block": payload["has_block"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        assert Path(payload["audio_url"]).exists()
        assert len(payload["clean_segments"]) == 2
        assert payload["fields"]["tumour_dimension"]["status"] == "populated"
        assert payload["fields"]["proximal_and_distal_margins"]["status"] == "populated"
        assert payload["has_block"] is False
        assert payload["override_logs"] == []

        print("\nAll pipeline assertions passed.")
        print(f"Stitched audio kept at: {payload['audio_url']}")
