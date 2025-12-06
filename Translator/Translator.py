import re
from typing import Optional, Any, List, Tuple

INDENT_STR = "    "

# ---------------- type mapping helpers ----------------

def map_java_type_to_py(java_type: Optional[str]) -> str:
    if not java_type:
        return "Any"

    jt = str(java_type).strip()
    # "List < String >" -> "List<String>"
    jt = re.sub(r"\s*<\s*", "<", jt)
    jt = re.sub(r"\s*>\s*", ">", jt)
    jt = re.sub(r"\s*,\s*", ",", jt)

    array_depth = 0
    while jt.endswith("[]"):
        array_depth += 1
        jt = jt[:-2]

    base_map = {
        "byte": "int", "short": "int", "int": "int", "integer": "int", "long": "int",
        "float": "float", "double": "float",
        "boolean": "bool", "bool": "bool",
        "char": "str", "character": "str",
        "string": "str", "object": "object",
        "void": "None",
        "decimal_literal": "int",
        "float_literal": "float",
        "hex_float_literal": "float",
        "bool_literal": "bool",
        "string_literal": "str",
        "text_block": "str",
    }

    def split_top_level(s: str, sep: str = ","):
        out, cur, depth = [], [], 0
        for ch in s:
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
            if ch == sep and depth == 0:
                out.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        if cur:
            out.append("".join(cur).strip())
        return out

    def parse_generic(s: str):
        if "<" not in s or not s.endswith(">"):
            return s, None
        base = s[:s.index("<")]
        args_part = s[s.index("<")+1:-1]
        return base, split_top_level(args_part, ",")

    def to_py(s: str) -> str:
        s = s.strip()
        base, args = parse_generic(s)
        b = base.lower()
        if args is None:
            if b in base_map:
                return base_map[b]
            if b in ("list", "arraylist"):
                return "list[Any]"
            if b in ("set", "hashset"):
                return "set[Any]"
            if b in ("map", "hashmap"):
                return "dict[Any, Any]"
            if b == "optional":
                return "Optional[Any]"
            return base
        # generic args
        mapped = [to_py(a) for a in args]
        if b in ("list", "arraylist"):
            return f"list[{mapped[0] if mapped else 'Any'}]"
        if b in ("set", "hashset"):
            return f"set[{mapped[0] if mapped else 'Any'}]"
        if b in ("map", "hashmap"):
            k = mapped[0] if len(mapped) > 0 else "Any"
            v = mapped[1] if len(mapped) > 1 else "Any"
            return f"dict[{k}, {v}]"
        if b == "optional":
            return f"Optional[{mapped[0] if mapped else 'Any'}]"
        return base

    py = to_py(jt)
    for _ in range(array_depth):
        py = f"list[{py}]"
    return py


def default_for_type(py_type: Optional[str]) -> str:
    if not py_type:
        return "None"
    if py_type.startswith("list["):
        return "[]"
    if py_type == "int":
        return "0"
    if py_type == "float":
        return "0.0"
    if py_type == "bool":
        return "False"
    if py_type == "str":
        return '""'
    if py_type == "None":
        return "None"
    return "None"


# ---------------- translator ----------------

class Translator:
    def __init__(self, indent_str: str = INDENT_STR):
        self.indent_str = indent_str
        self.indent_level = 0
        self._in_constructor = False

    def indent(self) -> str:
        return self.indent_str * self.indent_level

    def _format_literal_token(self, raw_value) -> str:
        if raw_value is None:
            return '""'
        s = str(raw_value)
        ls = s.lower()
        if ls == "null":  return "None"
        if ls == "true":  return "True"
        if ls == "false": return "False"
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s
        try:
            int(s)
            return s
        except Exception:
            try:
                float(s)
                return s
            except Exception:
                pass
        esc = s.replace('"', '\\"')
        return f'"{esc}"'

    def translate(self, ast) -> str:
        return self._translate_node(ast)

    # ---------- центральный диспетчер ----------

    def _translate_node(self, node):
        if node is None:
            return ""
        dispatch = {
            "CompilationUnit": self._trans_compilation_unit,
            "ClassDecl": self._trans_class_decl,
            "Modifiers": self._trans_modifiers,
            "MethodDecl": self._trans_method_decl,
            "ConstructorDecl": self._trans_constructor_decl,
            "Param": self._trans_param,
            "FieldDecl": self._trans_field_decl,
            "Init": self._trans_init_wrapper,
            "Block": self._trans_block,
            "IfStatement": self._trans_if_statement,
            "Then": self._trans_then,
            "Else": self._trans_else,
            "Assign": self._trans_assign,
            "ExprStmt": self._trans_expr_stmt,
            "Return": self._trans_return,
            "Call": self._trans_call,
            "Member": self._trans_member,
            "Identifier": self._trans_identifier,
            "Literal": self._trans_literal,
            "BinaryOp": self._trans_binaryop,
            "Unknown": self._trans_unknown,
            "ForStatement": self._trans_for_statement,
            "WhileStatement": self._trans_while_statement,
            "DoWhileStatement": self._trans_do_while_statement,
            "Break": self._trans_break,
            "Continue": self._trans_continue,
            "SwitchStatement": self._trans_switch_statement,
            "CaseLabel": self._trans_case_label,
            "DefaultLabel": self._trans_default_label,
            "PostfixOp": self._trans_postfixop,
            "PrefixOp": self._trans_prefixop,
            "TryStatement": self._trans_try_statement,
            "Base": lambda n: "",
        }
        fn = dispatch.get(node.type, None)
        if fn:
            return fn(node)
        out_lines = []
        for c in node.children:
            if c is None:
                continue
            if isinstance(c, str):
                out_lines.append(self.indent() + c)
            else:
                out_lines.append(self._translate_node(c))
        return "\n".join([l for l in out_lines if l])

    # ---------- верхний уровень ----------

    def _trans_compilation_unit(self, node):
        parts = []
        for child in node.children:
            s = self._translate_node(child)
            if s:
                parts.append(s)
        return "\n\n".join(parts)

    # -- утилиты для классов/полей/конструкторов --

    def _split_fields_ctors_others(self, children):
        fields, ctors, others = [], [], []
        for ch in children:
            t = getattr(ch, "type", None)
            if t == "FieldDecl":
                fields.append(ch)
            elif t == "Block":
                if all(getattr(c, "type", None) == "FieldDecl" for c in (ch.children or [])):
                    fields.extend(ch.children or [])
                else:
                    others.append(ch)
            elif t == "ConstructorDecl":
                ctors.append(ch)
            else:
                others.append(ch)
        return fields, ctors, others

    def _split_static_instance_fields(self, fields):
        static_fields, instance_fields = [], []
        for f in fields:
            mods = None
            for c in (f.children or []):
                if getattr(c, "type", None) == "Modifiers":
                    mods = (c.value or "")
                    break
            if mods and "STATIC" in mods:
                static_fields.append(f)
            else:
                instance_fields.append(f)
        return static_fields, instance_fields

    def _field_as_instance_assignment(self, field_node):
        """
        FieldDecl("T name", [Init(expr)?]) -> "self.name: pyT = <rhs>".
        """
        parts = (field_node.value or "").split()
        name = parts[-1] if parts else "var"
        declared_type = " ".join(parts[:-1]) if len(parts) >= 2 else None
        py_type = map_java_type_to_py(declared_type) if declared_type else None

        init_node = None
        for c in (field_node.children or []):
            if getattr(c, "type", None) == "Init" and c.children:
                init_node = c.children[0]
                break

        if init_node is not None:
            rhs = self._expr_to_source(init_node)
            if not rhs:
                rhs = default_for_type(py_type) if py_type else "None"
        else:
            rhs = default_for_type(py_type) if py_type else "None"

        ann = f": {py_type} " if py_type and py_type != "None" else ""
        return f"self.{name}{ann}= {rhs}"

    def _field_is_assigned_in_body(self, field_node, body_lines: List[str]) -> bool:
        name = (field_node.value or "").split()[-1] if field_node.value else None
        if not name:
            return False
        needle = f"self.{name} ="
        return any(needle in (ln or "") for ln in (body_lines or []))

    def _ctor_params_info(self, ctor_node) -> List[Tuple[str, str]]:
        params = []
        for c in (ctor_node.children or []):
            if getattr(c, "type", None) == "Param":
                pv = c.value.strip() if getattr(c, "value", None) else ""
                pp = pv.split()
                if len(pp) >= 2:
                    p_type_java = " ".join(pp[:-1])
                    p_name = pp[-1]
                    p_py = map_java_type_to_py(p_type_java)
                    params.append((p_name, p_py))
                else:
                    name = pp[-1] if pp else "arg"
                    params.append((name, "Any"))
        return params

    def _render_init_with_injection(self, header: str, body_src: str, instance_fields) -> str:
        lines = body_src.splitlines()
        if not lines:
            lines = [f"{self.indent()}def __init__(self):", self.indent() + self.indent_str + "pass"]

        body_indent = None
        first_body_idx = None
        for idx, ln in enumerate(lines[1:], start=1):
            if ln.strip():
                body_indent = ln[:len(ln) - len(ln.lstrip())]
                first_body_idx = idx
                break
        if body_indent is None:
            body_indent = self.indent() + self.indent_str

        is_delegating = False
        first_stmt = lines[first_body_idx].strip() if first_body_idx is not None else ""
        if first_stmt.startswith("self.__init__(") or first_stmt.startswith("super().__init__("):
            is_delegating = True

        if not is_delegating and first_body_idx is not None and lines[first_body_idx].strip() == "pass":
            del lines[first_body_idx]

        if not is_delegating and instance_fields:
            injected = [
                body_indent + self._field_as_instance_assignment(f)
                for f in instance_fields
                if not self._field_is_assigned_in_body(f, lines[first_body_idx:] if first_body_idx is not None else [])
            ]
            lines = [lines[0]] + injected + lines[1:]

        lines[0] = header
        return "\n".join(lines)

    def _merge_constructors_to_single_init(self, class_indent: str, ctors, instance_fields):
        primary = max(ctors, key=lambda c: len([x for x in (c.children or []) if getattr(x, "type", None) == "Param"]))
        primary_params = self._ctor_params_info(primary)
        primary_header, primary_body = self._render_ctor_string(primary)

        arities = sorted({
            len([x for x in (c.children or []) if getattr(x, "type", None) == "Param"])
            for c in ctors
        })
        min_arity = arities[0] if arities else len(primary_params)

        def_header = self._build_init_header_from_params(primary_params, min_arity, class_indent)

        return self._render_init_with_injection(def_header, primary_body, instance_fields)

    def _build_init_header_from_params(self, params: List[Tuple[str, str]], min_arity: int, class_indent: str) -> str:
        items = []
        for idx, (name, ptype) in enumerate(params):
            if idx >= min_arity:
                default = default_for_type(ptype)
                items.append(f"{name}: {ptype} = {default}" if ptype and ptype != "None" else f"{name} = {default}")
            else:
                items.append(f"{name}: {ptype}" if ptype and ptype != "None" else name)
        param_list = ("self" + (", " + ", ".join(items) if items else ""))
        return f"{class_indent}def __init__({param_list}):"

    def _render_ctor_string(self, ctor_node) -> Tuple[str, str]:
        children = list(ctor_node.children or [])
        if children and getattr(children[0], "type", None) == "Modifiers":
            children = children[1:]
        params = [c for c in children if getattr(c, "type", None) == "Param"]
        body_nodes = [c for c in children if getattr(c, "type", None) != "Param"]

        param_parts = []
        for p in params:
            pv = p.value.strip() if getattr(p, "value", None) else ""
            pp = pv.split()
            if len(pp) >= 2:
                p_type_java = " ".join(pp[:-1])
                p_name = pp[-1]
                p_py = map_java_type_to_py(p_type_java)
                param_parts.append(f"{p_name}: {p_py}")
            else:
                param_parts.append(pp[-1] if pp else "arg")

        header = f"{self.indent()}def __init__(self{', ' if param_parts else ''}{', '.join(param_parts)}):"

        self._in_constructor = True
        self.indent_level += 1
        body_lines = []
        if not body_nodes:
            body_lines.append(self.indent() + "pass")
        else:
            for b in body_nodes:
                rendered = self._translate_node(b)
                if rendered:
                    body_lines.extend(rendered.splitlines())
        self.indent_level -= 1
        self._in_constructor = False

        return header, f"{header}\n" + "\n".join(body_lines)

    # ---------- класс ----------

    def _trans_class_decl(self, node):
        class_name = node.value or ""
        children = list(node.children or [])

        if children and getattr(children[0], "type", None) == "Modifiers":
            children = children[1:]

        bases = []
        if children and getattr(children[0], "type", None) == "Base":
            base_val = children[0].value or ""
            bases = [b.strip() for b in base_val.split(",") if b.strip()]
            children = children[1:]

        header = f"class {class_name}" + (f"({', '.join(bases)})" if bases else "") + ":"

        fields, ctors, others = self._split_fields_ctors_others(children)
        static_fields, instance_fields = self._split_static_instance_fields(fields)

        if not ctors and not others and not static_fields and not instance_fields:
            return header + "\n" + self.indent_str + "pass"

        body_chunks: List[str] = []
        self.indent_level += 1
        class_indent = self.indent()

        for f in static_fields:
            body_chunks.append(self._translate_node(f))

        if ctors:
            if len(ctors) == 1:
                _, ctor_text = self._render_ctor_string(ctors[0])
                init_text = self._render_init_with_injection(ctor_text.splitlines()[0], ctor_text, instance_fields)
                body_chunks.append(init_text)
            else:
                init_text = self._merge_constructors_to_single_init(class_indent, ctors, instance_fields)
                body_chunks.append(init_text)
        else:
            if instance_fields:
                lines = [f"{class_indent}def __init__(self):"]
                inner_indent = class_indent + self.indent_str
                for f in instance_fields:
                    lines.append(inner_indent + self._field_as_instance_assignment(f))
                body_chunks.append("\n".join(lines))

        for o in others:
            body_chunks.append(self._translate_node(o))

        self.indent_level -= 1
        return header + "\n" + "\n".join(body_chunks)

    def _trans_modifiers(self, node):
        return f"# modifiers: {node.value}"

    # ---------- fields ----------

    def _trans_field_decl(self, node):
        val = node.value or ""
        parts = (val or "").split()
        if len(parts) >= 2:
            declared_type = " ".join(parts[:-1])
            name = parts[-1]
        elif len(parts) == 1:
            declared_type, name = parts[0], "var"
        else:
            declared_type, name = None, "var"

        init_node = None
        for c in (node.children or []):
            if getattr(c, "type", None) == "Init" and c.children:
                init_node = c.children[0]
                break

        py_type = map_java_type_to_py(declared_type) if declared_type else None
        if init_node is not None:
            init_src = self._expr_to_source(init_node)
            if not init_src:
                init_src = default_for_type(py_type) if py_type else "None"
            if py_type and py_type != "None":
                return f"{self.indent()}{name}: {py_type} = {init_src}"
            return f"{self.indent()}{name} = {init_src}"

        default = default_for_type(py_type) if py_type else "None"
        if py_type and py_type != "None":
            return f"{self.indent()}{name}: {py_type} = {default}"
        return f"{self.indent()}{name} = {default}"

    def _trans_init_wrapper(self, node):
        if node.children:
            return self._expr_to_source(node.children[0])
        return ""

    # ---------- methods / ctors ----------

    def _trans_param(self, node):
        return node.value or ""

    def _trans_method_decl(self, node):
        children = list(node.children or [])
        modifiers = []
        if children and getattr(children[0], "type", None) == "Modifiers":
            modifiers = children[0].value.split(",") if children[0].value else []
            children = children[1:]
        params = [c for c in children if getattr(c, "type", None) == "Param"]
        body_nodes = [c for c in children if getattr(c, "type", None) != "Param"]

        ret_type = None
        method_name = None
        if node.value:
            parts = node.value.split()
            if len(parts) >= 2:
                ret_type = parts[0]
                method_name = parts[1]
            elif len(parts) == 1:
                method_name = parts[0]
        if not method_name:
            method_name = "method"
        is_static = any(m.strip().upper() == "STATIC" for m in modifiers)

        param_items = []
        for p in params:
            pv = p.value.strip() if getattr(p, "value", None) else ""
            pp = pv.split()
            if len(pp) >= 2:
                p_type_java = " ".join(pp[:-1])
                p_name = pp[-1]
                p_py = map_java_type_to_py(p_type_java)
                param_items.append(f"{p_name}: {p_py}")
            else:
                param_items.append(pp[-1] if pp else "arg")

        if not is_static:
            param_list = "self" + (", " + ", ".join(param_items) if param_items else "")
        else:
            param_list = ", ".join(param_items)

        ret_py = map_java_type_to_py(ret_type) if ret_type is not None else "None"
        header = f"def {method_name}({param_list}) -> {ret_py}:"

        result = []
        if is_static:
            result.append(f"{self.indent()}@staticmethod")
        result.append(f"{self.indent()}{header}")

        self.indent_level += 1
        if not body_nodes:
            result.append(self.indent() + "pass")
        else:
            for b in body_nodes:
                rendered = self._translate_node(b)
                if rendered:
                    result.append(rendered)
        self.indent_level -= 1
        return "\n".join(result)

    def _trans_constructor_decl(self, node):
        children = list(node.children or [])
        if children and getattr(children[0], "type", None) == "Modifiers":
            children = children[1:]
        params = [c for c in children if getattr(c, "type", None) == "Param"]
        body_nodes = [c for c in children if getattr(c, "type", None) != "Param"]

        param_parts = []
        for p in params:
            pv = p.value.strip() if getattr(p, "value", None) else ""
            pp = pv.split()
            if len(pp) >= 2:
                p_type_java = " ".join(pp[:-1])
                p_name = pp[-1]
                p_py = map_java_type_to_py(p_type_java)
                param_parts.append(f"{p_name}: {p_py}")
            else:
                param_parts.append(pp[-1] if pp else "arg")

        header = f"def __init__(self{', ' if param_parts else ''}{', '.join(param_parts)}):"

        self._in_constructor = True
        self.indent_level += 1
        body_lines = []
        if not body_nodes:
            body_lines.append(self.indent() + "pass")
        else:
            for b in body_nodes:
                rendered = self._translate_node(b)
                if rendered:
                    body_lines.extend(rendered.splitlines())
        self.indent_level -= 1
        self._in_constructor = False

        return f"{self.indent()}{header}\n" + "\n".join(body_lines)

    # ---------- blocks / statements ----------

    def _trans_block(self, node):
        if not node.children:
            return self.indent() + "pass"
        lines = []
        for stmt in node.children:
            rendered = self._translate_node(stmt)
            if rendered:
                for line in rendered.splitlines():
                    if line.startswith(self.indent()):
                        lines.append(line)
                    else:
                        lines.append(self.indent() + line)
        return "\n".join(lines)

    def _trans_if_statement(self, node):
        cond_src = self._expr_to_source(node.value)
        lines = [f"{self.indent()}if {cond_src}:"]
        then_node = node.children[0] if node.children else None
        self.indent_level += 1
        if then_node:
            for stmt in then_node.children:
                lines.append(self._translate_node(stmt))
        self.indent_level -= 1
        next_else = node.children[1] if len(node.children) > 1 else None
        while next_else:
            if next_else.type == "IfStatement":
                elif_cond = self._expr_to_source(next_else.value)
                lines.append(f"{self.indent()}elif {elif_cond}:")
                self.indent_level += 1
                then_of_else = next_else.children[0] if next_else.children else None
                if then_of_else:
                    for stmt in then_of_else.children:
                        lines.append(self._translate_node(stmt))
                self.indent_level -= 1
                next_else = next_else.children[1] if len(next_else.children) > 1 else None
            elif next_else.type == "Else":
                lines.append(f"{self.indent()}else:")
                self.indent_level += 1
                for stmt in next_else.children:
                    lines.append(self._translate_node(stmt))
                self.indent_level -= 1
                next_else = None
            else:
                lines.append(self._translate_node(next_else))
                next_else = None
        return "\n".join(lines)

    def _trans_then(self, node):
        return "\n".join(self._translate_node(c) for c in node.children if c)

    def _trans_else(self, node):
        return "\n".join(self._translate_node(c) for c in node.children if c)

    def _trans_try_statement(self, node):
        lines = []
        # try
        lines.append(f"{self.indent()}try:")
        self.indent_level += 1
        try_block = node.children[0] if node.children else None
        if try_block:
            for stmt in try_block.children:
                lines.append(self._translate_node(stmt))
        else:
            lines.append(self.indent() + "pass")
        self.indent_level -= 1

        # catches
        for ch in node.children[1:]:
            t = getattr(ch, "type", None)
            if t != "Catch":
                continue
            type_name, var_name = None, None
            if ch.value:
                parts = ch.value.split()
                if len(parts) == 1:
                    type_name = parts[0]
                elif len(parts) >= 2:
                    type_name = parts[0]
                    var_name = parts[1]
            type_name = type_name or "Exception"
            header = f"{self.indent()}except {type_name}"
            if var_name:
                header += f" as {var_name}"
            header += ":"
            lines.append(header)
            self.indent_level += 1
            if ch.children:
                for stmt in ch.children:
                    lines.append(self._translate_node(stmt))
            else:
                lines.append(self.indent() + "pass")
            self.indent_level -= 1

        # finally
        last = node.children[-1] if node.children else None
        if last and getattr(last, "type", None) == "Finally":
            lines.append(f"{self.indent()}finally:")
            self.indent_level += 1
            if last.children:
                for stmt in last.children:
                    lines.append(self._translate_node(stmt))
            else:
                lines.append(self.indent() + "pass")
            self.indent_level -= 1

        return "\n".join(lines)

    def _trans_return(self, node):
        if node.children:
            return f"{self.indent()}return {self._expr_to_source(node.children[0])}"
        return f"{self.indent()}return"

    def _trans_break(self, node):
        return f"{self.indent()}break"

    def _trans_continue(self, node):
        return f"{self.indent()}continue"

    def _trans_expr_stmt(self, node):
        if node.children:
            expr = node.children[0]
            expr_src = self._expr_to_source(expr)
            return "\n".join((self.indent() + line) for line in expr_src.splitlines())
        return f"{self.indent()}pass"

    def _trans_call(self, node):
        src = self._expr_to_source(node)
        return "\n".join(self.indent() + line for line in src.splitlines())

    def _trans_member(self, node):
        member_name = node.value
        base = node.children[0] if node.children else None
        base_src = self._expr_to_source(base)
        return f"{base_src}.{member_name}"

    def _trans_identifier(self, node):
        return node.value or ""

    def _trans_literal(self, node):
        return self._format_literal_token(node.value)

    def _trans_binaryop(self, node):
        return self._expr_to_source(node)

    def _trans_unknown(self, node):
        text = node.value if node.value is not None else ""
        return f"{self.indent()}# Unknown node: {text}"

    # ---------- assign helpers / for ----------

    def _trans_assign(self, node):
        if not node.children or len(node.children) < 2:
            return f"{self.indent()}# malformed assign"
        left = node.children[0]
        right = node.children[1]

        left_src_raw = self._expr_to_source(left)
        left_src = f"self.{left_src_raw}" if (self._in_constructor and getattr(left, "type", None) == "Identifier") else left_src_raw

        # x = x <op> y -> x <op>= y
        if getattr(right, "type", None) == "BinaryOp" and len(getattr(right, "children", []) or []) == 2:
            op = right.value
            r_left, r_right = right.children
            if getattr(r_left, "type", None) == getattr(left, "type", None) == "Identifier" and r_left.value == getattr(left, "value", None):
                op_map = {"ADD": "+=", "SUB": "-=", "MUL": "*=", "DIV": "/=", "MOD": "%=", "BITAND": "&=", "BITOR": "|=", "CARET": "^=", "LSHIFT": "<<=", "RSHIFT": ">>="}
                if op in op_map:
                    return f"{self.indent()}{left_src} {op_map[op]} {self._expr_to_source(r_right)}"

        right_src = self._expr_to_source(right)
        return f"{self.indent()}{left_src} = {right_src}"

    # --- for helpers ---

    def _get_for_init_info(self, init_node):
        if init_node is None:
            return None, None
        if getattr(init_node, "type", None) == "FieldDecl":
            parts = (init_node.value or "").split()
            var_name = parts[-1] if parts else None
            init_child = None
            for c in init_node.children:
                if c and getattr(c, "type", None) == "Init":
                    init_child = c.children[0] if c.children else None
                    break
            if init_child:
                return var_name, self._expr_to_source(init_child)
            return var_name, None
        if getattr(init_node, "type", None) == "Assign":
            left = init_node.children[0] if init_node.children else None
            right = init_node.children[1] if init_node.children else None
            if left and getattr(left, "type", None) == "Identifier":
                return left.value, self._expr_to_source(right)
        return None, None

    def _get_for_update_step(self, update_node, var_name):
        if update_node is None:
            return None
        if getattr(update_node, "type", None) in ("PostfixOp", "PrefixOp"):
            if update_node.value == "INC":
                return 1
            if update_node.value == "DEC":
                return -1
        if getattr(update_node, "type", None) == "BinaryOp":
            return self._expr_to_source(update_node)
        if getattr(update_node, "type", None) == "Assign":
            right = update_node.children[1] if update_node.children else None
            if getattr(right, "type", None) == "BinaryOp":
                op = right.value
                if op == "ADD":
                    try:
                        return int(right.children[1].value)
                    except Exception:
                        return self._expr_to_source(update_node)
                if op == "SUB":
                    try:
                        return -int(right.children[1].value)
                    except Exception:
                        return self._expr_to_source(update_node)
            return self._expr_to_source(update_node)
        return self._expr_to_source(update_node)

    def _get_for_condition_end(self, cond_node, var_name):
        if cond_node is None:
            return None, None
        if getattr(cond_node, "type", None) == "BinaryOp":
            left = cond_node.children[0]
            right = cond_node.children[1]
            op = cond_node.value
            left_name = left.value if getattr(left, "type", None) == "Identifier" else None
            if var_name is None or left_name == var_name:
                return self._expr_to_source(right), op
        return None, None

    def _trans_for_statement(self, node):
        children = node.children or []
        # for(init; cond; update)
        if len(children) == 4:
            init, condition, update, body = children
            var_name, start_src = self._get_for_init_info(init)
            end_src, cond_op = self._get_for_condition_end(condition, var_name)
            step = self._get_for_update_step(update, var_name)
            if var_name and end_src is not None:
                if cond_op == "LE":
                    end_expr = f"({end_src}) + 1"
                elif cond_op == "LT":
                    end_expr = end_src
                else:
                    end_expr = None
                if end_expr is not None:
                    if start_src is None:
                        start_src = "0"
                    if isinstance(step, int):
                        step_part = "" if step == 1 else f", {step}"
                        return f"{self.indent()}for {var_name} in range({start_src}, {end_expr}{step_part}):\n" + self._block_inside_as_lines(body)
            # for -> while
            lines = []
            if init is not None:
                if getattr(init, "type", None) == "FieldDecl":
                    lines.append(self._trans_field_decl(init))
                else:
                    init_src = self._expr_to_source(init)
                    if init_src:
                        for ln in init_src.splitlines():
                            lines.append(self.indent() + ln)
            cond_src = self._expr_to_source(condition) if condition is not None else "True"
            lines.append(self.indent() + f"while {cond_src}:")
            self.indent_level += 1
            lines.append(self._translate_node(body))
            if update is not None:
                update_src = self._expr_to_source(update)
                if update_src:
                    for ln in update_src.splitlines():
                        lines.append(self.indent() + ln)
            self.indent_level -= 1
            return "\n".join(lines)

        # foreach (var : collection)
        if len(children) == 3:
            var_node, collection_expr, body = children
            var_name = self._expr_to_source(var_node)
            coll_src = self._expr_to_source(collection_expr)
            lines = [self.indent() + f"for {var_name} in {coll_src}:"]
            self.indent_level += 1
            lines.append(self._translate_node(body))
            self.indent_level -= 1
            return "\n".join(lines)

        return f"{self.indent()}# Unsupported for-statement"

    def _block_inside_as_lines(self, body):
        self.indent_level += 1
        block_src = self._translate_node(body)
        self.indent_level -= 1
        return block_src

    def _trans_while_statement(self, node):
        condition, body = node.children
        cond_src = self._expr_to_source(condition)
        lines = [self.indent() + f"while {cond_src}:"]
        self.indent_level += 1
        lines.append(self._translate_node(body))
        self.indent_level -= 1
        return "\n".join(lines)

    def _trans_do_while_statement(self, node):
        condition, body = node.children
        cond_src = self._expr_to_source(condition)
        lines = [self.indent() + "while True:"]
        self.indent_level += 1
        lines.append(self._translate_node(body))
        lines.append(self.indent() + f"if not ({cond_src}):")
        self.indent_level += 1
        lines.append(self.indent() + "break")
        self.indent_level -= 2
        return "\n".join(lines)

    def _trans_switch_statement(self, node):
        if not node.children:
            return f"{self.indent()}# empty switch"
        expr = node.children[0]
        cases = node.children[1:]
        lines = [self.indent() + f"match {self._expr_to_source(expr)}:"]
        self.indent_level += 1
        for case in cases:
            case_src = self._translate_node(case)
            lines.extend(case_src.splitlines())
        self.indent_level -= 1
        return "\n".join(lines)

    def _trans_case_label(self, node):
        if not node.children:
            return self.indent() + "# empty case"
        case_val = node.children[0]
        stmts = node.children[1:]
        lines = []
        lines.append(self.indent() + f"case {self._expr_to_source(case_val)}:")
        self.indent_level += 1
        for s in stmts:
            if getattr(s, "type", None) == "Break":
                continue
            out = self._translate_node(s)
            if out:
                lines.append(out)
        self.indent_level -= 1
        return "\n".join(lines)

    def _trans_default_label(self, node):
        lines = []
        lines.append(self.indent() + "case _:")
        self.indent_level += 1
        for s in node.children:
            if getattr(s, "type", None) == "Break":
                continue
            out = self._translate_node(s)
            if out:
                lines.append(out)
        self.indent_level -= 1
        return "\n".join(lines)

    def _trans_postfixop(self, node):
        base_src = self._expr_to_source(node.children[0])
        if node.value == "INC":
            return f"{self.indent()}{base_src} += 1"
        if node.value == "DEC":
            return f"{self.indent()}{base_src} -= 1"
        return f"{self.indent()}{base_src}"

    def _trans_prefixop(self, node):
        base_src = self._expr_to_source(node.children[0])
        v = node.value
        return {
            "INC": f"{self.indent()}{base_src} += 1",
            "DEC": f"{self.indent()}{base_src} -= 1",
            "BANG": f"{self.indent()}not {base_src}",
            "TILDE": f"{self.indent()}~({base_src})",
            "ADD": f"{self.indent()}+({base_src})",
            "SUB": f"{self.indent()}-({base_src})",
        }.get(v, f"{self.indent()}{base_src}")

    # ---------------- expr -> source ----------------

    def _expr_to_source(self, expr) -> str:
        if expr is None:
            return ""
        if isinstance(expr, str):
            return expr
        t = getattr(expr, "type", None)
        if t == "Literal":
            v = expr.value or ""
            return self._format_literal_token(v)
        if t == "Identifier":
            v = (expr.value or "")
            if v == "this":
                return "self"
            if v == "super":
                return "super"
            lv = v.lower()
            if lv == "true":
                return "True"
            if lv == "false":
                return "False"
            if lv == "null":
                return "None"
            return v
        if t == "Paren":
            inner = expr.children[0] if expr.children else None
            return f"({self._expr_to_source(inner)})"
        if t == "Member":
            base = expr.children[0] if expr.children else None
            base_src = self._expr_to_source(base)
            return f"{base_src}.{expr.value}"
        if t == "Call":
            base = expr.value
            base_src = self._expr_to_source(base) if base is not None else ""
            args = expr.children or []
            args_src = ", ".join(self._expr_to_source(a) for a in args)

            # System.out.print(ln)
            if base_src.endswith(".println") or base_src == "System.out.println":
                first = args[0] if args else None
                return f"print({self._expr_to_source(first) if first else ''})"
            if base_src.endswith(".print") or base_src == "System.out.print":
                first = args[0] if args else None
                return f"print({self._expr_to_source(first) if first else ''}, end='')"

            if base_src == "self":   # this(...)
                return f"self.__init__({args_src})"
            if base_src == "super":  # super(...)
                return f"super().__init__({args_src})"

            # List.of(...)
            if base_src == "List.of":
                return "[" + ", ".join(self._expr_to_source(a) for a in args) + "]"

            return f"{base_src}({args_src})"
        if t == "BinaryOp":
            op_map = {
                "GT": ">", "LT": "<", "GE": ">=", "LE": "<=",
                "EQUAL": "==", "NOTEQUAL": "!=",
                "ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%",
                "AND": "and", "OR": "or",
                "BITAND": "&", "BITOR": "|", "CARET": "^",
                "LSHIFT": "<<", "RSHIFT": ">>", "URSHIFT": ">>",
            }
            op = op_map.get(expr.value, expr.value)
            left = expr.children[0]
            right = expr.children[1]
            left_s = self._expr_to_source(left)
            right_s = self._expr_to_source(right)
            return f"{left_s} {op} {right_s}"
        if t == "Assign":
            left = expr.children[0]
            right = expr.children[1]
            left_s = self._expr_to_source(left)
            right_s = self._expr_to_source(right)
            if self._in_constructor and getattr(left, "type", None) == "Identifier":
                left_s = f"self.{left_s}"
            return f"{left_s} = {right_s}"
        if t == "Param":
            return (expr.value or "").split()[-1]
        if t == "PostfixOp":
            base_src = self._expr_to_source(expr.children[0])
            if expr.value == "INC":
                return f"{base_src} += 1"
            if expr.value == "DEC":
                return f"{base_src} -= 1"
            return base_src
        if t == "PrefixOp":
            base_src = self._expr_to_source(expr.children[0])
            v = expr.value
            return {
                "INC": f"{base_src} += 1",
                "DEC": f"{base_src} -= 1",
                "BANG": f"not {base_src}",
                "TILDE": f"~({base_src})",
                "ADD": f"+({base_src})",
                "SUB": f"-({base_src})",
            }.get(v, base_src)
        if t == "Ternary":
            cond = expr.children[0]
            texpr = expr.children[1]
            fexpr = expr.children[2]
            return f"{self._expr_to_source(texpr)} if {self._expr_to_source(cond)} else {self._expr_to_source(fexpr)}"
        if t == "ArrayInit":
            elems = expr.children or []
            return "[" + ", ".join(self._expr_to_source(e) for e in elems) + "]"
        if t == "FieldDecl":
            s = self._trans_field_decl(expr)
            return s.strip()
        if getattr(expr, "children", None):
            parts = []
            for c in expr.children:
                parts.append(self._expr_to_source(c))
            return " ".join(p for p in parts if p)
        return ""
