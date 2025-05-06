from openai import AsyncOpenAI
from crash_locator.config import config
from openai import RateLimitError, InternalServerError, APIConnectionError
from crash_locator.my_types import ReportInfo, Candidate, RunStatistic
from crash_locator.prompt import Prompt
from crash_locator.exceptions import UnExpectedResponseException
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from openai.types.chat.chat_completion_message_param import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
)
from crash_locator.config import run_statistic
from typing import Callable
import json
from pathlib import Path
from copy import deepcopy
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
    before_log,
    after_log,
)
import logging

logger = logging.getLogger(__name__)

client = AsyncOpenAI(base_url=config.openai_base_url, api_key=config.openai_api_key)


def _purge_conversation(conversation: list[ChatCompletionMessageParam]):
    """
    Purge the reasoning content from the conversation
    """
    messages = deepcopy(conversation)
    for message in messages:
        for key in list(message.keys()):
            if key not in ["content", "role"]:
                del message[key]
    return messages


@retry(
    wait=wait_random_exponential(min=1, max=60),
    stop=stop_after_attempt(6),
    retry=retry_if_exception_type(
        (RateLimitError, InternalServerError, APIConnectionError)
    ),
    before=before_log(logger, logging.WARNING),
    after=after_log(logger, logging.WARNING),
    reraise=True,
)
async def _query_llm(messages: list[ChatCompletionMessageParam]):
    conversation = _purge_conversation(messages)
    logger.info("Preparing to query LLM")
    logger.debug(f"Messages: {conversation}")

    collected_chunks: list[ChatCompletionChunk] = []
    collected_content: list[str | None] = []
    collected_reasoning_content: list[str | None] = []

    response = await client.chat.completions.create(
        model=config.openai_model,
        messages=conversation,
        timeout=240,
        stream=True,
    )

    async for chunk in response:
        logger.debug(f"Received chunk: {chunk}")
        collected_chunks.append(chunk)

        delta = chunk.choices[0].delta
        collected_content.append(delta.content)
        if "reasoning_content" in delta.model_extra:
            collected_reasoning_content.append(delta.model_extra["reasoning_content"])

    full_content = "".join([m for m in collected_content if m is not None])
    full_reasoning_content = "".join(
        [m for m in collected_reasoning_content if m is not None]
    )
    last_chunk = collected_chunks[-1]
    token_usage = RunStatistic.TokenUsage(
        input_tokens=last_chunk.usage.prompt_tokens,
        output_tokens=last_chunk.usage.completion_tokens,
    )
    run_statistic.add_token_usage(token_usage)
    logger.info("LLM query completed")
    logger.debug(f"Full content: {full_content}")
    logger.debug(f"Full reasoning content: {full_reasoning_content}")
    logger.debug(f"Token usage: {token_usage}")

    conversation.append(
        ChatCompletionAssistantMessageParam(
            content=full_content,
            role="assistant",
            reasoning_content=full_reasoning_content,
        )
    )

    return conversation


async def _query_llm_with_retry(
    messages: list[ChatCompletionMessageParam],
    retry_times: int,
    validate_func: Callable[[str], bool],
):
    logger.info(f"Query LLM with retry {retry_times} times")

    for times in range(retry_times):
        logger.info(f"Retry {times + 1} / {retry_times}")
        conversation = await _query_llm(messages)
        content = conversation[-1]["content"]

        if validate_func(content):
            logger.info("Get valid response from LLM")
            return conversation

        logger.error("Get unexpected response from LLM")

    raise UnExpectedResponseException("Invalid response from LLM")


def _save_conversation(
    conversation: list[ChatCompletionMessageParam], report_name: str, name: str
):
    dir = config.result_report_filter_dir(report_name) / "conversation"
    dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Saving conversation to {dir}")

    with open(dir / f"{name}.json", "w") as f:
        json.dump(conversation, f, indent=4)
    with open(dir / f"{name}.md", "w") as f:
        for message in conversation:
            f.write(f"## {message['role']}\n")
            f.write("Content:\n")
            f.write(f"````text\n{message['content']}\n````\n")
            if "reasoning_content" in message:
                f.write("Reasoning_content:\n")
                f.write(f"````text\n{message['reasoning_content']}\n````\n")


def _save_retained_candidates(candidates: list[Candidate], dir: Path):
    logger.info(f"Saving retained candidates to {dir}")

    dir.mkdir(parents=True, exist_ok=True)
    with open(dir / "retained_candidates.json", "w") as f:
        json.dump(
            [candidate.model_dump() for candidate in candidates],
            f,
            indent=4,
        )


async def _query_base_candidates(
    report_info: ReportInfo,
) -> tuple[list[Candidate], list[ChatCompletionMessageParam]]:
    logger.info(f"Starting base candidate query for {report_info.apk_name}")

    messages = [
        ChatCompletionSystemMessageParam(
            content=Prompt.FILTER_CANDIDATE_SYSTEM, role="system"
        ),
        ChatCompletionUserMessageParam(
            content=Prompt.FILTER_CANDIDATE_CRASH(report_info),
            role="user",
        ),
    ]

    retained_candidates = []
    for index, candidate in enumerate(report_info.base_candidates):
        logger.info(
            f"Querying base candidate {index + 1} / {len(report_info.base_candidates)}"
        )
        logger.info(f"Candidate: {candidate.name}")

        messages.append(
            ChatCompletionUserMessageParam(
                content=Prompt.FILTER_CANDIDATE_METHOD(report_info, candidate),
                role="user",
            )
        )
        messages = await _query_llm_with_retry(
            messages,
            3,
            lambda x: ("Yes" in x and "No" not in x) or ("No" in x and "Yes" not in x),
        )

        if "Yes" in messages[-1]["content"]:
            retained_candidates.append(candidate)

    _save_conversation(messages, report_info.apk_name, "base_candidates")
    return retained_candidates, messages


async def _query_extra_candidates(
    report_info: ReportInfo,
    retained_candidates: list[Candidate],
    base_messages: list[ChatCompletionMessageParam],
) -> list[Candidate]:
    logger.info(f"Starting extra candidate query for {report_info.apk_name}")

    for index, candidate in enumerate(report_info.extra_candidates):
        logger.info(
            f"Querying extra candidate {index + 1} / {len(report_info.extra_candidates)}"
        )
        logger.info(f"Candidate: {candidate.name}")
        messages = base_messages.copy()
        messages.append(
            ChatCompletionUserMessageParam(
                content=Prompt.FILTER_CANDIDATE_METHOD(report_info, candidate),
                role="user",
            )
        )
        messages = await _query_llm_with_retry(
            messages,
            3,
            lambda x: ("Yes" in x and "No" not in x) or ("No" in x and "Yes" not in x),
        )
        if "Yes" in messages[-1]["content"]:
            retained_candidates.append(candidate)
        _save_conversation(
            messages, report_info.apk_name, f"extra_candidates_{index + 1}"
        )

    return retained_candidates


async def query_filter_candidate(report_info: ReportInfo) -> list[Candidate]:
    logger.info(f"Starting candidate filtering for {report_info.apk_name}")

    retained_candidates, base_messages = await _query_base_candidates(report_info)
    retained_candidates = await _query_extra_candidates(
        report_info, retained_candidates, base_messages
    )

    _save_retained_candidates(
        retained_candidates,
        config.result_report_filter_dir(report_info.apk_name),
    )
    logger.info(
        f"Candidate filtering completed, before: {len(report_info.candidates)}, after: {len(retained_candidates)}"
    )
    return retained_candidates
