"""Conversation package.

Manages multi-turn chat sessions, conversation state, reply triggers,
and conversation history logging.
"""

from .chat import GenAIChatManager
from .log import ConversationLog
from .persona import PersonaManager
from .policy import ReplyTriggerPolicy, TriggerState

__all__ = [
    "GenAIChatManager",
    "ReplyTriggerPolicy",
    "TriggerState",
    "ConversationLog",
    "PersonaManager",
]
