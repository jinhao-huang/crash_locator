from tree_sitter import Language, Parser, Node
from typing import Callable
import tree_sitter_java
from pathlib import Path
from crash_locator.config import config
from crash_locator.my_types import MethodSignature
from crash_locator.exceptions import (
    MultipleMethodsCodeError,
    NoMethodFoundCodeError,
    MethodFileNotFoundException,
    UnknownException,
)
from crash_locator.utils.tree_sitter_helper import get_parent, get_child, get_type_child
import logging

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)

logger = logging.getLogger(__name__)


def get_application_code(
    apk_name: str,
    method_signature: MethodSignature,
) -> str:
    """Get the application code for a given method signature.

    Raises:
        NoMethodFoundCodeError: No method found in the file.
        MultipleMethodsCodeError: Multiple methods found in the file.
    """
    application_code_path = (
        config.application_code_path(apk_name) / method_signature.into_path()
    )
    logger.debug(f"Application code path: {application_code_path}")
    return _get_method_code_in_file(application_code_path, method_signature)


def _get_method_code_in_file(
    file_path: Path,
    method_signature: MethodSignature,
) -> str:
    method_name = method_signature.method_name

    if not file_path.exists():
        raise MethodFileNotFoundException()

    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()
    tree = parser.parse(bytes(source_code, "utf8"))

    query_string = f"""
    (
        method_declaration
        (identifier) @name (#eq? @name "{method_name}")
        (formal_parameters)
    ) @method"""

    query = JAVA_LANGUAGE.query(query_string)
    captures = query.captures(tree.root_node)

    method = _filter_methods(
        captures.get("method"),
        method_signature,
        [
            _method_return_type_filter,
            _methods_parameters_filter,
            _anonymous_class_filter,
        ],
    )
    if method is None or len(method) == 0:
        raise NoMethodFoundCodeError()
    elif len(method) > 1:
        raise MultipleMethodsCodeError()
    else:
        method = method[0]

    return method.text.decode("utf8")


def _filter_methods(
    methods: list[Node] | None,
    method_signature: MethodSignature,
    filter_functions: list[Callable[[list[Node], MethodSignature], list[Node]]],
) -> list[Node]:
    if methods is None:
        return []

    for filter_function in filter_functions:
        methods = filter_function(methods, method_signature)
        if len(methods) == 0:
            return []
    return methods


def _type_strip(type_str: list[str] | str | None) -> list[str] | str | None:
    match type_str:
        case list():
            return [_type_strip(t) for t in type_str]
        case str():
            return type_str.split(".")[-1].split("$")[-1]
        case None:
            return None
        case _:
            raise UnknownException()


def _method_return_type_filter(
    methods: list[Node],
    method_signature: MethodSignature,
) -> list[Node]:
    return_type = _type_strip(method_signature.return_type)
    if return_type is None:
        return methods

    retained_methods = []
    for method in methods:
        return_type_node = get_type_child(method)
        if return_type_node is None:
            raise UnknownException()

        if return_type_node.text.decode("utf8") != return_type:
            continue

        retained_methods.append(method)

    return retained_methods


def _methods_parameters_filter(
    methods: list[Node],
    method_signature: MethodSignature,
) -> list[Node]:
    parameters = _type_strip(method_signature.parameters)

    if parameters is None:
        return methods

    filtered_methods = []
    for method in methods:
        formal_parameters = get_child(method, "formal_parameters")
        if formal_parameters is None:
            raise UnknownException()

        if formal_parameters.named_child_count != len(parameters):
            continue

        matched = True
        for parameter, expected_parameter in zip(
            formal_parameters.named_children, parameters
        ):
            type_identifier = get_type_child(parameter)
            if type_identifier is None:
                raise UnknownException()

            if type_identifier.text.decode("utf8") != expected_parameter:
                matched = False
                break
        if matched:
            filtered_methods.append(method)

    return filtered_methods


def _anonymous_class_filter(
    methods: list[Node], method_signature: MethodSignature
) -> list[Node]:
    inner_class = method_signature.inner_class
    if inner_class is None:
        return methods
    if not inner_class.split("$")[-1].isdigit():
        return methods

    retained_methods = []
    for method in methods:
        class_body = get_parent(method, "class_body")
        if class_body is None:
            continue
        line_comment = get_child(class_body, "line_comment")
        if (
            line_comment is not None
            and method_signature.full_class_name() in line_comment.text.decode("utf8")
        ):
            retained_methods.append(method)

    return retained_methods
