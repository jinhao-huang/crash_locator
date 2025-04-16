import re
import logging
from crash_locator.exceptions import InvalidSignatureException

logger = logging.getLogger(__name__)


def parse_signature(method_signature):
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

        return (
            package_name,
            class_name,
            inner_class,
            return_type,
            method_name,
            parameters,
        )
    elif match2:
        package_name, class_name, inner_class, method_name = match2.groups()
        if inner_class:
            inner_class = inner_class.strip("$")
        return package_name, class_name, inner_class, None, method_name, None
    else:
        raise InvalidSignatureException(f"Invalid signature: {method_signature}")


def is_same_signature(signature1, signature2):
    if signature1 == signature2:
        return True
    if signature1.strip().strip("<>") == signature2.strip().strip("<>"):
        return True
    return False


def parse_field_signature(field_signature):
    """
    Example Field Signature:

        1. android.view.ViewRoot: java.lang.Thread mThread
        1. android.view.ViewRoot$InnerClass: java.lang.Thread mThread
    """
    field_signature = field_signature.strip().strip("<>")
    pattern = r"(\S+)\.(\w+)(\$\S+)?: (\S+) (\w+)"
    match = re.match(pattern, field_signature)
    if match:
        package_name, class_name, inner_class, type_name, field_name = match.groups()
        if inner_class:
            inner_class = inner_class.strip("$")
        return package_name, class_name, inner_class, type_name, field_name
    else:
        raise Exception(f"Invalid signature: {field_signature}")
