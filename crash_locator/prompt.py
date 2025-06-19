from crash_locator.my_types import ReportInfo, Candidate
from crash_locator.utils.java_parser import get_application_code
from crash_locator.my_types import ReasonTypeLiteral
from crash_locator.types.llm import Conversation, Message, Role
from textwrap import dedent
from crash_locator.config import config
from string import Template


class Prompt:
    class Part:
        @staticmethod
        def merger(parts: list[str] | list[str | None]) -> str:
            return "\n\n".join([s for s in parts if s is not None])

        @staticmethod
        def candidate_method(candidate: Candidate) -> str:
            return f"Candidate Method: {candidate.signature}"

        @staticmethod
        def method_code(code: str, class_name: str) -> str:
            normalized_code = dedent(code).strip()
            template = Template(
                dedent(
                    """\
                    Code:
                    ```
                    Class Name: $class_name

                    $code
                    ```
                    """
                ).strip()
            )
            return template.substitute(code=normalized_code, class_name=class_name)

        @staticmethod
        def candidate_reason(candidate: Candidate) -> str:
            template = Template(
                dedent("""\
                Candidate Reason:
                ```
                $reason
                ```
                """).strip()
            )
            return template.substitute(reason=candidate.reasons.reason_explanation())

    @staticmethod
    def _FILTER_CANDIDATE_SYSTEM(constraint: str | None = None) -> str:
        constraint_prompt = (
            "Additionally, we also provide a constraint which is met when the exception is triggered."
            if constraint
            else None
        )
        notes_prompt = (
            "// Note: You need to be aware that errors may be related to multiple aspects, such as for the 'service is null' error, it could be due to the creation method not successfully creating it, or it might have been modified by other methods leading to premature release."
            if config.enable_notes
            else None
        )

        response_prompt = (
            "For those candidate methods that likely to be related to the crash, you just reply 'Yes.'(Usually the numbers 'Yes' is less than 3) at the beginning, otherwise you reply 'No.', followed by a concise reason explanation of no more than two sentences after the period."
            if config.enable_notes
            else "For those candidate methods that are most likely to be related to the crash, you just reply 'Yes', otherwise you reply 'No' without any additional text."
        )

        prompts = [
            "You are an Android expert that assist with locating the cause of the crash of Android application.",
            "You will be given a crash report first, then you need to analyze the crash report and the cause of the crash.",
            constraint_prompt,
            notes_prompt,
            response_prompt,
        ]

        return Prompt.Part.merger(prompts)

    @staticmethod
    def _FILTER_CANDIDATE_CRASH(
        report_info: ReportInfo, constraint: str | None = None
    ) -> str:
        constraint_template = Template(
            dedent("""\
                Constraint:
                ```
                $constraint
                ```
            """).strip()
        )

        constraint_part = (
            constraint_template.substitute(constraint=constraint)
            if constraint
            else None
        )

        crash_template = Template(
            dedent("""\
                Crash Message:
                ```
                $crash_message
                ```

                Stack Trace:
                ```
                $stack_trace
                ```

                Exception Type:
                ```
                $exception_type
                ```

                Android Version:
                ```
                $android_version
                ```
            """).strip()
        )

        crash_part = crash_template.substitute(
            crash_message=report_info.crash_message,
            stack_trace="\n".join(report_info.stack_trace),
            exception_type=report_info.exception_type,
            android_version=report_info.android_version,
        )

        return Prompt.Part.merger([crash_part, constraint_part])

    @staticmethod
    def base_filter_candidate_prompt(
        report_info: ReportInfo,
        constraint: str | None = None,
    ) -> Conversation:
        return Conversation(
            messages=[
                Message(
                    content=Prompt._FILTER_CANDIDATE_SYSTEM(constraint),
                    role=Role.SYSTEM,
                ),
                Message(
                    content=Prompt._FILTER_CANDIDATE_CRASH(report_info, constraint),
                    role=Role.USER,
                ),
            ]
        )

    @staticmethod
    def FILTER_CANDIDATE_METHOD(report_info: ReportInfo, candidate: Candidate) -> str:
        parts = [
            Prompt.Part.candidate_method(candidate),
        ]
        if candidate.reasons.reason_type != ReasonTypeLiteral.NOT_OVERRIDE_METHOD:
            code = get_application_code(report_info.apk_name, candidate)
            parts.append(Prompt.Part.method_code(code, candidate.signature.class_name))

        if config.enable_candidate_reason:
            parts.append(Prompt.Part.candidate_reason(candidate))

        response_note = (
            "// Note: you just reply 'Yes.' if this candidate is directly related to the crash, otherwise you reply 'No.' at the beginning, followed by a concise reason explanation of no more than two sentences after the period. You should only reply 'yes' when you are very confident that the candidate is the cause of the crash."
            if config.enable_notes
            else "// Note: you just reply 'Yes' if this candidate is related to the crash, otherwise you reply 'No' without any additional text."
        )
        parts.append(response_note)

        if (
            config.enable_notes
            and report_info.candidates
            and report_info.candidates[0] == candidate
        ):
            parts.append(
                "// Note: this is the rank 1 candidate in our analysis tool, which means we have great confidence that this candidate may cause a crash. Therefore, unless you are very sure that this candidate has nothing to do with the crash, please do not filter out this candidate."
            )

        return Prompt.Part.merger(parts)

    EXTRACTOR_SYSTEM_PROMPT: str = dedent("""\
        Your task is to extract the precondition constraint of the target exception in Java methods and convert them into constraint related to method parameters or class field.

        Following are rules for formatting the constraints, you should replace the content in the brackets with the corresponding information:

        You should describe parameter using this format: <Parameter {0-based index of parameter}: {type of parameter} {parameter name}>
        Describe class field in this format: <Field {class name}: {type of field} {field name}> 
        Describe constraint in this format: [{Constrained method name}]: {Constraint}

        // Note: If the variable is a parameter of the method provided in `Code` or a field of the class to which it belongs, it must follow the specified format.
        // Note: We will use static analysis tool to check the result, so the parameter type must match the method signature, and the field type must match its declaration.
        // Note: These methods is from android framework, you can assume the unprovided method usage by your android expert knowledge.

        Please use the following format for the conversation(Your response should be in the same format):
        Code: ```
        Java method code and some basic information about the method.
        ```

        Exception: ```
        Target exception type name and a possible exception message

        // Note: The crash message is only used to determine which target exception it is when there are multiple exceptions of the same type, for example.
        // Do not attempt to resolve exceptions that trigger the same crash message alone.
        ```

        Constraint: ```
        Constraint related to method parameters. The method will throw **target exception** when this constraint is met.

        // Note: The constraint should not include other method, You should describe the specific effects of other methods in the constraints.
        // Note: The content of this section is the final result; this section should be independent, and you cannot reference content from other sections.
        // Note: Please pay attention to the readability of the constraint, except for maintaining a specific format, the overall constraint should be concise and readable, and it is not necessary to have a very formal constraint, but it should be able to accurately describe the crash.
        ```
        """)

    EXTRACTOR_USER_EXAMPLE1 = dedent("""\
        Code: ```
        Class Name: Pools

        public boolean release(T instance) {
            if (isInPool(instance)) {
                throw new IllegalStateException("Already in the pool!");
            }
            if (mPoolSize < mPool.length) {
                mPool[mPoolSize] = instance;
                mPoolSize++;
                return true;
            }
            return false;
        }
        ```

        Exception: ```
        Exception Type: IllegalStateException
        Exception Message: Already in the pool!
        ```
        """)

    EXTRACTOR_ASSISTANT_EXAMPLE1 = dedent("""\
        Constraint: ```
        [release]: <Parameter 0: T instance> must not already be present in <Field Pools: T[] mPool>
        ```
        """)

    @staticmethod
    def EXTRACTOR_USER_PROMPT(
        code: str, class_name: str, exception_name: str, crash_message: str
    ) -> str:
        normalized_code = dedent(code).strip()
        code_part = Prompt.Part.method_code(normalized_code, class_name)

        exception_template = Template(
            dedent("""\
            Exception:
            ```
            Exception Type: $exception_name
            Exception Message: $crash_message
            ```
        """).strip()
        )

        exception_part = exception_template.substitute(
            exception_name=exception_name, crash_message=crash_message
        )

        return Prompt.Part.merger([code_part, exception_part])

    @staticmethod
    def base_extractor_prompt() -> Conversation:
        return Conversation(
            messages=[
                Message(content=Prompt.EXTRACTOR_SYSTEM_PROMPT, role=Role.SYSTEM),
            ]
        )

    INFERRER_SYSTEM_PROMPT: str = dedent("""\
        You are an Android expert that assist with inferring the triggering constraint of the target exception in Java methods

        We will provide you with the Java method code which may trigger an exception. We will also provide a constraint of method which is invoked in code. A exception will be triggered when this constraint is met.

        Your task is to convert the constraint related with original method into constraint related to current method parameters and class field.

        All the code comes from the Android framework, for methods we have not provided, you can assume they are the Android framework methods that you are familiar with.

        Following are rules for formatting the constraints, you should replace the content in the brackets with the corresponding information:

        You should describe parameter using this format: <Parameter {0-based index of parameter}: {type of parameter} {parameter name}>
        Describe class field in this format: <Field {class name}: {type of field} {field name}> 
        Describe constraint in this format: [{Constrained method name}]: {Constraint}

        // Note: If the variable is a parameter of the method provided in `Code` or a field of the class to which it belongs, it must follow the specified format.
        // Note: We will use static analysis tool to check the result, so the parameter type must match the method signature, and the field type must match its declaration.
        // Note: These methods is from android framework, you can assume the unprovided method usage by your android expert knowledge.

        Please use the following format for the conversation(Your response should be in the same format):
        Code: ```
        Java method code and some basic information about the method.
        ```

        Original_Constraint: ```
        The constrained method and constraint content. A exception will be triggered when this constraint is met.
        ```

        Constraint: ```
        Conditions related to current method parameters or class field. Original constraint will be met if this condition is met.

        // Note: The constraint should not include other method, You should describe the specific effects of other methods in the constraints.
        // Note: The content of this section is the final result; this section should be independent, and you cannot reference content from other sections.
        // Note: Please pay attention to the readability of the constraint, except for maintaining a specific format, the overall constraint should be concise and readable, and it is not necessary to have a very formal constraint, but it should be able to accurately describe the crash.
        ``` 
        """)

    INFERRER_USER_EXAMPLE1 = dedent("""\
        Code: ```
        Class Name: AbstractWindowedCursor

        protected void checkPosition() {
            super.checkPosition();
            
            if (mWindow == null) {
                throw new StaleDataException("Attempting to access a closed CursorWindow." +
                        "Most probable cause: cursor is deactivated prior to calling this method.");
            }
        }
        ```

        Original_Constraint: ```
        [checkPosition]: <Field AbstractCursor: int mPos> == -1
        ```
        """)

    INFERRER_ASSISTANT_EXAMPLE1 = dedent("""\
        Constraint: ```
        [checkPosition]: <Field AbstractCursor: int mPos> == -1
        ```
        """)

    @staticmethod
    def INFERRER_USER_PROMPT(code: str, class_name: str, constraint: str) -> str:
        normalized_code = dedent(code).strip()
        code_part = Prompt.Part.method_code(normalized_code, class_name)

        constraint_template = Template(
            dedent("""\
                Original_Constraint:
                ```
                $constraint
                ```
            """).strip()
        )

        constraint_part = constraint_template.substitute(constraint=constraint)

        return Prompt.Part.merger([code_part, constraint_part])

    @staticmethod
    def base_inferrer_prompt() -> Conversation:
        return Conversation(
            messages=[
                Message(content=Prompt.INFERRER_SYSTEM_PROMPT, role=Role.SYSTEM),
            ]
        )
