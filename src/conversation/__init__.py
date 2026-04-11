"""Conversation package.

Manages multi-turn chat sessions, conversation state, reply triggers,
and conversation history logging.
"""

from .chat import GenAIChatManager
from .policy import ReplyTriggerPolicy, TriggerState
from .log import ConversationLog
from .persona import PersonaManager

__all__ = [
    "GenAIChatManager",
    "ReplyTriggerPolicy",
    "TriggerState",
    "ConversationLog",
    "PersonaManager",
]
