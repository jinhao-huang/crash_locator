import logging
from .config import Config
from crash_locator.my_types import ReportInfo
from crash_locator.exceptions import EmptyExceptionInfoException
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
from pathlib import Path
import json
import shutil
from crash_locator.my_types import PreCheckStatistic

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


def pre_check(pre_check_reports_dir: Path):
    report_name = pre_check_reports_dir.name
    crash_report_path = pre_check_reports_dir / f"{report_name}.json"
    report = json.load(open(crash_report_path, "r"))

    if len(report["Fault Localization by CrashTracker"]["Exception Info"]) == 0:
        raise EmptyExceptionInfoException(f"Empty exception info for {report_name}")

    report_completion(report)

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
        stack_trace=[
            method.strip("<>")
            for method in report["Crash Info in Dataset"]["stack trace signature"]
        ],
        stack_trace_short_api=report["Crash Info in Dataset"]["stack trace"],
        candidates=report["Fault Localization by CrashTracker"][
            "Buggy Method Candidates"
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
    work_list = crash_reports_dir.iterdir()

    with logging_redirect_tqdm():
        for crash_report_dir in tqdm(list(work_list)):
            report_name = crash_report_dir.name
            crash_report_path = crash_report_dir / f"{report_name}.json"
            if not crash_report_path.exists():
                logger.error(f"Crash report {report_name} not found")
                statistic.invalid_reports += 1
                continue

            pre_check_report_path = pre_check_reports_dir / report_name
            pre_check_report_path.mkdir(parents=True, exist_ok=True)
            shutil.copy(crash_report_path, pre_check_report_path)

            try:
                pre_check(pre_check_report_path)
            except EmptyExceptionInfoException:
                logger.error(f"Empty exception info for {report_name}")
                statistic.invalid_reports += 1
                continue

            logger.info(f"Crash report {report_name} pre-checked")
            statistic.valid_reports += 1

    with open(Config.PRE_CHECK_STATISTIC_PATH, "w") as f:
        f.write(statistic.model_dump_json(indent=4))
