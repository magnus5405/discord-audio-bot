"""Audio preprocessing and format conversion utilities."""

from __future__ import annotations

import logging
from array import array

logger = logging.getLogger(__name__)


def convert_to_linear16(
    pcm_bytes: bytes,
    from_sample_rate: int,
    to_sample_rate: int | None = None,
    channels: int = 2,
) -> bytes:
    """
    Convert PCM audio to LINEAR16 format at target sample rate.

    Discord provides 48 kHz stereo PCM. We downmix to mono and can optionally
    resample to a lower rate for STT.

    Args:
        pcm_bytes: Raw PCM audio data
        from_sample_rate: Source sample rate
        to_sample_rate: Target sample rate. If omitted or equal to the source
            sample rate, no resampling is performed.
        channels: Number of channels

    Returns:
        Converted PCM audio bytes
    """
    target_rate = from_sample_rate if to_sample_rate is None else to_sample_rate
    logger.debug("Audio preprocessing: %s Hz -> %s Hz", from_sample_rate, target_rate)

    mono_bytes = to_mono(pcm_bytes, channels=channels)
    if target_rate == from_sample_rate:
        return mono_bytes

    return resample_linear16_mono(
        pcm_bytes=mono_bytes,
        from_sample_rate=from_sample_rate,
        to_sample_rate=target_rate,
    )


def resample_linear16_mono(
    pcm_bytes: bytes,
    from_sample_rate: int,
    to_sample_rate: int,
) -> bytes:
    """Resample mono 16-bit PCM using integer-ratio decimation.

    This keeps phase-three dependencies light while supporting the common
    Discord 48 kHz -> STT 16 kHz path.
    """
    if from_sample_rate <= 0 or to_sample_rate <= 0:
        raise ValueError("Sample rates must be positive.")
    if from_sample_rate == to_sample_rate:
        return pcm_bytes
    if from_sample_rate % to_sample_rate != 0:
        raise ValueError(
            f"Unsupported resample ratio: {from_sample_rate} -> {to_sample_rate}."
        )

    step = from_sample_rate // to_sample_rate
    if step <= 0:
        raise ValueError("Invalid resample step.")

    samples = array("h")
    samples.frombytes(pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)])
    if not samples:
        return b""

    resampled = array("h", samples[::step])
    logger.debug(
        "Resampled mono PCM from %s Hz to %s Hz (%s -> %s samples)",
        from_sample_rate,
        to_sample_rate,
        len(samples),
        len(resampled),
    )
    return resampled.tobytes()


def to_mono(pcm_bytes: bytes, channels: int = 2) -> bytes:
    """
    Convert multi-channel audio to mono by selecting channel 0.

    Args:
        pcm_bytes: Stereo PCM audio data
        channels: Number of channels

    Returns:
        Mono PCM audio bytes
    """
    if channels <= 1:
        return pcm_bytes

    if not pcm_bytes:
        return b""

    frame_width = channels * 2
    usable_length = len(pcm_bytes) - (len(pcm_bytes) % frame_width)
    if usable_length <= 0:
        return b""

    samples = array("h")
    samples.frombytes(pcm_bytes[:usable_length])

    mono_samples = array("h")
    # Use the first channel rather than averaging to avoid phase cancellation.
    for index in range(0, len(samples), channels):
        mono_samples.append(samples[index])

    logger.debug("Converted %s PCM bytes from %s channels to mono", usable_length, channels)
    return mono_samples.tobytes()


def get_audio_duration(pcm_bytes: bytes, sample_rate: int, channels: int = 2) -> float:
    """
    Calculate audio duration from PCM data.

    Args:
        pcm_bytes: PCM audio data
        sample_rate: Sample rate in Hz
        channels: Number of channels

    Returns:
        Duration in seconds
    """
    bytes_per_sample = 2  # 16-bit PCM
    total_samples = len(pcm_bytes) // (bytes_per_sample * channels)
    duration = total_samples / sample_rate
    return duration
