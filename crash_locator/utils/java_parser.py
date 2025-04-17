from tree_sitter import Language, Parser
import tree_sitter_java
from pathlib import Path
from crash_locator.config import Config
from crash_locator.my_types import MethodSignature
from crash_locator.exceptions import (
    MultipleMethodsCodeError,
    NoMethodFoundCodeError,
    MethodFileNotFoundException,
)

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)


def get_application_code(
    apk_name: str,
    method_signature: MethodSignature,
) -> str:
    application_code_path = Config.APPLICATION_CODE_PATH(apk_name)
    return _get_method_code_in_file(
        application_code_path / method_signature.into_path(),
        method_signature.method_name,
        method_signature.return_type.split(".")[-1]
        if method_signature.return_type
        else None,
        [param.split(".")[-1] for param in method_signature.parameters]
        if method_signature.parameters
        else None,
    )


def _get_method_code_in_file(
    file_path: Path,
    method_name: str,
    return_type: str | None = None,
    arguments: list[str] | None = None,
) -> str:
    if not file_path.exists():
        raise MethodFileNotFoundException()

    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()
    tree = parser.parse(bytes(source_code, "utf8"))

    if return_type is not None:
        return_type_query = f'(_) @type (#eq? @type "{return_type}") .'
    if arguments is not None:
        argument_query = " . ".join(
            [
                f"""
            (
                formal_parameter
                . (_) @para (#eq? @para "{argument}")
            )
        """
                for argument in arguments
            ]
        )
        argument_query = f". {argument_query} ."

    query_string = f"""
    (
        method_declaration
        {return_type_query if return_type else ""}
        (identifier) @name (#eq? @name "{method_name}")
        (formal_parameters
            {argument_query if arguments else ""}
        )
    ) @method"""

    query = JAVA_LANGUAGE.query(query_string)
    captures = query.captures(tree.root_node)

    method = captures.get("method")
    if method is None:
        raise NoMethodFoundCodeError()
    elif len(method) > 1:
        raise MultipleMethodsCodeError()
    else:
        method = method[0]

    return method.text.decode("utf8")
