from openai import AsyncOpenAI
from openai import RateLimitError, InternalServerError, APIConnectionError
from openai._types import NOT_GIVEN
from crash_locator.config import config, run_statistic
from crash_locator.my_types import (
    ReportInfo,
    Candidate,
    MethodSignature,
    ClassSignature,
    ReasonTypeLiteral,
    ManualSupplementReason,
)
from crash_locator.prompt import Prompt
from crash_locator.exceptions import (
    CodeRetrievalException,
    UnExpectedResponseException,
    UnknownException,
    InvalidSignatureException,
)
from crash_locator.my_types import PackageType
from crash_locator.utils.helper import get_method_type
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
from openai.types.chat import ChatCompletionToolParam
from textwrap import dedent

logger = logging.getLogger(__name__)

client = AsyncOpenAI(base_url=config.openai_base_url, api_key=config.openai_api_key)


tools: list[ChatCompletionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_candidate",
            "description": "After you fully understand the crash and the candidate, you should evaluate whether the candidate is related to the crash. If it is related, pass is_crash_related parameter as true, otherwise pass false. In the meantime, you should provide a detailed reason about why you think the candidate is related to the crash or not.",
            "parameters": {
                "type": "object",
                "properties": {
                    "is_crash_related": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["is_crash_related"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_buggy_method_candidate",
            "description": "When you found a buggy method which is related to the crash, you should add it to the list of candidates by calling this tool. The method signature should be include class name, return type, method name and parameters in the format of `android.view.ViewRoot: void checkThread()`. In the meantime, you should provide a detailed reason about why you think the method is buggy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method_signature": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["method_signature", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_investigation",
            "description": "When you evaluate all candidates and add all buggy method which is not in candidates to the list of candidates, you should call this tool to finish the investigation.",
            "parameters": {},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_application_code",
            "description": "Pass a application method signature to get the code snippet of the method. The signature could be in two formats: 1. android.view.ViewRoot: void checkThread() 2. android.view.ViewRoot.checkThread. The format 1 is the full signature, and the format 2 is the short signature. the short signature may return multiple methods.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method_signature": {"type": "string"},
                },
                "required": ["method_signature"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_application_methods",
            "description": "Pass a application class signature to list all methods in the class. The signature example: android.view.ViewRoot",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_signature": {"type": "string"},
                },
                "required": ["class_signature"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_application_fields",
            "description": "Pass a application class signature to list all fields in the class. The signature example: android.view.ViewRoot",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_signature": {"type": "string"},
                },
                "required": ["class_signature"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_application_field",
            "description": "Pass a application class signature and field name to get the code snippet of the field. The signature example: android.view.ViewRoot",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_signature": {"type": "string"},
                    "field_name": {"type": "string"},
                },
            },
            "required": ["class_signature", "field_name"],
            "additionalProperties": False,
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_application_manifest",
            "description": "Get the android manifest for the application.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
            "required": [],
            "additionalProperties": False,
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_application_strings",
            "description": "Get the strings.xml file for the application.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
            "required": [],
            "additionalProperties": False,
            "strict": True,
        },
    },
]


async def _query_response_api(conversation: Conversation) -> Response:
    from openai.types.responses.response_input_param import ResponseInputParam

    input: ResponseInputParam = conversation.dump_messages()
    response = await client.responses.create(
        model=config.openai_model,
        input=input,
        timeout=240,
        stream=False,
    )
    logger.debug(f"Raw response: {response}")

    content = response.output_text
    token_usage = TokenUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return Response(content=content, token_usage=token_usage)


async def _query_completion_api(
    conversation: Conversation,
    tools: list[ChatCompletionToolParam] | None = None,
) -> Response:
    from openai.types.chat import ChatCompletionMessageParam

    messages: list[ChatCompletionMessageParam] = conversation.dump_messages()
    response = await client.chat.completions.create(
        model=config.openai_model,
        messages=messages,
        timeout=240,
        stream=False,
        reasoning_effort=config.reasoning_effort.value
        if config.reasoning_effort is not None
        else NOT_GIVEN,
        tools=tools if tools is not None else NOT_GIVEN,
    )
    logger.debug(f"Raw response: {response}")

    content = response.choices[0].message.content
    tool_calls = response.choices[0].message.tool_calls
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
        tool_calls=[tool_call.model_dump() for tool_call in tool_calls]
        if tool_calls is not None
        else None,
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
async def _query_llm(
    conversation: Conversation,
    tools: list[ChatCompletionToolParam] | None = None,
) -> Conversation:
    logger.info("Preparing to query LLM")
    logger.debug(f"Messages: {conversation}")

    conversation = conversation.messages_copy()
    match config.openai_api_type:
        case APIType.RESPONSE:
            logger.info("Using response API")
            response = await _query_response_api(conversation)
        case APIType.COMPLETION:
            logger.info("Using completion API")
            response = await _query_completion_api(conversation, tools)
        case _:
            raise ValueError(f"Invalid API type: {config.openai_api_type}")

    content = response.content
    tool_calls = response.tool_calls
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
            tool_calls=tool_calls,
        )
    )

    return conversation


async def _query_llm_with_retry(
    conversation: Conversation,
    retry_times: int,
    validate_func: Callable[[str], bool],
):
    logger.info(f"Query LLM with retry {retry_times} times")

    first_times = True
    for times in range(retry_times + 1):
        if not first_times:
            logger.info(f"Retry {times} / {retry_times}")
        else:
            first_times = False

        new_conversation = await _query_llm(conversation, tools)
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
            if message.tool_calls:
                f.write("Tool calls:\n")
                for tool_call in message.tool_calls:
                    f.write("```\n")
                    f.write(f"Tool call id: {tool_call['id']}\n")
                    f.write(f"Tool call name: {tool_call['function']['name']}\n")
                    f.write(f"Tool call args: {tool_call['function']['arguments']}\n")
                    f.write("```\n")


def _save_retained_candidates(candidates: list[Candidate], dir: Path):
    logger.info(f"Saving retained candidates to {dir}")

    dir.mkdir(parents=True, exist_ok=True)
    with open(dir / "retained_candidates.json", "w") as f:
        json.dump(
            [candidate.model_dump() for candidate in candidates],
            f,
            indent=4,
        )


def _evaluate_candidate_function_factory(
    retained_candidates: list[Candidate],
    candidate: Candidate | None,
) -> Callable[[bool, str], str]:
    def evaluate_candidate(is_crash_related: bool, reason: str) -> str:
        if candidate is None:
            return "You have no candidate to evaluate"

        if is_crash_related:
            retained_candidates.append(candidate)
        return dedent(
            f"""\
            Candidate method {candidate.name} is evaluated as {is_crash_related}
            Reason: {reason}
            """
        ).strip()

    return evaluate_candidate


def _add_buggy_method_candidate_function_factory(
    retained_candidates: list[Candidate],
) -> Callable[[str], str]:
    def add_buggy_method_candidate(method_signature: str, reason: str) -> str:
        signature = MethodSignature.from_str(method_signature)

        for candidate in retained_candidates:
            if candidate.signature == signature:
                return f"Buggy method {method_signature} is already in the list of candidates, do not add it again"

        match get_method_type(method_signature):
            case PackageType.ANDROID | PackageType.ANDROID_SUPPORT:
                return (
                    "Android framework method is not allowed to be added as a candidate"
                )
            case PackageType.JAVA:
                return "Java framework method is not allowed to be added as a candidate"
            case _:
                pass

        retained_candidates.append(
            Candidate(
                name=signature.into_basic_name(),
                signature=signature,
                extend_hierarchy=[],
                reasons=(
                    ManualSupplementReason(
                        reason_type=ReasonTypeLiteral.MANUAL_SUPPLEMENT,
                        reason=reason,
                    )
                ),
            )
        )
        return f"Buggy method {method_signature} is added to the list of candidates"

    return add_buggy_method_candidate


def _finish_investigation_function_factory(
    candidate: Candidate | None,
) -> Callable[[str], str]:
    def finish_investigation() -> str:
        if candidate is None:
            return "You have finished the investigation"
        else:
            return f"You cannot finish the investigation because you have not evaluated all the candidates yet. Please evaluate the candidate {candidate.name} first."

    return finish_investigation


def _call_tool_factory(
    apk_name: str,
    retained_candidates: list[Candidate],
    candidate: Candidate | None = None,
) -> Callable[[str, dict[str, str]], str]:
    _evaluate_candidate = _evaluate_candidate_function_factory(
        retained_candidates, candidate
    )
    _add_buggy_method_candidate = _add_buggy_method_candidate_function_factory(
        retained_candidates
    )
    _finish_investigation = _finish_investigation_function_factory(candidate)
    from crash_locator.utils.java_parser import (
        get_application_code,
        list_application_methods,
        list_application_fields,
        get_application_field,
        get_application_manifest,
        get_application_strings,
    )

    def call_tool(tool_name: str, tool_args: dict) -> str:
        try:
            match tool_name:
                case "evaluate_candidate":
                    return _evaluate_candidate(
                        bool(tool_args["is_crash_related"]), tool_args["reason"]
                    )
                case "add_buggy_method_candidate":
                    return _add_buggy_method_candidate(
                        tool_args["method_signature"], tool_args["reason"]
                    )
                case "finish_investigation":
                    return _finish_investigation()
                case "get_application_code":
                    code = get_application_code(
                        apk_name,
                        MethodSignature.from_str(tool_args["method_signature"]),
                    )
                    return f"Code snippet of method {tool_args['method_signature']}:\n{code}"
                case "list_application_methods":
                    methods = list_application_methods(
                        apk_name, ClassSignature.from_str(tool_args["class_signature"])
                    )
                    formatted_methods = "\n".join(
                        f"{i}. {method}" for i, method in enumerate(methods, 1)
                    )
                    return f"Methods in class {tool_args['class_signature']}:\n{formatted_methods}"
                case "list_application_fields":
                    fields = list_application_fields(
                        apk_name, ClassSignature.from_str(tool_args["class_signature"])
                    )
                    formatted_fields = "\n".join(
                        f"{i}. {field}" for i, field in enumerate(fields, 1)
                    )
                    return f"Fields in class {tool_args['class_signature']}:\n{formatted_fields}"
                case "get_application_field":
                    field = get_application_field(
                        apk_name,
                        ClassSignature.from_str(tool_args["class_signature"]),
                        tool_args["field_name"],
                    )
                    return f"Code snippet of field {tool_args['field_name']}:\n{field}"
                case "get_application_manifest":
                    manifest = get_application_manifest(apk_name)
                    return f"Android manifest:\n{manifest}"
                case "get_application_strings":
                    strings = get_application_strings(apk_name)
                    return f"Application strings:\n{strings}"
                case _:
                    raise UnknownException(f"Unknown tool: {tool_name}")
        except (CodeRetrievalException, InvalidSignatureException) as e:
            return f"Error when calling tool {tool_name}: {e}"

    return call_tool


async def _query_llm_with_tool_process(
    conversation: Conversation,
    tool_func: Callable[[str, dict], str],
    end_tool_call_name: str,
) -> Conversation:
    is_end = False
    while not is_end:
        conversation = await _query_llm(conversation, tools)
        if conversation[-1].tool_calls is not None:
            for tool_call in conversation[-1].tool_calls:
                tool_name = tool_call["function"]["name"]
                if tool_name == end_tool_call_name:
                    is_end = True

                tool_args = json.loads(tool_call["function"]["arguments"])
                logger.info(f"Tool call: {tool_name} with args: {tool_args}")

                tool_call_id = tool_call["id"]
                tool_result = tool_func(tool_name, tool_args)
                logger.info("Got tool result")
                logger.debug(f"Tool result: {tool_result}")
                conversation.append(
                    Message(
                        content=tool_result, role=Role.TOOL, tool_call_id=tool_call_id
                    )
                )
    return conversation


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
        conversation = await _query_llm_with_tool_process(
            conversation,
            _call_tool_factory(report_info.apk_name, retained_candidates, candidate),
            "evaluate_candidate",
        )

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
        conversation = await _query_llm_with_tool_process(
            conversation,
            _call_tool_factory(report_info.apk_name, retained_candidates, candidate),
            "evaluate_candidate",
        )

        _save_conversation(
            conversation,
            config.result_report_filter_dir(report_info.apk_name),
            f"extra_candidates_{index + 1}",
        )

    return retained_candidates


async def _query_final_review(
    report_info: ReportInfo,
    retained_candidates: list[Candidate],
    base_messages: Conversation,
) -> list[Candidate]:
    logger.info(f"Starting final review for {report_info.apk_name}")

    conversation = base_messages.messages_copy()

    conversation.append(
        Message(
            content=Prompt.FINAL_REVIEW_USER_PROMPT(report_info, retained_candidates),
            role=Role.USER,
        )
    )
    conversation = await _query_llm_with_tool_process(
        conversation,
        _call_tool_factory(report_info.apk_name, retained_candidates),
        "finish_investigation",
    )

    _save_conversation(
        conversation,
        config.result_report_filter_dir(report_info.apk_name),
        "final_review",
    )
    return retained_candidates


async def _llm_filter_candidate(
    report_info: ReportInfo, constraint: str | None = None
) -> list[Candidate]:
    logger.info(f"Starting llm candidate filtering for {report_info.apk_name}")

    retained_candidates, base_messages = await _query_base_candidates(
        report_info, constraint
    )
    retained_candidates = await _query_extra_candidates(
        report_info, retained_candidates, base_messages
    )
    retained_candidates = await _query_final_review(
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


async def _construct_constraint(report_info: ReportInfo) -> str:
    inference_messages = Prompt.base_inferrer_prompt()
    for index, framework_method in enumerate(report_info.framework_trace):
        logger.info(f"construct constraint for {framework_method}")
        logger.info(
            f"Constraint construction process: {index + 1} / {len(report_info.framework_trace)}"
        )

        if index == 0:
            logger.info(f"Extracting constraint for {framework_method}")
            constraint = await _extract_constraint(framework_method, report_info)
        else:
            logger.info(f"Inferring constraint for {framework_method}")
            constraint = await _infer_constraint(
                framework_method, inference_messages, constraint, report_info
            )

    logger.info(f"Constraint is extracted: {constraint}")
    with open(
        config.result_report_constraint_dir(report_info.apk_name) / "constraint.txt",
        "w",
    ) as f:
        f.write(constraint)

    return constraint


async def filter_candidate(report_info: ReportInfo) -> list[Candidate]:
    logger.info(f"Starting candidate filtering for {report_info.apk_name}")

    constraint = None
    if config.enable_extract_constraint:
        constraint = await _construct_constraint(report_info)
    return await _llm_filter_candidate(report_info, constraint)
