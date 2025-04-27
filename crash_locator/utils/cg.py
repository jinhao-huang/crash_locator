from crash_locator.config import config
from cachier import cachier


def _get_cg_file_path(signature, apk_name, android_version):
    from .helper import get_method_type, MethodType

    method_type = get_method_type(signature)
    if method_type == MethodType.ANDROID:
        file_path = config.android_cg_path(android_version)
    elif (
        method_type == MethodType.ANDROID_SUPPORT
        or method_type == MethodType.APPLICATION
    ):
        file_path = config.apk_cg_path(apk_name)
    elif method_type == MethodType.JAVA:
        raise ValueError("Java method signature is not supported")
    else:
        raise ValueError("Unknown method type")

    return file_path


@cachier()
def _get_call_methods(signature, apk_name, android_version):
    from .parser import is_same_signature

    signature = signature.strip("<>")

    try:
        file_path = _get_cg_file_path(signature, apk_name, android_version)
    except ValueError:
        return set(), set()
    if not file_path.exists():
        return set(), set()

    called_signature_set = set()
    caller_signature_set = set()
    with open(file_path, "r") as lines:
        for line in lines:
            caller, callee = line.split("->")
            if is_same_signature(caller, signature):
                called_signature_set.add(callee.strip().strip("<>"))
            if is_same_signature(callee, signature):
                caller_signature_set.add(caller.strip().strip("<>"))

    return called_signature_set, caller_signature_set


def get_called_methods(unsafe_signature, apk_name, android_version):
    return _get_call_methods(unsafe_signature, apk_name, android_version)[0]


def get_callers_method(unsafe_signature, apk_name, android_version):
    return _get_call_methods(unsafe_signature, apk_name, android_version)[1]
