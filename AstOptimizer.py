from __future__ import annotations

from typing import Optional, Any
from SimpleJavaParser.SimpleJavaParser import ASTNode


class AstOptimizer:
    """
    - рекурсивно обходит дерево AST;
    - упрощает выражения (BinaryOp, PrefixOp, Ternary) там, где это
      гарантированно не меняет семантику программы;
    - не удаляет операторы присваивания, вызовы методов и другие
      потенциально "опасные" конструкции;
    - не меняет порядок операторов.
    """

    def __init__(
        self,
        enable_constant_folding: bool = True,
        enable_simplify: bool = True,
    ) -> None:
        self.enable_constant_folding = enable_constant_folding
        self.enable_simplify = enable_simplify

    # ---------------- публичный API ----------------

    def optimize(self, root: Optional[ASTNode]) -> Optional[ASTNode]:
        if root is None:
            return None
        return self._optimize_node(root)

    # ---------------- базовый обход ----------------

    def _optimize_node(self, node: ASTNode) -> ASTNode:
        """
        Сначала оптимизируются дочерние узлы, 
        затем применяются локальные правила к самому узлу.
        """
        if isinstance(node.value, ASTNode):
            node.value = self._optimize_node(node.value)

        new_children = []
        for ch in node.children or []:
            if isinstance(ch, ASTNode):
                new_children.append(self._optimize_node(ch))
            else:
                new_children.append(ch)
        node.children = new_children

        t = getattr(node, "type", None)

        if t == "BinaryOp":
            if self.enable_constant_folding:
                folded = self._try_constant_fold_binary(node)
                if folded is not None:
                    return folded
            if self.enable_simplify:
                return self._simplify_binary(node)

        if t == "PrefixOp" and self.enable_constant_folding:
            folded = self._try_constant_fold_prefix(node)
            if folded is not None:
                return folded

        if t == "Ternary" and self.enable_constant_folding:
            folded = self._try_constant_fold_ternary(node)
            if folded is not None:
                return folded

        return node

    # ---------------- свёртка констант ----------------

    def _try_constant_fold_binary(self, node: ASTNode) -> Optional[ASTNode]:
        """
        BinaryOp с двумя литеральными операндами -> один Literal
        """
        if len(node.children) != 2:
            return None
        left, right = node.children
        if not (isinstance(left, ASTNode) and isinstance(right, ASTNode)):
            return None
        if left.type != "Literal" or right.type != "Literal":
            return None

        op = node.value
        try:
            l_val = self._literal_to_value(left.value)
            r_val = self._literal_to_value(right.value)
        except Exception:
            return None

        if l_val is _NoValue or r_val is _NoValue:
            return None

        try:
            result: Any

            if op in {"ADD", "SUB", "MUL", "DIV", "MOD"}:
                if op == "ADD" and isinstance(l_val, str) and isinstance(r_val, str):
                    result = l_val + r_val
                else:
                    if not isinstance(l_val, (int, float)) or not isinstance(r_val, (int, float)):
                        return None
                    if op == "ADD":
                        result = l_val + r_val
                    elif op == "SUB":
                        result = l_val - r_val
                    elif op == "MUL":
                        result = l_val * r_val
                    elif op == "DIV":
                        if r_val == 0:
                            return None
                        result = l_val / r_val
                    elif op == "MOD":
                        if r_val == 0:
                            return None
                        result = l_val % r_val
                    else:
                        return None

            elif op in {"GT", "LT", "GE", "LE", "EQUAL", "NOTEQUAL"}:
                if op == "GT":
                    result = l_val > r_val
                elif op == "LT":
                    result = l_val < r_val
                elif op == "GE":
                    result = l_val >= r_val
                elif op == "LE":
                    result = l_val <= r_val
                elif op == "EQUAL":
                    result = l_val == r_val
                elif op == "NOTEQUAL":
                    result = l_val != r_val
                else:
                    return None

            elif op in {"AND", "OR"}:
                if not isinstance(l_val, bool) or not isinstance(r_val, bool):
                    return None
                if op == "AND":
                    result = l_val and r_val
                else:
                    result = l_val or r_val

            elif op in {"BITAND", "BITOR", "CARET", "LSHIFT", "RSHIFT", "URSHIFT"}:
                if not isinstance(l_val, int) or not isinstance(r_val, int):
                    return None
                if op == "BITAND":
                    result = l_val & r_val
                elif op == "BITOR":
                    result = l_val | r_val
                elif op == "CARET":
                    result = l_val ^ r_val
                elif op in {"LSHIFT", "RSHIFT", "URSHIFT"}:
                    result = l_val >> r_val
                else:
                    return None
            else:
                return None

            lit_text = self._value_to_literal(result)
            return ASTNode("Literal", lit_text, token=node.token)

        except Exception:
            return None

    def _try_constant_fold_prefix(self, node: ASTNode) -> Optional[ASTNode]:
        """
        Свёртка унарных операций над литералами
        """
        if not node.children:
            return None
        base = node.children[0]
        if not isinstance(base, ASTNode) or base.type != "Literal":
            return None

        try:
            val = self._literal_to_value(base.value)
        except Exception:
            return None
        if val is _NoValue:
            return None

        op = node.value
        try:
            if op == "ADD":
                result = +val
            elif op == "SUB":
                result = -val
            elif op == "TILDE":
                if not isinstance(val, int):
                    return None
                result = ~val
            elif op == "BANG":
                if not isinstance(val, bool):
                    return None
                result = not val
            else:
                return None
            lit_text = self._value_to_literal(result)
            return ASTNode("Literal", lit_text, token=node.token)
        except Exception:
            return None

    def _try_constant_fold_ternary(self, node: ASTNode) -> Optional[ASTNode]:
        """
        cond ? a : b  ->  a  (если cond == true)
        cond ? a : b  ->  b  (если cond == false)
        """
        if len(node.children) != 3:
            return None
        cond, texpr, fexpr = node.children
        if not isinstance(cond, ASTNode) or cond.type != "Literal":
            return None
        try:
            val = self._literal_to_value(cond.value)
        except Exception:
            return None
        if not isinstance(val, bool):
            return None
        return texpr if val else fexpr

    # ---------------- упрощение выражений ----------------

    def _simplify_binary(self, node: ASTNode) -> ASTNode:
        if len(node.children) != 2:
            return node
        left, right = node.children
        op = node.value

        # +0, -0, *1
        # x + 0 -> x
        if op == "ADD":
            if self._is_int_literal_with_value(left, 0):
                return right
            if self._is_int_literal_with_value(right, 0):
                return left

        # x - 0 -> x
        if op == "SUB":
            if self._is_int_literal_with_value(right, 0):
                return left

        # x * 1 -> x
        if op == "MUL":
            if self._is_int_literal_with_value(left, 1):
                return right
            if self._is_int_literal_with_value(right, 1):
                return left

        if op in {"AND", "OR"} and isinstance(left, ASTNode) and left.type == "Literal":
            try:
                l_val = self._literal_to_value(left.value)
            except Exception:
                l_val = _NoValue
            if isinstance(l_val, bool):
                if op == "AND":
                    # true && X -> X
                    if l_val is True:
                        return right
                    # false && X -> false
                    if l_val is False:
                        return left
                elif op == "OR":
                    # true || X -> true
                    if l_val is True:
                        return left
                    # false || X -> X
                    if l_val is False:
                        return right

        return node

    # ---------------- вспомогательные методы ----------------

    def _is_int_literal_with_value(self, node: Any, target: int) -> bool:
        if not isinstance(node, ASTNode) or node.type != "Literal":
            return False
        try:
            val = self._literal_to_value(node.value)
        except Exception:
            return False
        return isinstance(val, int) and val == target

    def _literal_to_value(self, text: Any) -> Any:
        if text is None:
            return _NoValue
        s = str(text).strip()
        if not s:
            return _NoValue

        ls = s.lower()
        if ls == "null":
            return None
        if ls == "true":
            return True
        if ls == "false":
            return False

        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            inner = s[1:-1]
            return inner

        stripped = s
        while stripped and stripped[-1] in "lLfFdD":
            stripped = stripped[:-1]
        stripped = stripped.replace("_", "")

        try:
            iv = int(stripped, 0)
            return iv
        except Exception:
            pass

        try:
            fv = float(stripped)
            return fv
        except Exception:
            pass

        return _NoValue

    def _value_to_literal(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(value)
        if isinstance(value, str):
            esc = value.replace('"', '\\"')
            return f'"{esc}"'

        esc = str(value).replace('"', '\\"')
        return f'"{esc}"'


class _NoValueType:
    """Маркер невозможности разбора литерала."""

    def __repr__(self) -> str:
        return "<NoValue>"


_NoValue = _NoValueType()
