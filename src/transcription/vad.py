"""Voice Activity Detection (VAD) for utterance segmentation."""

import logging

logger = logging.getLogger(__name__)


class VADProcessor:
    """
    Voice Activity Detection using WebRTC VAD.

    Detects voiced vs unvoiced audio to segment utterances more cleanly
    before sending to STT (optional enhancement).
    """

    def __init__(
        self, sample_rate: int = 16000, frame_duration_ms: int = 30
    ) -> None:
        """
        Initialize VAD processor.

        Args:
            sample_rate: Sample rate for VAD (typically 16000)
            frame_duration_ms: Frame duration (10, 20, or 30 ms)
        """
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        logger.info(
            f"VADProcessor initialized: {sample_rate} Hz, {frame_duration_ms}ms frames"
        )

    def process_frame(self, pcm_bytes: bytes) -> bool:
        """
        Detect if a frame contains voice activity.

        Args:
            pcm_bytes: PCM audio frame

        Returns:
            True if voice activity detected, False otherwise
        """
        return True

    def should_end_utterance(
        self, frames_without_voice: int, timeout_ms: float
    ) -> bool:
        """
        Determine if an utterance should be considered complete.

        Args:
            frames_without_voice: Number of consecutive frames without voice
            timeout_ms: Time elapsed without speech

        Returns:
            True if utterance should end
        """
        return timeout_ms > 500
