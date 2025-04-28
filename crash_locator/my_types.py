import threading
from typing import Literal
from typing import Annotated
from pydantic import BaseModel, Field, PrivateAttr
import re
from crash_locator.exceptions import InvalidSignatureException
from pathlib import Path
from enum import Enum, StrEnum
from typing import Self


class PreCheckStatistic(BaseModel):
    # Total crash reports
    total_reports: int = 0
    valid_reports: int = 0
    invalid_reports: int = 0
    invalid_report_exceptions: dict[str, int] = Field(default_factory=dict)
    invalid_reports_detail: dict[str, str] = Field(default_factory=dict)
    candidates_nums_distribution: dict[int, int] = Field(default_factory=dict)


class ReportStatus(StrEnum):
    FINISHED = "finished"
    SKIPPED = "skipped"
    FAILED = "failed"


class ProcessedReportInfo(BaseModel):
    report_status: Literal[ReportStatus.FINISHED] = ReportStatus.FINISHED
    total_candidates_count: int
    retained_candidates_count: int
    is_buggy_method_filtered: bool

    @property
    def filtered_candidates_count(self) -> int:
        return self.total_candidates_count - self.retained_candidates_count


class SkippedReportInfo(BaseModel):
    report_status: Literal[ReportStatus.SKIPPED] = ReportStatus.SKIPPED


class FailedReportInfo(BaseModel):
    report_status: Literal[ReportStatus.FAILED] = ReportStatus.FAILED
    exception_type: str
    error_message: str


FinishedReport = Annotated[
    ProcessedReportInfo | SkippedReportInfo | FailedReportInfo,
    Field(discriminator="report_status"),
]


class RunStatistic(BaseModel):
    class TokenUsage(BaseModel):
        input_tokens: int = 0
        output_tokens: int = 0

        def __add__(self, other: Self) -> Self:
            return self.__class__(
                input_tokens=self.input_tokens + other.input_tokens,
                output_tokens=self.output_tokens + other.output_tokens,
            )

    class ModelInfo(BaseModel):
        model_name: str

    # Processed reports after filtering
    processed_reports: int = 0
    # Count of candidates of processed reports before filtering
    processed_candidates: int = 0
    # Count of candidates that have been filtered
    filtered_candidates: int = 0
    # Count of retained candidates
    retained_candidates: int = 0
    # Count of buggy methods that have been filtered
    filtered_buggy_method: int = 0

    # Count of skipped reports
    skipped_reports: int = 0

    # Count of failed reports
    failed_reports: int = 0

    token_usage: TokenUsage = TokenUsage()
    model_info: ModelInfo

    finished_reports_detail: dict[str, FinishedReport] = Field(
        default_factory=dict,
    )

    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _path: Path = PrivateAttr(default=None)

    def __init__(self, **data):
        path = data.pop("_path", None)
        super().__init__(**data)
        if path is not None:
            self._path = path

    def _save_statistic(self):
        if self._path is None:
            return
        with open(self._path, "w") as f:
            f.write(self.model_dump_json(indent=4))

    def add_token_usage(self, token_usage: TokenUsage):
        with self._lock:
            self.token_usage += token_usage
            self._save_statistic()

    def add_report(
        self,
        report_name: str,
        finished_report: FinishedReport,
    ):
        with self._lock:
            self.finished_reports_detail[report_name] = finished_report

            match finished_report:
                case ProcessedReportInfo():
                    self.processed_reports += 1
                    self.processed_candidates += finished_report.total_candidates_count
                    self.filtered_candidates += (
                        finished_report.filtered_candidates_count
                    )
                    self.retained_candidates += (
                        finished_report.retained_candidates_count
                    )
                    if finished_report.is_buggy_method_filtered:
                        self.filtered_buggy_method += 1
                case SkippedReportInfo():
                    self.skipped_reports += 1
                case FailedReportInfo():
                    self.failed_reports += 1
                case _:
                    raise ValueError(f"Unknown finished report info: {finished_report}")

            self._save_statistic()

    def remove_report(self, report_name: str):
        """
        Remove a (failed) report from statistic
        """
        with self._lock:
            if report_name in self.finished_reports_detail:
                if isinstance(
                    self.finished_reports_detail[report_name], FailedReportInfo
                ):
                    del self.finished_reports_detail[report_name]
                    self.failed_reports -= 1
                    self._save_statistic()
                else:
                    raise ValueError(f"Report {report_name} is not failed")
            else:
                raise ValueError(f"Report {report_name} not found")

    def set_path(self, path: Path):
        with self._lock:
            self._path = path


class ClassSignature(BaseModel):
    package_name: str
    class_name: str
    inner_class: str | None = None

    @classmethod
    def from_str(cls, class_signature: str) -> Self:
        """
        Example Class Signature:
        1. android.view.ViewRoot
        2. android.view.ViewRoot$checkThread
        """
        class_signature = class_signature.strip().strip("<>")
        pattern = r"^(\S+)\.(\w+)(\$\S+)?$"
        match = re.match(pattern, class_signature)
        if match:
            package_name, class_name, inner_class = match.groups()
            return cls(
                package_name=package_name,
                class_name=class_name,
                inner_class=inner_class,
            )
        else:
            raise InvalidSignatureException(
                f"Invalid class signature: {class_signature}"
            )

    def __str__(self) -> str:
        return f"{self.package_name}.{self.class_name}{'.' + self.inner_class if self.inner_class else ''}"


class MethodSignature(BaseModel):
    package_name: str
    class_name: str
    inner_class: str | None = None
    method_name: str
    return_type: str | None = None
    parameters: list[str] | None = None

    @classmethod
    def from_str(cls, method_signature: str) -> Self:
        """
        Example Method Signature:
        1. android.view.ViewRoot: void checkThread()
        2. android.view.ViewRoot.checkThread
        3. android.view.ViewRoot: android.view.ViewParent invalidateChildInParent(int[],android.graphics.Rect)

        Counter Example:
        1. <android.view.View: void invalidate(android.graphics.Rect)>; <android.view.View: void invalidate(int,int,int,int)>; <android.view.View: void invalidate()>
        """
        method_signature = method_signature.strip().strip("<>")
        pattern1 = r"^(\S+)\.(\w+)(\$\S+)?: (\S+) ([\w$]+|<init>)(\([^()]*?\))?$"
        pattern2 = r"^(\S+)\.(\w+)(\$\S+)?\.(\S+)$"
        match1 = re.match(pattern1, method_signature)
        match2 = re.match(pattern2, method_signature)
        if match1:
            (
                package_name,
                class_name,
                inner_class,
                return_type,
                method_name,
                parameter_list,
            ) = match1.groups()
            if inner_class:
                inner_class = inner_class.strip("$")
            if parameter_list:
                parameters = [
                    param.strip() for param in parameter_list.strip("()").split(",")
                ]
                # remove empty string
                parameters = list(filter(None, parameters))
            else:
                parameters = None
        elif match2:
            package_name, class_name, inner_class, method_name = match2.groups()
            if inner_class:
                inner_class = inner_class.strip("$")

            return_type = None
            parameters = None
        else:
            raise InvalidSignatureException(f"Invalid signature: {method_signature}")

        return cls(
            package_name=package_name,
            class_name=class_name,
            inner_class=inner_class,
            method_name=method_name,
            return_type=return_type,
            parameters=parameters,
        )

    def into_path(self) -> Path:
        return Path(self.package_name.replace(".", "/")) / f"{self.class_name}.java"

    def full_class_name(self) -> str:
        if self.inner_class:
            return f"{self.class_name}.{self.inner_class.replace('$', '.')}"
        else:
            return self.class_name

    def __str__(self) -> str:
        params = ", ".join(self.parameters) if self.parameters else ""
        return f"{self.package_name}.{self.class_name}{'.' + self.inner_class if self.inner_class else ''}: {self.return_type} {self.method_name}({params})"

    def __eq__(self, other: "MethodSignature") -> bool:
        if self.package_name != other.package_name:
            return False
        if self.class_name != other.class_name:
            return False
        if self.inner_class != other.inner_class:
            return False
        if self.method_name != other.method_name:
            return False
        if (
            self.return_type is not None
            and other.return_type is not None
            and self.return_type != other.return_type
        ):
            return False
        if (
            self.parameters is not None
            and other.parameters is not None
            and self.parameters != other.parameters
        ):
            return False
        return True


class CandidateReason(BaseModel):
    reason_type: str

    def reason_explanation(self) -> str:
        pass


class ReasonTypeLiteral(StrEnum):
    KEY_VAR_TERMINAL = "Key Variable Related 1"
    KEY_VAR_NON_TERMINAL = "Key Variable Related 2"
    KEY_API_INVOKED = "Key API Related 1"
    KEY_API_EXECUTED = "Key API Related 2 (Executed)"
    KEY_VAR_MODIFIED_FIELD = "Key Variable Related 4"
    NOT_OVERRIDE_METHOD = "Not Override Method 1"
    NOT_OVERRIDE_METHOD_EXECUTED = "Not Override Method 2 (Executed)"
    FRAMEWORK_RECALL = "Framework Recall"
    KEY_VAR_3 = "Key Variable Related 3"


class KeyVarTerminalReason(CandidateReason):
    reason_type: Literal[ReasonTypeLiteral.KEY_VAR_TERMINAL] = (
        ReasonTypeLiteral.KEY_VAR_TERMINAL
    )
    framework_entry_api: str
    call_chain_to_entry: list[str]
    terminal_api: str

    def reason_explanation(self) -> str:
        return f"""
Our static analysis tool detect that some buggy parameter value is passed to `{self.framework_entry_api}` by call chain {self.call_chain_to_entry}.

The buggy parameter meet the crash constraint which was described in `Constraint` part
"""


class KeyVarNonTerminalReason(CandidateReason):
    reason_type: Literal[ReasonTypeLiteral.KEY_VAR_NON_TERMINAL] = (
        ReasonTypeLiteral.KEY_VAR_NON_TERMINAL
    )
    framework_entry_api: str
    call_chain_to_terminal: list[str]
    terminal_api: str

    def reason_explanation(self) -> str:
        return f"""
Our static analysis tool detect that the method invoke `{self.terminal_api}` by call chain {self.call_chain_to_terminal}.

`{self.terminal_api}` method pass buggy parameter to `{self.framework_entry_api}`
"""


class KeyApiInvokedReason(CandidateReason):
    reason_type: Literal[ReasonTypeLiteral.KEY_API_INVOKED] = (
        ReasonTypeLiteral.KEY_API_INVOKED
    )
    key_api: str
    key_field: list[str]

    def reason_explanation(self) -> str:
        return f"""
We detect that the method `{self.key_api}` is invoked in the method.

The method can affect the `{self.key_field}` field in Android Framework so that cause constraint violation.
"""


class KeyApiExecutedReason(CandidateReason):
    reason_type: Literal[ReasonTypeLiteral.KEY_API_EXECUTED] = (
        ReasonTypeLiteral.KEY_API_EXECUTED
    )

    def reason_explanation(self) -> str:
        return """
This method was detected because it was executed during the process of the application crashing.
"""


class KeyVarModifiedFieldReason(CandidateReason):
    reason_type: Literal[ReasonTypeLiteral.KEY_VAR_MODIFIED_FIELD] = (
        ReasonTypeLiteral.KEY_VAR_MODIFIED_FIELD
    )
    field: str
    api: str

    # TODO: add field effect
    def reason_explanation(self) -> str:
        return f"""
Our static analysis detect that the method change the value of field `{self.field}`

The field was passed to the method `{self.api}` and meet the crash constraint, resulting in the crash.
"""


class NotOverrideMethodReason(CandidateReason):
    reason_type: Literal[ReasonTypeLiteral.NOT_OVERRIDE_METHOD] = (
        ReasonTypeLiteral.NOT_OVERRIDE_METHOD
    )
    application_class: str
    framework_method: str
    framework_class: str
    extend_chain: list[str]

    def reason_explanation(self) -> str:
        return f"""
Our static analysis tool detect that the class `{self.application_class}` extends the class `{self.framework_class}` by chain {self.extend_chain}.

When `{self.framework_method}` is invoked, an unconditional exception is thrown out.

But in the application code, the method is not override.
"""


class NotOverrideMethodExecutedReason(CandidateReason):
    reason_type: Literal[ReasonTypeLiteral.NOT_OVERRIDE_METHOD_EXECUTED] = (
        ReasonTypeLiteral.NOT_OVERRIDE_METHOD_EXECUTED
    )

    def reason_explanation(self) -> str:
        return """
This method was detected because it was executed during the process of the application crashing.
"""


class FrameworkRecallReason(CandidateReason):
    reason_type: Literal[ReasonTypeLiteral.FRAMEWORK_RECALL] = (
        ReasonTypeLiteral.FRAMEWORK_RECALL
    )

    def reason_explanation(self) -> str:
        return """
This method is not in the crash stack, it is a recall method invoked by framework method.
"""


class KeyVar3Reason(CandidateReason):
    reason_type: Literal[ReasonTypeLiteral.KEY_VAR_3] = ReasonTypeLiteral.KEY_VAR_3

    # TODO: Need more confirmation
    def reason_explanation(self) -> str:
        return """
The method is data related to the crash.
"""


class Candidate(BaseModel):
    name: str
    signature: MethodSignature
    extend_hierarchy: list[ClassSignature]
    reasons: (
        KeyVarTerminalReason
        | KeyVarNonTerminalReason
        | KeyApiInvokedReason
        | KeyApiExecutedReason
        | KeyVarModifiedFieldReason
        | NotOverrideMethodReason
        | NotOverrideMethodExecutedReason
        | FrameworkRecallReason
        | KeyVar3Reason
    ) = Field(discriminator="reason_type")


class ReportInfo(BaseModel):
    apk_name: str
    android_version: str
    regression_message: str
    exception_type: str
    crash_message: str
    stack_trace: list[str]
    stack_trace_short_api: list[str]
    framework_trace: list[str]
    framework_trace_short_api: list[str]
    framework_entry_api: str
    candidates: list[Candidate]
    ets_related_type: str
    related_variable_type: str
    related_condition_type: str
    buggy_method: MethodSignature

    @property
    def sorted_candidates(self) -> list[Candidate]:
        """
        Sort the candidates by stack trace order
        """
        sorted_candidates = []

        for method in self.stack_trace_short_api:
            for candidate in self.candidates:
                if candidate.name == method:
                    sorted_candidates.append(candidate)
                    break

        for candidate in self.candidates:
            if candidate not in sorted_candidates:
                sorted_candidates.append(candidate)

        return sorted_candidates


class PackageType(Enum):
    JAVA = "java"
    ANDROID = "android"
    APPLICATION = "application"
    ANDROID_SUPPORT = "android_support"

    @staticmethod
    def get_package_type(signature: MethodSignature | ClassSignature) -> "PackageType":
        match signature.package_name:
            case s if s.startswith("java"):
                return PackageType.JAVA
            case s if s.startswith("android.support"):
                return PackageType.ANDROID_SUPPORT
            case s if s.startswith("android") or s.startswith("com.android"):
                return PackageType.ANDROID
            case _:
                return PackageType.APPLICATION
