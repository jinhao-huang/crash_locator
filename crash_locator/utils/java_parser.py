from tree_sitter import Language, Parser, Node
from typing import Callable
import tree_sitter_java
from pathlib import Path
from crash_locator.config import config
from crash_locator.my_types import (
    MethodSignature,
    PackageType,
    Candidate,
    ClassSignature,
)
from crash_locator.exceptions import (
    MultipleMethodsCodeError,
    NoMethodFoundCodeError,
    MethodFileNotFoundException,
    UnknownException,
)
from crash_locator.utils.tree_sitter_helper import (
    get_parent,
    get_child,
    get_type_child,
    find_ancestor_by_type,
)
import logging

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)

logger = logging.getLogger(__name__)


def get_application_code(
    apk_name: str,
    candidate: Candidate,
) -> str:
    """Get the application code for a given method signature.
    Recursively search the method by the extend hierarchy.

    Raises:
        ValueError: The code is not in the application code directory.
        NoMethodFoundCodeError: No method found in the file.
        MultipleMethodsCodeError: Multiple methods found in the file.
    """
    if len(candidate.extend_hierarchy) == 0:
        extend_hierarchy = [
            ClassSignature(
                package_name=candidate.signature.package_name,
                class_name=candidate.signature.class_name,
                inner_class=candidate.signature.inner_class,
            )
        ]
    else:
        extend_hierarchy = candidate.extend_hierarchy

    for class_signature in extend_hierarchy:
        method_signature = MethodSignature(
            package_name=class_signature.package_name,
            class_name=class_signature.class_name,
            inner_class=class_signature.inner_class,
            method_name=candidate.signature.method_name,
            parameters=candidate.signature.parameters,
            return_type=candidate.signature.return_type,
        )
        if PackageType.get_package_type(method_signature) != PackageType.APPLICATION:
            raise ValueError(f"The code is not in the application code directory.")
        try:
            return _get_method_code_in_file(
                config.application_code_dir(apk_name) / method_signature.into_path(),
                method_signature,
            )
        except NoMethodFoundCodeError:
            continue

    raise NoMethodFoundCodeError()


def _get_method_code_in_file(
    file_path: Path,
    method_signature: MethodSignature,
) -> str:
    logger.debug(f"Getting method code in file: {file_path}")
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
            _class_name_filter,
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


def _is_anonymous_class(method_signature: MethodSignature) -> bool:
    return method_signature.class_list()[-1].isdigit()


def _check_anonymous_class(
    class_body_node: Node, method_signature: MethodSignature
) -> bool:
    line_comment = get_child(class_body_node, "line_comment")
    if line_comment is None:
        return False
    text = line_comment.text.decode("utf8")
    full_class_text = f"// from class: {method_signature.full_class_name()}"
    return text == full_class_text


def _anonymous_class_filter(
    methods: list[Node], method_signature: MethodSignature
) -> list[Node]:
    inner_class = method_signature.inner_class
    if inner_class is None:
        return methods
    if not _is_anonymous_class(method_signature):
        return methods

    retained_methods = []
    for method in methods:
        class_body = get_parent(method, "class_body")
        if class_body is None:
            continue
        if _check_anonymous_class(class_body, method_signature):
            retained_methods.append(method)

    return retained_methods


def _class_name_filter(
    methods: list[Node],
    method_signature: MethodSignature,
) -> list[Node]:
    class_list = method_signature.class_list()

    for class_name in reversed(class_list):
        if _is_anonymous_class(method_signature):
            class_list.pop()
        else:
            break

    retained_methods = []
    for method in methods:
        cursor_node = method
        for cursor_class in reversed(class_list):
            cursor_node = find_ancestor_by_type(cursor_node, "class_declaration")
            if cursor_node is None:
                break
            identifier = get_child(cursor_node, "identifier")
            if identifier is None:
                break
            if identifier.text.decode("utf8") != cursor_class:
                break
        else:
            retained_methods.append(method)

    return retained_methods
