from openai import AsyncOpenAI
from crash_locator.config import config
from openai import RateLimitError, InternalServerError, APIConnectionError
from crash_locator.my_types import ReportInfo, Candidate, RunStatistic, MethodSignature
from crash_locator.prompt import Prompt
from crash_locator.exceptions import UnExpectedResponseException
from openai.types.chat.chat_completion_message_param import (
    ChatCompletionMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
)
from crash_locator.config import run_statistic
from crash_locator.utils.java_parser import get_framework_code
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

    response = await client.chat.completions.create(
        model=config.openai_model,
        messages=conversation,
        timeout=240,
        stream=False,
        reasoning_effort="medium",
    )

    full_content = response.choices[0].message.content
    token_usage = RunStatistic.TokenUsage(
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )
    run_statistic.add_token_usage(token_usage)
    logger.info("LLM query completed")
    logger.debug(f"Full content: {full_content}")
    logger.debug(f"Token usage: {token_usage}")

    messages.append(
        ChatCompletionAssistantMessageParam(
            content=full_content,
            role="assistant",
        )
    )

    return messages


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

        logger.error(f"Get unexpected response from LLM: {content}")

    raise UnExpectedResponseException("Invalid response from LLM")


def _save_conversation(
    conversation: list[ChatCompletionMessageParam], base_dir: Path, name: str
):
    dir = base_dir / "conversation"
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
    constraint: str | None = None,
) -> tuple[list[Candidate], list[ChatCompletionMessageParam]]:
    logger.info(f"Starting base candidate query for {report_info.apk_name}")

    messages = Prompt.base_filter_candidate_prompt(report_info, constraint)

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

    _save_conversation(
        messages,
        config.result_report_filter_dir(report_info.apk_name),
        "base_candidates",
    )
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
            messages,
            config.result_report_filter_dir(report_info.apk_name),
            f"extra_candidates_{index + 1}",
        )

    return retained_candidates


async def query_filter_candidate(
    report_info: ReportInfo, constraint: str | None = None
) -> list[Candidate]:
    logger.info(f"Starting candidate filtering for {report_info.apk_name}")

    retained_candidates, base_messages = await _query_base_candidates(
        report_info, constraint
    )
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


def _constraint_parser(message: str) -> str | None:
    import re

    pattern = r"Constraint:\s?```\s?(.*?)\s?```"
    matches = re.findall(pattern, message, re.DOTALL)

    if len(matches) == 0:
        return None

    return matches[0].strip()


async def _extract_constraint(
    method: MethodSignature,
    report_info: ReportInfo,
) -> str:
    code = get_framework_code(method, report_info.android_version)
    messages = Prompt.base_extractor_prompt()
    messages.append(
        ChatCompletionUserMessageParam(
            content=Prompt.EXTRACTOR_USER_PROMPT(
                code,
                method.full_class_name(),
                report_info.exception_type,
                report_info.crash_message,
            ),
            role="user",
        )
    )

    conversation = await _query_llm_with_retry(
        messages,
        3,
        lambda x: _constraint_parser(x) is not None,
    )
    _save_conversation(
        conversation,
        config.result_report_constraint_dir(report_info.apk_name),
        "extract_constraint",
    )
    return _constraint_parser(conversation[-1]["content"])


async def _infer_constraint(
    method: MethodSignature,
    messages: list[ChatCompletionMessageParam],
    original_constraint: str,
    report_info: ReportInfo,
) -> str:
    code = get_framework_code(method, report_info.android_version)
    messages.append(
        ChatCompletionUserMessageParam(
            content=Prompt.INFERRER_USER_PROMPT(
                code,
                method.full_class_name(),
                original_constraint,
            ),
            role="user",
        )
    )

    conversation = await _query_llm_with_retry(
        messages, 3, lambda x: _constraint_parser(x) is not None
    )
    _save_conversation(
        conversation,
        config.result_report_constraint_dir(report_info.apk_name),
        "infer_constraint",
    )
    return _constraint_parser(conversation[-1]["content"])


async def query_filter_candidate_with_constraint(
    report_info: ReportInfo,
) -> list[Candidate]:
    logger.info(f"Starting candidate filtering for {report_info.apk_name}")

    inference_messages = Prompt.base_inferrer_prompt()
    for index, framework_method in enumerate(report_info.framework_trace):
        logger.info(f"Inferring constraint for {framework_method}")
        logger.info(
            f"Inferring process: {index + 1} / {len(report_info.framework_trace)}"
        )

        if index == 0:
            logger.info(f"Extracting constraint for {framework_method}")
            constraint = await _extract_constraint(framework_method, report_info)
        else:
            constraint = await _infer_constraint(
                framework_method, inference_messages, constraint, report_info
            )

    logger.info(f"Constraint is extracted: {constraint}")
    with open(
        config.result_report_constraint_dir(report_info.apk_name) / "constraint.txt",
        "w",
    ) as f:
        f.write(constraint)

    return await query_filter_candidate(report_info, constraint)
