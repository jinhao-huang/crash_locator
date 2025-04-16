from pydantic import BaseModel


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
