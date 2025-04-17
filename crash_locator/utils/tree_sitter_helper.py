from tree_sitter import Node
from crash_locator.exceptions import (
    ParentTypeNotMatchException,
    ChildNotFoundException,
    MultipleChildrenFoundException,
)


def get_parent(node: Node, parent_type: str) -> Node | None:
    parent = node.parent
    if parent is not None and parent.type != parent_type:
        raise ParentTypeNotMatchException()

    return parent


def get_child(node: Node, child_type: str) -> Node | None:
    children = node.named_children

    children_candidates = []
    for child in children:
        if child.type == child_type:
            children_candidates.append(child)

    if len(children_candidates) == 0:
        raise ChildNotFoundException()
    elif len(children_candidates) > 1:
        raise MultipleChildrenFoundException()
    return children_candidates[0]
