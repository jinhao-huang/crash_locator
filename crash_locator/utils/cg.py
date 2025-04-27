def get_cg_file_path(signature, apk_name, android_version):
    from crash_locator.config import config

    APK_CG_PATH = config.apk_cg_path
    ANDROID_CG_PATH = config.android_cg_path
    from .helper import get_method_type, MethodType

    method_type = get_method_type(signature)
    if method_type == MethodType.ANDROID:
        file_path = ANDROID_CG_PATH(android_version)
    elif (
        method_type == MethodType.ANDROID_SUPPORT
        or method_type == MethodType.APPLICATION
    ):
        file_path = APK_CG_PATH(apk_name)
    elif method_type == MethodType.JAVA:
        raise ValueError("Java method signature is not supported")
    else:
        raise ValueError("Unknown method type")

    return file_path


def get_cache_cg_file_path(signature, apk_name, android_version, called):
    from crash_locator.config import config

    ANDROID_CG_CALLED_CACHE_PATH = config.android_cg_called_cache_path
    ANDROID_CG_CALLER_CACHE_PATH = config.android_cg_caller_cache_path
    APK_CG_CALLED_CACHE_PATH = config.apk_cg_called_cache_path
    APK_CG_CALLER_CACHE_PATH = config.apk_cg_caller_cache_path

    from .helper import get_method_type, MethodType
    import hashlib

    hashed_signature = hashlib.sha256(signature.encode()).hexdigest()
    method_type = get_method_type(signature)
    if method_type == MethodType.ANDROID:
        if android_version == "support":
            raise ValueError("Android support version is not supported")
        if called:
            file_path = ANDROID_CG_CALLED_CACHE_PATH(android_version, hashed_signature)
        else:
            file_path = ANDROID_CG_CALLER_CACHE_PATH(android_version, hashed_signature)
    elif (
        method_type == MethodType.ANDROID_SUPPORT
        or method_type == MethodType.APPLICATION
    ):
        if called:
            file_path = APK_CG_CALLED_CACHE_PATH(apk_name, hashed_signature)
        else:
            file_path = APK_CG_CALLER_CACHE_PATH(apk_name, hashed_signature)
    elif method_type == MethodType.JAVA:
        raise ValueError("Java method signature is not supported")
    else:
        raise ValueError("Unknown method type")

    return file_path


def get_called_methods(unsafe_signature, apk_name, android_version):
    from .parser import is_same_signature
    import json
    import os

    signature = unsafe_signature.strip("<>")
    try:
        cache_file_path = get_cache_cg_file_path(
            signature, apk_name, android_version, True
        )
    except ValueError:
        return set()
    if os.path.exists(cache_file_path):
        with open(cache_file_path, "r") as f:
            cache_file = json.load(f)
            if signature in cache_file:
                return set(cache_file[signature])

    try:
        file_path = get_cg_file_path(signature, apk_name, android_version)
    except ValueError:
        return set()
    called_signature_set = set()
    with open(file_path, "r") as lines:
        for line in lines:
            caller, callee = line.split("->")
            if is_same_signature(caller, signature):
                called_signature_set.add(callee.strip().strip("<>"))

    os.makedirs(os.path.dirname(cache_file_path), exist_ok=True)
    if os.path.exists(cache_file_path):
        with open(cache_file_path, "r") as f:
            cache_file = json.load(f)
    else:
        cache_file = {}

    cache_file[signature] = list(called_signature_set)

    with open(cache_file_path, "w") as f:
        json.dump(cache_file, f, indent=4)

    return called_signature_set


def get_callers_method(unsafe_signature, apk_name, android_version):
    from .parser import is_same_signature
    import json
    import os

    signature = unsafe_signature.strip("<>")
    try:
        cache_file_path = get_cache_cg_file_path(
            signature, apk_name, android_version, False
        )
    except ValueError:
        return set()
    if os.path.exists(cache_file_path):
        with open(cache_file_path, "r") as f:
            cache_file = json.load(f)
            if signature in cache_file:
                return set(cache_file[signature])

    try:
        file_path = get_cg_file_path(signature, apk_name, android_version)
    except ValueError:
        return set()
    caller_signature_set = set()
    with open(file_path, "r") as lines:
        for line in lines:
            caller, callee = line.split("->")
            if is_same_signature(callee, signature):
                caller_signature_set.add(caller.strip().strip("<>"))

    os.makedirs(os.path.dirname(cache_file_path), exist_ok=True)
    if os.path.exists(cache_file_path):
        with open(cache_file_path, "r") as f:
            cache_file = json.load(f)
    else:
        cache_file = {}

    cache_file[signature] = list(caller_signature_set)

    with open(cache_file_path, "w") as f:
        json.dump(cache_file, f, indent=4)

    return caller_signature_set
