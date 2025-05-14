from enum import StrEnum
from pydantic import BaseModel
from openai.types.responses.response_input_param import ResponseInputParam
from openai.types.responses.easy_input_message_param import EasyInputMessageParam


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
