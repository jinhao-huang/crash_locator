from crash_locator.my_types import ReportInfo, Candidate
from crash_locator.utils.java_parser import get_application_code


class Prompt:
    FILTER_CANDIDATE_SYSTEM: str = """
You are an Android expert that assist with locating the cause of the crash of Android application.

You will be given a crash report first, then you need to analyze the crash report and the cause of the crash.

Then, we will give you a candidate method at a time, and you need to analyze whether the candidate method is related to the crash.

For those candidate methods that are most likely to be related to the crash, you just reply "Yes"(Usually the numbers "Yes" is less than 3), otherwise you reply "No" without any additional text.
"""

    @staticmethod
    def FILTER_CANDIDATE_CRASH(report_info: ReportInfo) -> str:
        return f"""
Crash Report:
```
{report_info.crash_message}
```

Stack Trace:
```
{report_info.stack_trace}
```

Exception Type:
```
{report_info.exception_type}
```

Android Version:
```
{report_info.android_version}
```
"""

    @staticmethod
    def FILTER_CANDIDATE_METHOD(report_info: ReportInfo, candidate: Candidate) -> str:
        code = get_application_code(report_info.apk_name, candidate)
        return f"""
Candidate Method: {candidate.signature}

Method Code:
```
{code}
```

Candidate Reason:
```
{candidate.reasons.reason_explanation()}
```
"""
