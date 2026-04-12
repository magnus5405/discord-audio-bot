"""Reply trigger policy - silence, mentions, and cooldown."""

import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class TriggerState(Enum):
    """Bot state machine states."""

    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    MENTION_WAITING = "mention_waiting"


class ReplyTriggerPolicy:
    """
    Implements bot reply trigger rules:
    - Default: 5s silence trigger, 3m cooldown
    - Mention: 30s window, reply on 5s silence or time elapse
    - Join: Greet immediately
    - Other User Join: Optional greeting, no trigger
    """

    def __init__(
        self,
        silence_timeout_seconds: float = 5.0,
        cooldown_seconds: float = 180.0,
        mention_window_seconds: float = 30.0,
    ) -> None:
        """
        Initialize trigger policy with configurable timeouts.

        Args:
            silence_timeout_seconds: Silence required to trigger
            cooldown_seconds: Min interval between replies
            mention_window_seconds: Time to wait after mention
        """
        self.silence_timeout_seconds = silence_timeout_seconds
        self.cooldown_seconds = cooldown_seconds
        self.mention_window_seconds = mention_window_seconds

        self.state = TriggerState.LISTENING
        self.last_human_speech_timestamp: float | None = None
        self.last_bot_reply_timestamp: float | None = None
        self.mention_detected_timestamp: float | None = None
        self.mention_triggers: list[str] = []

        logger.info(
            f"ReplyTriggerPolicy initialized: "
            f"silence={silence_timeout_seconds}s, "
            f"cooldown={cooldown_seconds}s, "
            f"mention_window={mention_window_seconds}s"
        )

    def set_mention_triggers(self, names: list[str]) -> None:
        """Set lowercase substrings that open the mention window when found in transcript text."""
        seen: set[str] = set()
        out: list[str] = []
        for raw in names:
            s = str(raw).strip().lower()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
        self.mention_triggers = out
        logger.debug("Mention triggers set: %s", self.mention_triggers)

    def text_contains_mention_trigger(self, text: str) -> bool:
        """True if any configured trigger appears as a substring of *text* (case-insensitive)."""
        if not self.mention_triggers:
            return False
        low = text.lower()
        return any(t in low for t in self.mention_triggers)

    def record_human_speech(self) -> None:
        """Record that human speech was detected."""
        self.last_human_speech_timestamp = time.time()
        logger.debug("Human speech detected")

    def record_mention(self) -> None:
        """Record that bot's nickname was mentioned."""
        if self.state != TriggerState.MENTION_WAITING:
            self.mention_detected_timestamp = time.time()
            self.state = TriggerState.MENTION_WAITING
            logger.info("Mention detected, entering mention window")

    def record_bot_reply(self) -> None:
        """Record that bot sent a reply."""
        self.last_bot_reply_timestamp = time.time()
        self.state = TriggerState.LISTENING
        self.mention_detected_timestamp = None
        logger.debug("Bot reply recorded, cooldown reset")

    def should_trigger_reply(
        self,
        current_time: float | None = None,
        *,
        has_pending_transcript: bool = True,
    ) -> bool:
        """
        Determine if bot should generate a reply now.

        Args:
            current_time: Current timestamp (uses time.time() if not provided)
            has_pending_transcript: Require at least one user transcript since the
                last bot turn (PLAN: silence trigger only with something to reply to)

        Returns:
            True if trigger conditions met, False otherwise
        """
        if current_time is None:
            current_time = time.time()

        if not has_pending_transcript:
            return False

        if self.state == TriggerState.MENTION_WAITING and self.mention_detected_timestamp:
            mention_elapsed = current_time - self.mention_detected_timestamp

            if self.last_human_speech_timestamp:
                silence_elapsed = current_time - self.last_human_speech_timestamp
                if silence_elapsed >= self.silence_timeout_seconds:
                    logger.info("Mention window: silence detected, triggering reply")
                    self.state = TriggerState.LISTENING
                    self.mention_detected_timestamp = None
                    return True

            if mention_elapsed >= self.mention_window_seconds:
                logger.info("Mention window: timeout elapsed, forcing reply")
                self.state = TriggerState.LISTENING
                self.mention_detected_timestamp = None
                return True

            return False

        if not self.last_human_speech_timestamp:
            return False

        silence_elapsed = current_time - self.last_human_speech_timestamp

        if silence_elapsed < self.silence_timeout_seconds:
            return False

        if self.last_bot_reply_timestamp:
            cooldown_elapsed = current_time - self.last_bot_reply_timestamp
            if cooldown_elapsed < self.cooldown_seconds:
                logger.debug(
                    f"Cooldown active: {cooldown_elapsed:.1f}s / {self.cooldown_seconds}s"
                )
                return False

        logger.info(f"Trigger condition met: silence_elapsed={silence_elapsed:.1f}s")
        return True

    def get_state(self) -> TriggerState:
        """Get current state machine state."""
        return self.state

    def set_state(self, state: TriggerState) -> None:
        """Set state machine state."""
        self.state = state
        logger.debug(f"State changed to: {state.value}")

    def snapshot_for_ui(self, now: float | None = None) -> tuple[bool, float, float]:
        """
        Values for dashboards: mention-window active, seconds left in that window,
        and seconds remaining on the post-reply cooldown timer.

        Mention window is active only in MENTION_WAITING with a recorded timestamp.
        Cooldown uses time since the last bot reply; 0.0 if no reply yet or cooldown elapsed.
        """
        if now is None:
            now = time.time()

        mention_waiting = (
            self.state == TriggerState.MENTION_WAITING
            and self.mention_detected_timestamp is not None
        )
        mention_left = 0.0
        if mention_waiting and self.mention_detected_timestamp is not None:
            mention_left = max(
                0.0, self.mention_window_seconds - (now - self.mention_detected_timestamp)
            )

        cooldown_left = 0.0
        if self.last_bot_reply_timestamp is not None:
            cooldown_left = max(
                0.0, self.cooldown_seconds - (now - self.last_bot_reply_timestamp)
            )

        return mention_waiting, mention_left, cooldown_left
