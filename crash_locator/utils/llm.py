from openai import AsyncOpenAI
from openai import RateLimitError, InternalServerError, APIConnectionError
from crash_locator.config import config, run_statistic
from crash_locator.my_types import ReportInfo, Candidate, MethodSignature
from crash_locator.prompt import Prompt
from crash_locator.exceptions import UnExpectedResponseException
from crash_locator.utils.java_parser import get_framework_code
from crash_locator.types.llm import (
    Conversation,
    Message,
    Role,
    APIType,
    Response,
    TokenUsage,
)
from typing import Callable
import json
from pathlib import Path
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
    before_log,
    after_log,
)
import logging
import re

logger = logging.getLogger(__name__)

client = AsyncOpenAI(base_url=config.openai_base_url, api_key=config.openai_api_key)


async def _query_response_api(conversation: Conversation) -> Response:
    from openai.types.responses.response_input_param import ResponseInputParam

    input: ResponseInputParam = conversation.dump_messages()
    response = await client.responses.create(
        model=config.openai_model,
        input=input,
        timeout=240,
        stream=False,
        reasoning={
            "effort": "medium",
        },
    )

    content = response.output_text
    token_usage = TokenUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return Response(content=content, token_usage=token_usage)


async def _query_completion_api(conversation: Conversation) -> Response:
    from openai.types.chat import ChatCompletionMessageParam

    messages: list[ChatCompletionMessageParam] = conversation.dump_messages()
    response = await client.chat.completions.create(
        model=config.openai_model,
        messages=messages,
        timeout=240,
        stream=False,
    )

    content = response.choices[0].message.content
    reasoning_content = None

    # Check if reasoning content is in model_extra
    if "reasoning_content" in response.choices[0].message.model_extra:
        reasoning_content = response.choices[0].message.model_extra["reasoning_content"]

    # Check if reasoning content is wrapped in <think> tags within content
    if reasoning_content is None and content:
        think_pattern = r"<think>(.*?)</think>"
        think_matches = re.findall(think_pattern, content, re.DOTALL)
        if think_matches:
            # Extract the reasoning content from think tags
            reasoning_content = "\n".join(think_matches)
            # Remove think tags from the main content
            content = re.sub(think_pattern, "", content, flags=re.DOTALL).strip()

    token_usage = TokenUsage(
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )
    return Response(
        content=content,
        token_usage=token_usage,
        reasoning_content=reasoning_content,
    )


@retry(
    wait=wait_random_exponential(min=1, max=60),
    stop=stop_after_attempt(6),
    retry=retry_if_exception_type(
        (RateLimitError, InternalServerError, APIConnectionError)
    ),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.INFO),
    reraise=True,
)
async def _query_llm(conversation: Conversation) -> Conversation:
    logger.info("Preparing to query LLM")
    logger.debug(f"Messages: {conversation}")

    conversation = conversation.messages_copy()
    match config.openai_api_type:
        case APIType.RESPONSE:
            logger.info("Using response API")
            response = await _query_response_api(conversation)
        case APIType.COMPLETION:
            logger.info("Using completion API")
            response = await _query_completion_api(conversation)
        case _:
            raise ValueError(f"Invalid API type: {config.openai_api_type}")

    content = response.content
    token_usage = response.token_usage
    reasoning_content = response.reasoning_content
    run_statistic.add_token_usage(token_usage)
    logger.info("LLM query completed")
    logger.debug(f"Content: {content}")
    logger.debug(f"Token usage: {token_usage}")

    conversation.append(
        Message(
            content=content,
            role=Role.ASSISTANT,
            reasoning_content=reasoning_content,
        )
    )

    return conversation


async def _query_llm_with_retry(
    conversation: Conversation,
    retry_times: int,
    validate_func: Callable[[str], bool],
):
    logger.info(f"Query LLM with retry {retry_times} times")

    for times in range(retry_times):
        logger.info(f"Retry {times + 1} / {retry_times}")
        new_conversation = await _query_llm(conversation)
        content = new_conversation.messages[-1].content

        if validate_func(content):
            logger.info("Get valid response from LLM")
            return new_conversation

        logger.error(f"Get unexpected response from LLM: {content}")

    raise UnExpectedResponseException("Invalid response from LLM")


def _save_conversation(conversation: Conversation, base_dir: Path, name: str):
    dir = base_dir / "conversation"
    dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Saving conversation to {dir}")

    with open(dir / f"{name}.json", "w") as f:
        json.dump(conversation.model_dump(), f, indent=4)
    with open(dir / f"{name}.md", "w") as f:
        for message in conversation.messages:
            f.write(f"## {message.role}\n")
            f.write("Content:\n")
            f.write(f"````text\n{message.content}\n````\n")
            if message.reasoning_content:
                f.write("Reasoning_content:\n")
                f.write(f"````text\n{message.reasoning_content}\n````\n")


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
) -> tuple[list[Candidate], Conversation]:
    logger.info(f"Starting base candidate query for {report_info.apk_name}")

    conversation = Prompt.base_filter_candidate_prompt(report_info, constraint)

    retained_candidates = []
    for index, candidate in enumerate(report_info.base_candidates):
        logger.info(
            f"Querying base candidate {index + 1} / {len(report_info.base_candidates)}"
        )
        logger.info(f"Candidate: {candidate.name}")

        conversation.append(
            Message(
                content=Prompt.FILTER_CANDIDATE_METHOD(report_info, candidate),
                role=Role.USER,
            )
        )
        conversation = await _query_llm_with_retry(
            conversation,
            3,
            lambda x: ("Yes" in x and "No" not in x) or ("No" in x and "Yes" not in x),
        )

        if "Yes" in conversation.messages[-1].content:
            retained_candidates.append(candidate)

    _save_conversation(
        conversation,
        config.result_report_filter_dir(report_info.apk_name),
        "base_candidates",
    )
    return retained_candidates, conversation


async def _query_extra_candidates(
    report_info: ReportInfo,
    retained_candidates: list[Candidate],
    base_messages: Conversation,
) -> list[Candidate]:
    logger.info(f"Starting extra candidate query for {report_info.apk_name}")

    for index, candidate in enumerate(report_info.extra_candidates):
        logger.info(
            f"Querying extra candidate {index + 1} / {len(report_info.extra_candidates)}"
        )
        logger.info(f"Candidate: {candidate.name}")
        conversation = base_messages.messages_copy()
        conversation.append(
            Message(
                content=Prompt.FILTER_CANDIDATE_METHOD(report_info, candidate),
                role=Role.USER,
            )
        )
        conversation = await _query_llm_with_retry(
            conversation,
            3,
            lambda x: ("Yes" in x and "No" not in x) or ("No" in x and "Yes" not in x),
        )
        if "Yes" in conversation.messages[-1].content:
            retained_candidates.append(candidate)
        _save_conversation(
            conversation,
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
    conversation = Prompt.base_extractor_prompt()
    conversation.append(
        Message(
            content=Prompt.EXTRACTOR_USER_PROMPT(
                code,
                method.full_class_name(),
                report_info.exception_type,
                report_info.crash_message,
            ),
            role=Role.USER,
        )
    )

    conversation = await _query_llm_with_retry(
        conversation,
        3,
        lambda x: _constraint_parser(x) is not None,
    )
    _save_conversation(
        conversation,
        config.result_report_constraint_dir(report_info.apk_name),
        "extract_constraint",
    )
    return _constraint_parser(conversation[-1].content)


async def _infer_constraint(
    method: MethodSignature,
    conversation: Conversation,
    original_constraint: str,
    report_info: ReportInfo,
) -> str:
    code = get_framework_code(method, report_info.android_version)
    conversation.append(
        Message(
            content=Prompt.INFERRER_USER_PROMPT(
                code,
                method.full_class_name(),
                original_constraint,
            ),
            role=Role.USER,
        )
    )

    conversation = await _query_llm_with_retry(
        conversation, 3, lambda x: _constraint_parser(x) is not None
    )
    _save_conversation(
        conversation,
        config.result_report_constraint_dir(report_info.apk_name),
        "infer_constraint",
    )
    return _constraint_parser(conversation.messages[-1].content)


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
