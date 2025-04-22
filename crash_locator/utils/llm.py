from openai import OpenAI
from crash_locator.config import Config, get_thread_logger
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
import logging
from typing import Callable
import json
from pathlib import Path
from copy import deepcopy

logger = logging.getLogger(__name__)

client = OpenAI(base_url=Config.OPENAI_BASE_URL, api_key=Config.OPENAI_API_KEY)


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


def _query_llm(messages: list[ChatCompletionMessageParam]):
    thread_logger = get_thread_logger()
    conversation = _purge_conversation(messages)
    thread_logger.info("Preparing to query LLM")
    thread_logger.debug(f"Messages: {conversation}")

    response = client.chat.completions.create(
        model=Config.OPENAI_MODEL,
        messages=conversation,
        timeout=240,
        stream=True,
    )

    collected_chunks: list[ChatCompletionChunk] = []
    collected_content: list[str | None] = []
    collected_reasoning_content: list[str | None] = []

    for chunk in response:
        thread_logger.debug(f"Received chunk: {chunk}")
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
    thread_logger.info("LLM query completed")
    thread_logger.debug(f"Full content: {full_content}")
    thread_logger.debug(f"Full reasoning content: {full_reasoning_content}")
    thread_logger.debug(f"Token usage: {token_usage}")

    conversation.append(
        ChatCompletionAssistantMessageParam(
            content=full_content,
            role="assistant",
            reasoning_content=full_reasoning_content,
        )
    )

    return conversation


def _query_llm_with_retry(
    messages: list[ChatCompletionMessageParam],
    retry_times: int,
    validate_func: Callable[[str], bool],
):
    thread_logger = get_thread_logger()
    thread_logger.info(f"Query LLM with retry {retry_times} times")

    for times in range(retry_times):
        thread_logger.info(f"Retry {times + 1} / {retry_times}")
        conversation = _query_llm(messages)
        content = conversation[-1]["content"]

        if validate_func(content):
            thread_logger.info("Get valid response from LLM")
            return conversation

        thread_logger.error("Get unexpected response from LLM")

    raise UnExpectedResponseException("Invalid response from LLM")


def _save_conversation(conversation: list[ChatCompletionMessageParam], dir: Path):
    thread_logger = get_thread_logger()
    dir.mkdir(parents=True, exist_ok=True)
    thread_logger.info(f"Saving conversation to {dir}")

    with open(dir / "conversation.json", "w") as f:
        json.dump(conversation, f)
    with open(dir / "conversation.md", "w") as f:
        for message in conversation:
            f.write(f"## {message['role']}\n")
            f.write("Content:\n")
            f.write(f"````text\n{message['content']}\n````\n")
            if "reasoning_content" in message:
                f.write("Reasoning_content:\n")
                f.write(f"````text\n{message['reasoning_content']}\n````\n")


def _save_retained_candidates(candidates: list[Candidate], dir: Path):
    thread_logger = get_thread_logger()
    thread_logger.info(f"Saving retained candidates to {dir}")

    dir.mkdir(parents=True, exist_ok=True)
    with open(dir / "retained_candidates.json", "w") as f:
        json.dump(
            [candidate.model_dump() for candidate in candidates],
            f,
            indent=4,
        )


def query_filter_candidate(report_info: ReportInfo) -> list[Candidate]:
    thread_logger = get_thread_logger()
    thread_logger.info(f"Starting candidate filtering for {report_info.apk_name}")

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
    for index, candidate in enumerate(report_info.sorted_candidates):
        thread_logger.info(
            f"Filtering candidate {index + 1} / {len(report_info.sorted_candidates)}"
        )
        thread_logger.info(f"Candidate: {candidate.name}")

        messages.append(
            ChatCompletionUserMessageParam(
                content=Prompt.FILTER_CANDIDATE_METHOD(report_info, candidate),
                role="user",
            )
        )
        # TODO: only add the necessary candidate to the context
        messages = _query_llm_with_retry(
            messages,
            3,
            lambda x: ("Yes" in x and "No" not in x) or ("No" in x and "Yes" not in x),
        )
        if "Yes" in messages[-1]["content"]:
            retained_candidates.append(candidate)

    _save_conversation(messages, Config.RESULT_REPORT_FILTER_DIR(report_info.apk_name))
    _save_retained_candidates(
        retained_candidates,
        Config.RESULT_REPORT_FILTER_DIR(report_info.apk_name),
    )
    thread_logger.info(
        f"Candidate filtering completed, before: {len(report_info.candidates)}, after: {len(retained_candidates)}"
    )
    return retained_candidates
