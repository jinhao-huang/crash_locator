from pydantic import BaseModel

class ReportInfo(BaseModel):
    apk_name: str
    android_version: str
    regression_message: str
    exception_type: str
    crash_message: str
    stack_trace: list[str]
    stack_trace_short_api: list[str]
    framework_trace: list[str]
    framework_short_trace: list[str]
    application_trace: list[str]
    application_short_trace: list[str]
    framework_pass_chain: list[list[int]]
    framework_entry_api: str
    framework_reference_fields: list[str]
    candidates: list[dict]
    ets_related_type: str
    related_variable_type: str
    related_condition_type: str