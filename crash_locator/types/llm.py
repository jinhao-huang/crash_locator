from enum import StrEnum
from pydantic import BaseModel
from typing import Self


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    role: Role
    content: str
    reasoning_content: str | None = None


class Conversation(BaseModel):
    messages: list[Message]

    def append(self, message: Message):
        self.messages.append(message)

    def messages_copy(self) -> "Conversation":
        return Conversation(messages=self.messages.copy())

    def dump_messages(self) -> list[dict]:
        return [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in self.messages
        ]

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
    content: str
    reasoning_content: str | None = None
    token_usage: TokenUsage


class ReasoningEffort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
