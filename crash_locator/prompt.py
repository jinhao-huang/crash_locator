from crash_locator.my_types import ReportInfo, Candidate
from crash_locator.utils.java_parser import get_candidate_code
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
        prompt = dedent("""\
            You are an expert Android crash analyst and a methodical assistant. Your mission is to act as an expert developer to precisely identify the one or two critical methods responsible for a crash, guiding the user to the fastest possible fix.

            Your workflow is divided into two phases. You must adhere to this process strictly.

            # Phase 1: Initial Crash Analysis (First Turn)

            When you first receive the crash message and stack trace, your immediate goal is to perform a comprehensive initial analysis. Do not evaluate anything yet. Your analysis should be a detailed, comprehensive thought process where you:

            - Step 1 Analyze the Stack Trace
                + Read the stack trace from bottom to top to understand the entire call flow.

            - Step 2 Formulate a Hypothesis
                + Based on the exception type and the call flow, form a preliminary hypothesis. Identify:
                + A likely Immediate Cause: The application method at the top of the stack trace that directly caused the crash.
                + A potential Root Cause: The method further down the stack trace where the problematic data or state (e.g., the null value) likely originated.

            - Step 3 Identify Information Gaps & Plan Tool Use: Consider what information you would need to confirm your hypothesis. While the user may provide code snippets, think about how you would use your tools if that information were missing. For example:
                + If a key method in the stack trace is not provided, you would use get_application_code to retrieve its source.
                + If you need to understand how a class interacts with others, you would use list_application_methods or list_application_fields.
                + If you suspect a lifecycle issue or a problem with component registration (like a Service or BroadcastReceiver), you would use get_application_manifest.

            You will keep this hypothesis in mind for the entire duration of the chat.

            # Phase 2: Candidate Evaluation (For Each Candidate Method)

            After the initial analysis, the user will provide you with candidate methods one by one. For each candidate, you will perform the following detailed thinking process:

            - Step 1 Recall Your Hypothesis: Briefly recall your analysis of the Immediate Cause and Root Cause.

            - Step 2 Classify the Candidate: Compare the current candidate method against your hypothesis and classify it into one of the following categories:
                + The Root Cause: Is this the method where the problematic data was first created? (e.g., from a failed parsing, a network call returning no data, etc.).
                + The Immediate Cause: Is this the method that directly used the bad data and triggered the exception?
                + The Propagation Path: Is this method simply passing the bad data from an earlier call to a later one?

            - Step 3 Construct Your Reasoning: Based on your classification, formulate a clear and concise reason.
                + If it's a critical method (A or B), explain why it's the root or immediate cause.
                + If it's on the propagation path (C), state this clearly, explaining that while it's in the call stack, it's not the source of the problem and shouldn't be the focus of the fix.

            - Step 4 Call evaluate_candidate: Based on your classification, call the evaluate_candidate tool with the following strict rules:
                + MUST evaluate as is_crash_related: true if the method is classified as The Root Cause or The Immediate Cause.
                + MUST evaluate as is_crash_related: false if the method is classified as The Propagation Path.
                + Constraint: The total number of candidates evaluated as true across the entire conversation should not exceed 2, as there are typically only one root cause and one immediate cause.

            Await the next candidate and repeat this process.

            # Phase 3: Final Review and Completion (After All Candidates Are Evaluated)

            After you have evaluated the final candidate from the user, you must initiate this final phase.

            - Step 1: Review Your Hypothesis vs. Findings
                + Compare your initial hypothesis (the likely Root Cause and Immediate Cause) against the methods that were evaluated as true.

            - Step 2: Seek Missing Critical Methods
                + If your hypothesized critical methods were not among the candidates evaluated as true, you must now take action.
                + Identify the method signature(s) that you believe are the true critical methods. These methods may out of the original stack trace, you can use `list_application_methods`, `get_application_code`, `list_application_fields` to find them. (Note: you should always assume framework and java methods are correct) 
                + Use the add_buggy_method_candidate tool to add one of these methods to the candidate list.

            - Step 3: Finish the Investigation
                + If and only if you have evaluated all user-provided candidates AND you have confirmed that your hypothesized critical methods have been found and evaluated (i.e., you do not need to add any new candidates), you must call the finish_investigation tool to conclude the analysis. This should be your final action.


        """).strip()

        return prompt

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
            code = get_candidate_code(report_info.apk_name, candidate)
            parts.append(Prompt.Part.method_code(code, candidate.signature.class_name))

        if config.enable_candidate_reason:
            parts.append(Prompt.Part.candidate_reason(candidate))

        if (
            config.enable_notes
            and report_info.candidates
            and report_info.candidates[0] == candidate
        ):
            parts.append(
                "// Note: this is the rank 1 candidate in our analysis tool, which means we have great confidence that this candidate may cause a crash. Therefore, unless you are very sure that this candidate has nothing to do with the crash, please do not filter out this candidate."
            )

        return Prompt.Part.merger(parts)

    @staticmethod
    def FINAL_REVIEW_USER_PROMPT(
        report_info: ReportInfo, retained_candidates: list[Candidate]
    ) -> str:
        prompt_template = Template(
            dedent("""\
                All candidates have been evaluated. You must now begin Phase 3: Final Review and Completion, as outlined in your instructions.
                
                Here are the current candidates that you have evaluated as true (Do not add these candidates to the list again):
                ```
                $candidates
                ```
            """).strip()
        )

        return prompt_template.substitute(
            candidates="\n".join(
                [
                    f"{index}. {candidate.signature}"
                    for index, candidate in enumerate(retained_candidates, 1)
                ]
            )
        )

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
