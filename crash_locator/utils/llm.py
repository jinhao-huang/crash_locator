from openai import OpenAI
from crash_locator.config import Config
from crash_locator.my_types import ReportInfo, Candidate
from crash_locator.prompt import Prompt
from crash_locator.exceptions import UnExpectedResponseException
from openai.types.chat.chat_completion_message_param import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
)
import logging
from typing import Callable
import json
from pathlib import Path

logger = logging.getLogger(__name__)

client = OpenAI(base_url=Config.OPENAI_BASE_URL, api_key=Config.OPENAI_API_KEY)


def _query_llm(messages: list[ChatCompletionMessageParam]):
    conversation = messages.copy()
    logger.debug("Preparing to query LLM")
    response = client.chat.completions.create(
        model=Config.OPENAI_MODEL, messages=conversation, timeout=240
    )
    logger.debug("LLM query completed")
    conversation.append(
        ChatCompletionAssistantMessageParam(
            content=response.choices[0].message.content, role="assistant"
        )
    )

    return conversation


def _query_llm_with_retry(
    messages: list[ChatCompletionMessageParam],
    retry_times: int,
    validate_func: Callable[[str], bool],
):
    for times in range(retry_times):
        conversation = _query_llm(messages)
        content = conversation[-1]["content"]
        if validate_func(content):
            logger.info(
                f"Get valid response from LLM, retry {times + 1} / {retry_times}"
            )
            logger.debug(f"Response: {content}")
            return conversation
        logger.error(
            f"Get unexpected response from LLM, retry {times + 1} / {retry_times}"
        )
        logger.debug(f"Response: {content}")
    raise UnExpectedResponseException("Invalid response from LLM")


def _save_conversation(conversation: list[ChatCompletionMessageParam], dir: Path):
    dir.mkdir(parents=True, exist_ok=True)
    with open(dir / "conversation.json", "w") as f:
        json.dump(conversation, f)
    with open(dir / "conversation.md", "w") as f:
        for message in conversation:
            f.write(f"## {message['role']}\n")
            f.write(f"```text\n{message['content']}\n```\n")


def _save_remaining_candidates(candidates: list[Candidate], dir: Path):
    dir.mkdir(parents=True, exist_ok=True)
    with open(dir / "remaining_candidates.json", "w") as f:
        json.dump(
            [candidate.model_dump() for candidate in candidates],
            f,
            indent=4,
        )


def query_filter_candidate(report_info: ReportInfo) -> list[Candidate]:
    messages = [
        ChatCompletionSystemMessageParam(
            content=Prompt.FILTER_CANDIDATE_SYSTEM, role="system"
        ),
        ChatCompletionUserMessageParam(
            content=Prompt.FILTER_CANDIDATE_CRASH(report_info),
            role="user",
        ),
    ]

    remaining_candidates = []
    for candidate in report_info.sorted_candidates:
        messages.append(
            ChatCompletionUserMessageParam(
                content=Prompt.FILTER_CANDIDATE_METHOD(report_info, candidate),
                role="user",
            )
        )
        messages = _query_llm_with_retry(
            messages,
            3,
            lambda x: ("Yes" in x and "No" not in x) or ("No" in x and "Yes" not in x),
        )
        if "Yes" in messages[-1]["content"]:
            remaining_candidates.append(candidate)

    _save_conversation(messages, Config.RESULT_REPORT_FILTER_DIR(report_info.apk_name))
    _save_remaining_candidates(
        remaining_candidates,
        Config.RESULT_REPORT_FILTER_DIR(report_info.apk_name),
    )
    logger.info(
        f"Candidate filtering completed, before: {len(report_info.candidates)}, after: {len(remaining_candidates)}"
    )
    return remaining_candidates
