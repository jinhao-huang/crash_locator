from pydantic import BaseModel
import re
from crash_locator.exceptions import InvalidSignatureException
from pathlib import Path


class PreCheckStatistic(BaseModel):
    total_reports: int = 0
    valid_reports: int = 0
    invalid_reports: int = 0


class ReportInfo(BaseModel):
    apk_name: str
    android_version: str
    regression_message: str
    exception_type: str
    crash_message: str
    stack_trace: list[str]
    stack_trace_short_api: list[str]
    candidates: list[dict]
    ets_related_type: str
    related_variable_type: str
    related_condition_type: str


class RunStatistic(BaseModel):
    total_methods: int = 0
    valid_methods: int = 0
    invalid_methods: int = 0
    total_reports: int = 0
    valid_reports: int = 0
    invalid_reports: int = 0


class MethodSignature(BaseModel):
    package_name: str
    class_name: str
    inner_class: str | None = None
    method_name: str
    return_type: str | None = None
    parameters: list[str] | None = None

    def __init__(self, method_signature: str):
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

        super().__init__(
            package_name=package_name,
            class_name=class_name,
            inner_class=inner_class,
            method_name=method_name,
            return_type=return_type,
            parameters=parameters,
        )

    def into_path(self) -> Path:
        return Path(self.package_name.replace(".", "/")) / f"{self.class_name}.java"
