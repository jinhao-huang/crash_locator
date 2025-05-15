from enum import StrEnum
from pydantic import BaseModel
from openai.types.responses.response_input_param import ResponseInputParam
from openai.types.responses.easy_input_message_param import EasyInputMessageParam
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

    def dump_response_input(self) -> ResponseInputParam:
        messages = [
            EasyInputMessageParam(
                content=message.content,
                role=message.role,
            )
            for message in self.messages
        ]
        return messages


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
