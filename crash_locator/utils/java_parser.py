from tree_sitter import Language, Parser
import tree_sitter_java
from pathlib import Path

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)


class MultipleMethodsError(Exception):
    def __init__(self, message="Multiple methods found with the same name."):
        self.message = message


def get_method_code(file_path: Path, method_name: str, return_type: str = None,  arguments: list[str] = None) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()
    tree = parser.parse(bytes(source_code, "utf8"))

    if return_type is not None:
        return_type_query = f'(_) @type (#eq? @type "{return_type}") .'
    if arguments is not None:
        argument_query = " . ".join([f"""
            (
                formal_parameter
                . (_) @para (#eq? @para "{argument}")
            )
        """ for argument in arguments])
        argument_query = f". {argument_query} ."

    query_string = f"""
    (
        method_declaration
        {return_type_query if return_type else ""}
        (identifier) @name (#eq? @name "{method_name}")
        (formal_parameters
            {argument_query if arguments else ""}
        )
    ) @method
    """

    query = JAVA_LANGUAGE.query(query_string)
    captures = query.captures(tree.root_node)

    method = captures["method"]
    if len(method) > 1:
        raise MultipleMethodsError()
    else:
        method = method[0]

    return method.text.decode("utf8")
