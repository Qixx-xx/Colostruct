"""Merge ordered audio segments into one 16 kHz mono timeline.

ColoStruct receives a case as several uploads recorded at different times.  The
pipeline stitches them in submission order, inserts 0.5 s of silence between
consecutive segments, and returns a cumulative offset table.  The offset table
is what later lets a transcript segment (identified by ``segment_id``) resolve
to a global position in the stitched WAV.

Example
-------
.. code-block:: python

    offsets = merge_audio_segments(["a.wav", "b.wav"], "stitched.wav")
    assert offsets[0]["offset_sec"] == 0.0
    assert offsets[1]["offset_sec"] == offsets[0]["duration_sec"] + 0.5

The function is deliberately tolerant of a single bad upload: a corrupt file is
logged and skipped, and the remaining files are still merged.  If no file can be
read, a ``ValueError`` is raised because there is no timeline to produce.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydub import AudioSegment

logger = logging.getLogger(__name__)

#: All stitched audio uses this sample rate.
TARGET_FRAME_RATE: int = 16_000

#: All stitched audio uses one channel.
TARGET_CHANNELS: int = 1

#: 16-bit PCM keeps the stitched WAV broadly compatible with ASR tooling.
TARGET_SAMPLE_WIDTH: int = 2

#: Forced pause between two consecutive uploaded segments, in milliseconds.
SILENCE_MS: int = 500

__all__ = [
    "SILENCE_MS",
    "TARGET_CHANNELS",
    "TARGET_FRAME_RATE",
    "TARGET_SAMPLE_WIDTH",
    "merge_audio_segments",
]


def _silence() -> AudioSegment:
    """Return exactly :data:`SILENCE_MS` of silent 16 kHz mono 16-bit audio."""
    return (
        AudioSegment.silent(
            duration=SILENCE_MS,
            frame_rate=TARGET_FRAME_RATE,
        )
        .set_channels(TARGET_CHANNELS)
        .set_sample_width(TARGET_SAMPLE_WIDTH)
    )


def _normalise(segment: AudioSegment) -> AudioSegment:
    """Convert one segment to the format used by the stitched timeline.

    Args:
        segment: A decoded pydub segment.

    Returns:
        The same audio as 16 kHz, mono, 16-bit PCM.
    """
    return (
        segment.set_frame_rate(TARGET_FRAME_RATE)
        .set_channels(TARGET_CHANNELS)
        .set_sample_width(TARGET_SAMPLE_WIDTH)
    )


def _load_segment(path: Path) -> AudioSegment | None:
    """Load and normalise one audio file, or return ``None`` when unusable.

    A failure in one file must not abort the whole case.  The exception is
    logged with the file path and type, and the caller continues with the next
    upload.  Non-WAV containers (for example MP3 or M4A) require ``ffmpeg`` on
    ``PATH``; WAV files are decoded by pydub directly.

    Args:
        path: Path to the uploaded audio file.

    Returns:
        A normalised :class:`AudioSegment`, or ``None`` when the file is
        missing, corrupt, empty, or cannot be decoded.
    """
    try:
        segment = AudioSegment.from_file(str(path))
        if len(segment) == 0:
            logger.warning("Skipping empty audio segment: %s", path)
            return None
        return _normalise(segment)
    except Exception as exc:
        if isinstance(exc, FileNotFoundError) and path.exists():
            logger.warning(
                "Skipping audio segment %s: a decoder is unavailable or the "
                "file is unreadable (install ffmpeg for non-WAV formats): %s",
                path,
                exc,
            )
        elif isinstance(exc, FileNotFoundError):
            logger.warning("Skipping missing audio segment: %s", path)
        else:
            logger.warning(
                "Skipping unreadable audio segment %s (%s): %s",
                path,
                type(exc).__name__,
                exc,
            )
        logger.debug("Audio load failure details for %s", path, exc_info=True)
        return None


def merge_audio_segments(file_paths: list[str], output_path: str) -> list[dict]:
    """Merge uploaded audio segments in order and return their global offsets.

    Each readable segment is converted to 16 kHz mono 16-bit PCM.  Segments are
    appended in the order given, with :data:`SILENCE_MS` of silence inserted
    between every pair of consecutive readable segments (never before the first
    or after the last).  The stitched audio is written to ``output_path``.

    The returned offset table has one entry per *successfully merged* segment::

        [
            {
                "segment_index": 0,
                "source_file": "a.wav",
                "offset_sec": 0.0,
                "duration_sec": 10.5,
            },
            {
                "segment_index": 1,
                "source_file": "b.wav",
                "offset_sec": 11.0,
                "duration_sec": 5.2,
            },
        ]

    ``segment_index`` is the original position in ``file_paths``.  If a file is
    skipped, the returned indexes can therefore contain gaps (for example
    ``[0, 2]``); this preserves traceability to the upload order.
    ``source_file`` is the file's basename, matching the uploaded filename.
    ``offset_sec`` is the start of the segment in the stitched timeline and
    already includes all preceding segments and silence gaps.  ``duration_sec``
    is the segment's own duration, excluding the silence gap.

    Args:
        file_paths: Uploaded audio paths, in the order they should be stitched.
        output_path: Destination path for the stitched audio.  The container is
            inferred from the suffix (``.wav``, ``.mp3``, ...); a missing suffix
            defaults to WAV.  Parent directories are created automatically.

    Returns:
        The global offset table for the successfully merged segments, in
        stitching order.  There is one entry per successfully merged file; the
        value is never ``None``.

    Raises:
        ValueError: If ``file_paths`` is empty or no file could be read.
        RuntimeError: If the stitched audio cannot be exported.
    """
    if not file_paths:
        raise ValueError("file_paths must contain at least one audio file")

    loaded: list[tuple[int, str, AudioSegment]] = []
    for index, raw_path in enumerate(file_paths):
        path = Path(raw_path)
        segment = _load_segment(path)
        if segment is not None:
            loaded.append((index, path.name, segment))

    if not loaded:
        raise ValueError(
            "No readable audio segments were found; check the input files and "
            "the warnings logged above"
        )

    # Start from the first decoded segment so the accumulator already has the
    # target frame rate, channel count, and sample width.
    first_index, first_source, first_segment = loaded[0]
    merged = first_segment
    offsets: list[dict] = [
        {
            "segment_index": first_index,
            "source_file": first_source,
            "offset_sec": 0.0,
            "duration_sec": round(len(first_segment) / 1000.0, 3),
        }
    ]

    for index, source_file, segment in loaded[1:]:
        merged += _silence()
        offset_sec = len(merged) / 1000.0
        merged += segment
        offsets.append(
            {
                "segment_index": index,
                "source_file": source_file,
                "offset_sec": round(offset_sec, 3),
                "duration_sec": round(len(segment) / 1000.0, 3),
            }
        )

    output = Path(output_path)
    export_format = output.suffix.lower().lstrip(".") or "wav"

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        merged.export(str(output), format=export_format)
    except Exception as exc:
        logger.error("Failed to export merged audio to %s: %s", output, exc)
        raise RuntimeError(f"Failed to export merged audio to {output}") from exc

    logger.info(
        "Merged %d of %d segment(s) into %s (%.3f s)",
        len(loaded),
        len(file_paths),
        output,
        len(merged) / 1000.0,
    )
    return offsets


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
        """Write a short PCM WAV tone, deliberately with a non-target format."""
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

    with tempfile.TemporaryDirectory(prefix="colostruct-audio-") as tmp:
        work_dir = Path(tmp)
        first = work_dir / "segment-1.wav"
        second = work_dir / "segment-2.wav"
        broken = work_dir / "segment-broken.wav"
        stitched = work_dir / "stitched.wav"

        # Different sample rates and channel counts prove the normalisation.
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
        broken.write_bytes(b"this is not a valid audio file")

        print("Test 1: merge two valid segments")
        offsets = merge_audio_segments([str(first), str(second)], str(stitched))
        print(json.dumps(offsets, indent=2, ensure_ascii=False))

        output_audio = AudioSegment.from_wav(str(stitched))
        print(
            "Output: "
            f"{len(output_audio) / 1000.0:.3f}s, "
            f"{output_audio.frame_rate} Hz, "
            f"{output_audio.channels} channel(s)"
        )

        assert output_audio.frame_rate == TARGET_FRAME_RATE
        assert output_audio.channels == TARGET_CHANNELS
        assert output_audio.sample_width == TARGET_SAMPLE_WIDTH
        assert len(offsets) == 2
        assert offsets[0]["offset_sec"] == 0.0
        assert math.isclose(
            offsets[1]["offset_sec"],
            offsets[0]["duration_sec"] + 0.5,
            abs_tol=1e-3,
        )
        gap_total = 0.5 * (len(offsets) - 1)
        expected_total = sum(item["duration_sec"] for item in offsets) + gap_total
        assert math.isclose(
            len(output_audio) / 1000.0,
            expected_total,
            abs_tol=1e-3,
        )

        print("\nTest 2: a corrupt file is skipped, not fatal")
        offsets_with_broken = merge_audio_segments(
            [str(first), str(broken), str(second)],
            str(work_dir / "stitched-with-broken.wav"),
        )
        print(json.dumps(offsets_with_broken, indent=2, ensure_ascii=False))
        assert [item["segment_index"] for item in offsets_with_broken] == [0, 2]
        assert len(offsets_with_broken) == 2

        print("\nAll assertions passed.")
