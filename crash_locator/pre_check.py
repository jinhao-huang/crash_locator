import logging
import traceback
from crash_locator.config import Config
from crash_locator.my_types import ReportInfo, CandidateReason
from crash_locator.my_types import (
    KeyVarTerminalReason,
    KeyVarNonTerminalReason,
    KeyApiInvokedReason,
    KeyApiExecutedReason,
    KeyVarModifiedFieldReason,
    NotOverrideMethodReason,
    NotOverrideMethodExecutedReason,
    FrameworkRecallReason,
    KeyVar3Reason,
)
from crash_locator.exceptions import (
    EmptyExceptionInfoException,
    PreCheckException,
    InvalidFrameworkStackException,
)
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
from pathlib import Path
import json
import shutil
from crash_locator.my_types import (
    PreCheckStatistic,
    Candidate,
    MethodSignature,
    ReasonTypeLiteral,
)
from crash_locator.utils.helper import get_method_type, MethodType

logger = logging.getLogger(__name__)


def report_completion(report):
    """
    Complete the full signature stack trace of report.
    """
    apk_name = report["Crash Info in Dataset"]["Apk name"]
    android_version = report["Fault Localization by CrashTracker"]["Exception Info"][
        "Target Version of Framework"
    ]
    stack_trace = report["Crash Info in Dataset"]["stack trace signature"]

    def complete_self_invoke_trace(stack_trace, apk_name, android_version):
        stack_trace_reverse = list(reversed(stack_trace))
        for index, (first_sig, second_sig) in enumerate(
            zip(stack_trace_reverse, stack_trace_reverse[1:])
        ):
            if first_sig != second_sig:
                continue
            if ";" not in first_sig:
                continue

            end_index = index + 1
            while (
                end_index < (len(stack_trace_reverse) - 1)
                and stack_trace_reverse[end_index + 1] == first_sig
            ):
                end_index += 1

            methods = set([s.strip().strip("<>") for s in first_sig.split(";")])

            valid_count = 0
            next_method = {}
            for m in methods:
                called_methods = get_called_methods(m, apk_name, android_version)
                if len(called_methods) == 1:
                    called_method = called_methods.pop()
                    if called_method in methods:
                        next_method[m] = called_method
                        valid_count += 1

            if valid_count != len(methods) - 1:
                continue
            invoke_list = []
            for m in methods:
                if m not in set(next_method.values()):
                    invoke_list.append(m)
                    break

            while invoke_list[-1] in next_method:
                invoke_list.append(next_method[invoke_list[-1]])

            for i in range(end_index, index - 1, -1):
                stack_trace_reverse[i] = invoke_list.pop()

            return list(reversed(stack_trace_reverse))

        return None

    def complete_stack_trace(stack_trace, apk_name, android_version, call_func):
        from .utils.parser import parse_signature, InvalidSignatureException

        for index, (first_sig, second_sig) in enumerate(
            zip(stack_trace, stack_trace[1:])
        ):
            try:
                parse_signature(first_sig)
            except InvalidSignatureException:
                continue
            if ";" not in second_sig:
                continue

            called_methods = call_func(first_sig, apk_name, android_version)
            second_sig_set = set([s.strip().strip("<>") for s in second_sig.split(";")])
            common_methods = called_methods & second_sig_set

            if len(common_methods) == 1:
                stack_trace[index + 1] = common_methods.pop()
                return True
        return False

    from .utils.cg import get_called_methods, get_callers_method

    while True:
        new_trace = complete_self_invoke_trace(stack_trace, apk_name, android_version)
        if new_trace is not None:
            stack_trace = new_trace
            continue
        break

    while True:
        stack_trace_reverse = list(reversed(stack_trace))
        if complete_stack_trace(
            stack_trace_reverse, apk_name, android_version, get_called_methods
        ):
            stack_trace = list(reversed(stack_trace_reverse))
            continue
        elif complete_stack_trace(
            stack_trace, apk_name, android_version, get_callers_method
        ):
            continue
        break

    report["Crash Info in Dataset"]["stack trace signature"] = stack_trace


def find_terminal_api(candidates: list[dict]) -> str | None:
    for candidate in candidates:
        for reason in candidate["Reasons"]:
            if reason.get("M_app Is Terminate?") is True:
                return candidate["Candidate Signature"]

    return None


def get_framework_stack(
    stack_trace: list[str], stack_trace_short_api: list[str]
) -> tuple[list[str], list[str]]:
    framework_trace = []
    framework_short_trace = []
    divider_index = None

    for index, (method, method_short_api) in enumerate(
        zip(stack_trace, stack_trace_short_api)
    ):
        method_type = get_method_type(method)
        if method_type == MethodType.ANDROID:
            framework_trace.append(method)
            framework_short_trace.append(method_short_api)
        elif method_type == MethodType.ANDROID_SUPPORT:
            framework_trace.append(method)
            framework_short_trace.append(method_short_api)
        elif method_type == MethodType.JAVA:
            raise InvalidFrameworkStackException("Java method in framework stack trace")
        elif method_type == MethodType.APPLICATION:
            divider_index = index
            break

    if len(framework_trace) == 0 or divider_index is None:
        raise InvalidFrameworkStackException(
            f"Invalid framework stack trace: {stack_trace}"
        )

    return framework_trace, framework_short_trace


def candidate_into_reason(
    candidate: dict, framework_entry_api: str, terminal_api: str | None
) -> CandidateReason:
    def _extract_var4_field_and_passed_method(explanation_info):
        import re

        pattern = "Value of the (\d+) parameter \(start from 0\) in API (\S+) may be wrong and trigger crash\. Method \S+ modify the field variable (\<[\S ]+\>), which may influence the buggy parameter value\."

        m = re.match(pattern, explanation_info)
        if m:
            index, api, field = m.groups()
            return int(index), api, field

    candidate_reason = candidate["Reasons"][0]
    reason_type = candidate_reason["Explanation Type"]
    match reason_type:
        case ReasonTypeLiteral.KEY_VAR_TERMINAL:
            call_chain_to_entry = candidate_reason["M_app Trace to Crash API"]
            terminal_api = call_chain_to_entry[0]

            return KeyVarTerminalReason(
                framework_entry_api=framework_entry_api,
                call_chain_to_entry=call_chain_to_entry,
                terminal_api=terminal_api,
            )
        case ReasonTypeLiteral.KEY_VAR_NON_TERMINAL:
            if terminal_api is not None:
                call_methods = candidate_reason["M_app Trace to Crash API"]
                call_chain_to_terminal = []
                for method in call_methods:
                    call_chain_to_terminal.append(method)
                    if method == terminal_api:
                        break
            else:
                raise NotImplementedError(
                    "Non-terminal key variable explanation is not implemented yet"
                )
            return KeyVarNonTerminalReason(
                framework_entry_api=framework_entry_api,
                call_chain_to_terminal=call_chain_to_terminal,
                terminal_api=terminal_api,
            )
        case ReasonTypeLiteral.KEY_API_INVOKED:
            key_api = candidate_reason["M_frame Triggered KeyAPI"]
            key_field = candidate_reason["M_frame Influenced Field"]
            return KeyApiInvokedReason(
                key_api=key_api,
                key_field=key_field,
            )
        case ReasonTypeLiteral.KEY_API_EXECUTED:
            return KeyApiExecutedReason()
        case ReasonTypeLiteral.KEY_VAR_MODIFIED_FIELD:
            _, api, field = _extract_var4_field_and_passed_method(
                candidate_reason["Explanation Info"]
            )
            return KeyVarModifiedFieldReason(
                field=field,
                api=api,
            )
        case ReasonTypeLiteral.NOT_OVERRIDE_METHOD:
            application_class = candidate_reason["M_app NotOverride Class"]
            framework_method = candidate_reason[
                "M_frame Unconditional Exception Method"
            ]
            framework_class = candidate_reason[
                "M_app NotOverride Class Extend M_frame Class"
            ]
            extend_chain = candidate_reason["M_app Extend Relationship"]
            return NotOverrideMethodReason(
                application_class=application_class,
                framework_method=framework_method,
                framework_class=framework_class,
                extend_chain=extend_chain,
            )
        case ReasonTypeLiteral.NOT_OVERRIDE_METHOD_EXECUTED:
            return NotOverrideMethodExecutedReason()
        case ReasonTypeLiteral.FRAMEWORK_RECALL:
            return FrameworkRecallReason()
        case ReasonTypeLiteral.KEY_VAR_3:
            return KeyVar3Reason()
        case _:
            raise NotImplementedError(f"Reason type {reason_type} is not implemented")


def pre_check(pre_check_reports_dir: Path):
    report_name = pre_check_reports_dir.name
    crash_report_path = pre_check_reports_dir / f"{report_name}.json"
    report = json.load(open(crash_report_path, "r"))

    if len(report["Fault Localization by CrashTracker"]["Exception Info"]) == 0:
        raise EmptyExceptionInfoException(f"Empty exception info for {report_name}")
    report_completion(report)

    stack_trace = [
        method.strip("<>")
        for method in report["Crash Info in Dataset"]["stack trace signature"]
    ]
    stack_trace_short_api = report["Crash Info in Dataset"]["stack trace"]
    framework_trace, framework_short_trace = get_framework_stack(
        stack_trace, stack_trace_short_api
    )
    framework_entry_api = framework_trace[-1]
    terminal_api = find_terminal_api(
        report["Fault Localization by CrashTracker"]["Buggy Method Candidates"]
    )

    report_info = ReportInfo(
        apk_name=report["Crash Info in Dataset"]["Apk name"],
        android_version=report["Fault Localization by CrashTracker"]["Exception Info"][
            "Target Version of Framework"
        ],
        regression_message=report["Fault Localization by CrashTracker"][
            "Exception Info"
        ]["Regression Message"],
        exception_type=report["Crash Info in Dataset"]["Exception Type"]
        .split(".")[-1]
        .split("$")[-1],
        ets_related_type=report["Fault Localization by CrashTracker"]["Exception Info"][
            "ETS-related Type"
        ],
        related_variable_type=report["Fault Localization by CrashTracker"][
            "Exception Info"
        ]["Related Variable Type"],
        related_condition_type=report["Fault Localization by CrashTracker"][
            "Exception Info"
        ]["Related Condition Type"],
        stack_trace=stack_trace,
        stack_trace_short_api=stack_trace_short_api,
        framework_trace=framework_trace,
        framework_trace_short_api=framework_short_trace,
        framework_entry_api=framework_entry_api,
        candidates=[
            Candidate(
                name=candidate["Candidate Name"],
                signature=MethodSignature.from_str(candidate["Candidate Signature"])
                if candidate["Candidate Signature"] != ""
                else MethodSignature.from_str(candidate["Candidate Name"]),
                reasons=candidate_into_reason(
                    candidate, framework_entry_api, terminal_api
                ),
            )
            for candidate in report["Fault Localization by CrashTracker"][
                "Buggy Method Candidates"
            ]
        ],
        crash_message=report["Crash Info in Dataset"]["Crash Message"],
    )

    output_file_path = pre_check_reports_dir / Config.PRE_CHECK_REPORT_INFO_NAME
    with open(output_file_path, "w") as json_file:
        json_file.write(report_info.model_dump_json(indent=4))


if __name__ == "__main__":
    crash_reports_dir = Config.CRASH_REPORTS_DIR
    pre_check_reports_dir = Config.PRE_CHECK_REPORTS_DIR
    statistic = PreCheckStatistic()
    if Config.DEBUG:
        work_list = [Config.DEBUG_CRASH_REPORT_DIR]
    else:
        work_list = crash_reports_dir.iterdir()

    with logging_redirect_tqdm():
        for crash_report_dir in tqdm(list(work_list)):
            statistic.total_reports += 1
            report_name = crash_report_dir.name
            crash_report_path = crash_report_dir / f"{report_name}.json"
            if not crash_report_path.exists():
                logger.error(f"Crash report {report_name} not found")
                statistic.invalid_reports += 1
                continue

            logger.info(f"Pre-checking report {report_name}")
            logger.debug(f"Crash report directory: {crash_report_dir}")
            logger.debug(f"Crash report path: {crash_report_path}")
            pre_check_report_path = pre_check_reports_dir / report_name
            pre_check_report_path.mkdir(parents=True, exist_ok=True)
            shutil.copy(crash_report_path, pre_check_report_path)

            try:
                pre_check(pre_check_report_path)
            except PreCheckException as e:
                logger.error(f"Crash report {report_name} pre-check failed: {e}")
                statistic.invalid_reports += 1
                shutil.rmtree(pre_check_report_path)
                if e.__class__.__name__ not in statistic.invalid_report_exception:
                    statistic.invalid_report_exception[e.__class__.__name__] = 0
                statistic.invalid_report_exception[e.__class__.__name__] += 1
                continue
            except Exception:
                logger.error(traceback.format_exc())
                logger.error(f"Crash report path: {crash_report_dir}")
                exit(1)

            logger.info(f"Crash report {report_name} pre-check finished")
            statistic.valid_reports += 1

    with open(Config.PRE_CHECK_STATISTIC_PATH, "w") as f:
        logger.info(f"Pre-check statistic: {statistic}")
        f.write(statistic.model_dump_json(indent=4))
