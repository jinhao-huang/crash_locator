from enum import StrEnum
from pydantic import BaseModel
from typing import Self


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    role: Role
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class Conversation(BaseModel):
    messages: list[Message]

    def append(self, message: Message):
        self.messages.append(message)

    def messages_copy(self) -> "Conversation":
        return Conversation(messages=self.messages.copy())

    def dump_messages(self) -> list[dict]:
        msgs = []
        for message in self.messages:
            msg = {}
            msg["role"] = message.role
            if message.content is not None:
                msg["content"] = message.content
            if message.tool_calls is not None:
                msg["tool_calls"] = message.tool_calls
            if message.tool_call_id is not None:
                msg["tool_call_id"] = message.tool_call_id
            msgs.append(msg)
        return msgs

    def __getitem__(self, index: int) -> Message:
        return self.messages[index]


class APIType(StrEnum):
    COMPLETION = "completion"
    RESPONSE = "response"


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Self) -> Self:
        return self.__class__(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class Response(BaseModel):
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[dict] | None = None
    token_usage: TokenUsage


class ReasoningEffort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
