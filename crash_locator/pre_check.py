import logging
from crash_locator.config import config, setup_logging
from crash_locator.my_types import (
    PackageType,
    ReportInfo,
    CandidateReason,
    ClassSignature,
)
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
    MethodCodeException,
    NoBuggyMethodCandidatesException,
    CandidateCodeNotFoundException,
    NoTerminalAPIException,
    FrameworkCodeNotFoundException,
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
from crash_locator.utils.helper import get_method_type
from crash_locator.utils.java_parser import get_application_code, get_framework_code

logger = logging.getLogger()
statistic = PreCheckStatistic()


def _get_android_version(report: dict) -> str:
    if (
        "Target Version of Framework"
        in report["Fault Localization by CrashTracker"]["Exception Info"]
    ):
        return report["Fault Localization by CrashTracker"]["Exception Info"][
            "Target Version of Framework"
        ]
    else:
        match report["Crash Info in Dataset"]["Manifest targetSdkVersion"]:
            case v if v <= 8:
                return "2.2"
            case v if v < 19:
                return "2.3"
            case v if v < 21:
                return "4.4"
            case v if v < 23:
                return "5.0"
            case v if v < 24:
                return "6.0"
            case v if v < 26:
                return "7.0"
            case v if v < 28:
                return "8.0"
            case v if v < 29:
                return "9.0"
            case v if v < 30:
                return "10.0"
            case v if v < 31:
                return "11.0"
            case _:
                return "12.0"


def report_completion(report):
    """
    Complete the full signature stack trace of report.
    """
    apk_name = report["Crash Info in Dataset"]["Apk name"]
    android_version = _get_android_version(report)
    stack_trace = report["Crash Info in Dataset"]["stack trace signature"]

    def _get_ambiguous_method_indexes(
        stack_trace: list[str],
    ) -> list[tuple[int, int]]:
        indexes = []
        index = 0
        while index < len(stack_trace):
            if ";" in stack_trace[index]:
                end_index = index
                while (
                    end_index + 1 < len(stack_trace)
                    and stack_trace[end_index + 1] == stack_trace[index]
                ):
                    end_index += 1
                indexes.append((index, end_index))
                index = end_index + 1
            else:
                index += 1

        return indexes

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

    def complete_stack_trace_with_pattern(stack_trace: list[str]):
        patterns = {
            "<android.app.Activity: void startActivityForResult(android.content.Intent,int,android.os.Bundle)>; <android.app.Activity: void startActivityForResult(java.lang.String,android.content.Intent,int,android.os.Bundle)>; <android.app.Activity: void startActivityForResult(android.content.Intent,int)>": {
                2: [
                    "android.app.Activity: void startActivityForResult(android.content.Intent,int,android.os.Bundle)",
                    "android.app.Activity: void startActivityForResult(android.content.Intent,int)",
                ]
            },
            "<android.app.Activity: void startActivity(android.content.Intent)>; <android.app.Activity: void startActivity(android.content.Intent,android.os.Bundle)>": {
                2: [
                    "android.app.Activity: void startActivity(android.content.Intent,android.os.Bundle)",
                    "android.app.Activity: void startActivity(android.content.Intent)",
                ]
            },
            "<android.os.Parcel: void readException(int,java.lang.String)>; <android.os.Parcel: void readException()>": {
                1: ["android.os.Parcel: void readException(int,java.lang.String)"],
                2: [
                    "android.os.Parcel: void readException(int,java.lang.String)",
                    "android.os.Parcel: void readException()",
                ],
            },
            "<android.location.LocationManager: void requestLocationUpdates(java.lang.String,long,float,android.app.PendingIntent)>; <android.location.LocationManager: void requestLocationUpdates(java.lang.String,long,float,android.location.LocationListener,android.os.Looper)>; <android.location.LocationManager: void requestLocationUpdates(java.lang.String,long,float,android.location.LocationListener)>": {
                2: [
                    "android.location.LocationManager: void requestLocationUpdates(java.lang.String,long,float,android.location.LocationListener,android.os.Looper)",
                    "android.location.LocationManager: void requestLocationUpdates(java.lang.String,long,float,android.location.LocationListener)",
                ]
            },
        }

        renew_flag = False
        for start_index, end_index in _get_ambiguous_method_indexes(stack_trace):
            ambiguous_methods_str = stack_trace[start_index]
            ambiguous_methods_len = end_index - start_index + 1
            if (
                ambiguous_methods_str in patterns
                and ambiguous_methods_len in patterns[ambiguous_methods_str]
            ):
                renew_flag = True
                ambiguous_methods = patterns[ambiguous_methods_str][
                    ambiguous_methods_len
                ]
                for i in range(start_index, end_index + 1):
                    stack_trace[i] = ambiguous_methods[i - start_index]

        return renew_flag

    from .utils.cg import get_called_methods, get_callers_method

    while True:
        if complete_stack_trace_with_pattern(stack_trace):
            continue

        new_trace = complete_self_invoke_trace(stack_trace, apk_name, android_version)
        if new_trace is not None:
            stack_trace = new_trace
            continue

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


def _find_terminal_api(candidates: list[dict]) -> str | None:
    for candidate in candidates:
        for reason in candidate["Reasons"]:
            if reason.get("M_app Is Terminate?") is True:
                return candidate["Candidate Signature"]

    return None


def _get_and_check_framework_stack(
    stack_trace: list[str], stack_trace_short_api: list[str]
) -> tuple[list[str], list[str]]:
    framework_trace = []
    framework_short_trace = []
    divider_index = None

    for index, (method, method_short_api) in enumerate(
        zip(stack_trace, stack_trace_short_api)
    ):
        method_type = get_method_type(method)
        if method_type == PackageType.ANDROID:
            framework_trace.append(method)
            framework_short_trace.append(method_short_api)
        elif method_type == PackageType.ANDROID_SUPPORT:
            framework_trace.append(method)
            framework_short_trace.append(method_short_api)
        elif method_type == PackageType.JAVA:
            raise InvalidFrameworkStackException("Java method in framework stack trace")
        elif method_type == PackageType.APPLICATION:
            divider_index = index
            break

    if len(framework_trace) == 0 or divider_index is None:
        raise InvalidFrameworkStackException(
            "Cannot find the divider index of the framework stack trace"
        )

    return framework_trace, framework_short_trace


def _candidate_into_reason(
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
                raise NoTerminalAPIException()
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


def _check_exception_info_exist(report: dict) -> None:
    if "Fault Localization by CrashTracker" not in report:
        raise EmptyExceptionInfoException()
    if "Exception Info" not in report["Fault Localization by CrashTracker"]:
        raise EmptyExceptionInfoException()
    if len(report["Fault Localization by CrashTracker"]["Exception Info"]) == 0:
        raise EmptyExceptionInfoException()


def _check_buggy_method_candidates_exist(report: ReportInfo) -> None:
    buggy_method = report.buggy_method
    for candidate in report.candidates:
        if candidate.signature == buggy_method:
            return
    raise NoBuggyMethodCandidatesException()


def _remove_useless_candidates(report: ReportInfo) -> None:
    report.candidates = [
        candidate
        for candidate in report.candidates
        if not candidate.signature.method_name.startswith("access$")
    ]


def _check_candidate_code_exist(report: ReportInfo) -> None:
    """Check if the candidate code exist
    If candidate code not exists in **application code directory**, the candidate will be removed.
    if candidate code not found, raise CandidateCodeNotFoundException.
    """
    for candidate in report.candidates[:]:
        try:
            get_application_code(report.apk_name, candidate)
        except MethodCodeException:
            raise CandidateCodeNotFoundException(str(candidate.signature))
        except ValueError:
            if candidate.reasons.reason_type != ReasonTypeLiteral.NOT_OVERRIDE_METHOD:
                report.candidates.remove(candidate)


def _check_framework_code_exist(report: ReportInfo) -> None:
    for method in report.framework_trace:
        try:
            get_framework_code(method, report.android_version)
        except MethodCodeException as e:
            raise FrameworkCodeNotFoundException(method, str(e))


def _fix_candidate_signature(report: ReportInfo) -> None:
    """
    Fix the candidate signature due to CrashTracker candidate signature error.
    """
    for candidate in report.candidates:
        if candidate.reasons.reason_type == ReasonTypeLiteral.KEY_VAR_TERMINAL:
            target_method = None
            duplicate_method = False
            for method, method_short_api in zip(
                report.stack_trace, report.stack_trace_short_api
            ):
                sig: MethodSignature = MethodSignature.from_str(method)
                if method_short_api == candidate.name and sig != candidate.signature:
                    if target_method is None:
                        target_method = method
                    else:
                        duplicate_method = True
                        statistic.fixed_failed_duplicate += 1
                        break

            if target_method is not None and not duplicate_method:
                statistic.fixed_reports += 1
                if report.apk_name not in statistic.fixed_reports_detail:
                    statistic.fixed_reports_detail[report.apk_name] = []
                statistic.fixed_reports_detail[report.apk_name].append(
                    {
                        "before": str(candidate.signature),
                        "after": str(MethodSignature.from_str(target_method)),
                    }
                )

                candidate.signature = MethodSignature.from_str(target_method)


def pre_check(crash_report_path: Path) -> ReportInfo:
    report = json.load(open(crash_report_path, "r"))

    report_completion(report)

    stack_trace = [
        method.strip("<>")
        for method in report["Crash Info in Dataset"]["stack trace signature"]
    ]
    stack_trace_short_api = report["Crash Info in Dataset"]["stack trace"]
    framework_trace, framework_short_trace = _get_and_check_framework_stack(
        stack_trace, stack_trace_short_api
    )
    framework_entry_api = framework_trace[-1]
    terminal_api = _find_terminal_api(
        report["Fault Localization by CrashTracker"]["Buggy Method Candidates"]
    )

    report_info = ReportInfo(
        apk_name=report["Crash Info in Dataset"]["Apk name"],
        android_version=_get_android_version(report),
        target_sdk_version=report["Crash Info in Dataset"]["Manifest targetSdkVersion"],
        exception_type=report["Crash Info in Dataset"]["Exception Type"]
        .split(".")[-1]
        .split("$")[-1],
        stack_trace=stack_trace,
        stack_trace_short_api=stack_trace_short_api,
        framework_trace=[
            MethodSignature.from_str(method) for method in framework_trace
        ],
        framework_trace_short_api=framework_short_trace,
        framework_entry_api=framework_entry_api,
        candidates=[
            Candidate(
                name=candidate["Candidate Name"],
                signature=MethodSignature.from_str(candidate["Candidate Signature"])
                if candidate["Candidate Signature"] != ""
                else MethodSignature.from_str(candidate["Candidate Name"]),
                extend_hierarchy=[
                    ClassSignature.from_str(extend_hierarchy)
                    for extend_hierarchy in candidate["Extend Hierarchy"]
                ],
                reasons=_candidate_into_reason(
                    candidate, framework_entry_api, terminal_api
                ),
            )
            for candidate in report["Fault Localization by CrashTracker"][
                "Buggy Method Candidates"
            ]
        ],
        crash_message=report["Crash Info in Dataset"]["Crash Message"],
        buggy_method=MethodSignature.from_str(
            report["Crash Info in Dataset"]["Labeled Buggy Method"]
        ),
    )

    _fix_candidate_signature(report_info)
    _remove_useless_candidates(report_info)
    _check_candidate_code_exist(report_info)
    _check_framework_code_exist(report_info)
    _check_buggy_method_candidates_exist(report_info)

    return report_info


def _successful_statistic(report: ReportInfo, statistic: PreCheckStatistic):
    if len(report.candidates) not in statistic.candidates_nums_distribution:
        statistic.candidates_nums_distribution[len(report.candidates)] = 0
    statistic.candidates_nums_distribution[len(report.candidates)] += 1

    statistic.valid_reports += 1


def _failed_statistic(
    report_name: str, statistic: PreCheckStatistic, e: PreCheckException
):
    exception_name = e.__class__.__name__
    if exception_name not in statistic.invalid_report_exceptions:
        statistic.invalid_report_exceptions[exception_name] = 0

    statistic.invalid_report_exceptions[exception_name] += 1
    statistic.invalid_reports_detail[report_name] = str(e)

    statistic.invalid_reports += 1


def _save_report(report_name: str, report_info: ReportInfo) -> None:
    pre_check_report_dir = config.pre_check_reports_dir / report_name
    pre_check_report_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy(config.crash_report_path(report_name), pre_check_report_dir)

    with open(config.pre_check_report_info_path(report_name), "w") as f:
        f.write(report_info.model_dump_json(indent=4))


def main():
    setup_logging(config.pre_check_dir)

    work_list = config.crash_reports_dir.iterdir()
    if config.debug:
        work_list = [
            report_dir
            for report_dir in work_list
            if report_dir.name in config.debug_crash_reports
        ]

    with logging_redirect_tqdm():
        for crash_report_dir in tqdm(list(work_list)):
            report_name = crash_report_dir.name
            crash_report_path = config.crash_report_path(report_name)
            if not crash_report_path.exists():
                logger.error(f"The directory {crash_report_dir} is not a crash report")
                continue

            statistic.total_reports += 1
            logger.info(f"Pre-checking report {report_name}")
            logger.debug(f"Crash report directory: {crash_report_dir}")
            logger.debug(f"Crash report path: {crash_report_path}")

            try:
                report_info = pre_check(crash_report_path)
            except PreCheckException as e:
                logger.error(f"Crash report {report_name} pre-check failed: {e}")
                _failed_statistic(report_name, statistic, e)
            except Exception as e:
                logger.exception(e)
                logger.critical(
                    f"Crash report {report_name} pre-check raise unexpected exception"
                )
                logger.critical(f"Crash report path: {crash_report_dir}")
                exit(1)
            else:
                logger.info(f"Crash report {report_name} pre-check successful")
                _save_report(report_name, report_info)
                _successful_statistic(report_info, statistic)

    with open(config.pre_check_statistic_path, "w") as f:
        logger.info(f"Pre-check statistic: {statistic}")
        f.write(statistic.model_dump_json(indent=4))


if __name__ == "__main__":
    main()
