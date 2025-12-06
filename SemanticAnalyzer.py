from dataclasses import dataclass, field
from typing import Dict, List, Optional
from SimpleJavaParser.SimpleJavaParser import ASTNode



# ---------------- Вспомогательные структуры ----------------


@dataclass
class TypeInfo:
    name: str

    @property
    def is_unknown(self) -> bool:
        return self.name == "Unknown"

    @property
    def is_primitive(self) -> bool:
        return self.name in {"byte", "short", "int", "long", "float", "double", "boolean", "char"}

    @property
    def is_boolean(self) -> bool:
        return self.name == "boolean"

    @property
    def is_numeric(self) -> bool:
        return self.name in {"byte", "short", "int", "long", "float", "double", "char"}

    @property
    def is_string(self) -> bool:
        return self.name == "String"

    @property
    def is_array(self) -> bool:
        """Тип массива: 'T[]', 'int[]', 'String[][]' и т.п."""
        return self.name.endswith("[]")

    @property
    def is_list(self) -> bool:
        """Простейшее распознавание List<T>."""
        return self.name.startswith("List<") and self.name.endswith(">")

    @property
    def element_type(self) -> "TypeInfo":
        """
        - 'T[]', 'T[][]' -> 'T';
        - 'List<T>' -> 'T';
        - иначе Unknown.
        """
        if self.is_array:
            base = self.name
            while base.endswith("[]"):
                base = base[:-2]
            base = base.strip()
            return TypeInfo(base) if base else TypeInfo("Unknown")

        # List<T>
        if self.is_list:
            inner = self.name[len("List<"):-1].strip()
            if not inner:
                return TypeInfo("Unknown")
            return TypeInfo(inner)

        return TypeInfo("Unknown")

    def __str__(self) -> str:
        return self.name


@dataclass
class VarInfo:
    name: str
    type: TypeInfo
    is_field: bool = False
    is_static: bool = False
    is_param: bool = False


@dataclass
class MethodInfo:
    name: str
    return_type: TypeInfo
    param_types: List[TypeInfo] = field(default_factory=list)
    is_static: bool = False
    is_constructor: bool = False


@dataclass
class ClassInfo:
    name: str
    fields: Dict[str, VarInfo] = field(default_factory=dict)
    methods: Dict[str, List[MethodInfo]] = field(default_factory=dict)
    super_name: Optional[str] = None


@dataclass
class Scope:
    parent: Optional["Scope"] = None
    vars: Dict[str, VarInfo] = field(default_factory=dict)

    def declare(self, var: VarInfo) -> bool:
        if var.name in self.vars:
            return False
        self.vars[var.name] = var
        return True

    def resolve(self, name: str) -> Optional[VarInfo]:
        scope: Optional["Scope"] = self
        while scope is not None:
            if name in scope.vars:
                return scope.vars[name]
            scope = scope.parent
        return None


class SemanticError(Exception):

    def __init__(self, message: str, node: Optional[ASTNode] = None):
        super().__init__(message)
        self.message = message
        self.node = node
        # Координаты извлекаем из узла, если они есть
        if node is not None:
            self.line = getattr(node, "line", None)
            self.column = getattr(node, "column", None)
        else:
            self.line = None
            self.column = None

    def __str__(self) -> str:
        if self.line is not None and self.column is not None:
            return f"{self.message} (строка {self.line}, столбец {self.column})"
        return self.message


# ---------------- Семантический анализатор ----------------


class SemanticAnalyzer:

    def __init__(self):
        self.classes: Dict[str, ClassInfo] = {}
        self.errors: List[SemanticError] = []

        self._current_method: Optional[MethodInfo] = None

        self.global_var_count: int = 0
        self.global_var_limit: Optional[int] = 128 

        self._block_depth: int = 0
        self.block_depth_limit: Optional[int] = None

    # ---------- Публичный API ----------

    def analyze(self, ast: ASTNode) -> List[SemanticError]:
        self.classes.clear()
        self.errors.clear()
        self._current_method = None
        self.global_var_count = 0
        self._block_depth = 0

        if ast.type != "CompilationUnit":
            raise SemanticError("Ожидался корневой узел CompilationUnit", ast)

        # регистрируем классы, их поля и сигнатуры методов/конструкторов.
        for child in ast.children:
            if isinstance(child, ASTNode) and child.type == "ClassDecl":
                self._register_class(child)

        # семантика внутри классов.
        for child in ast.children:
            if isinstance(child, ASTNode) and child.type == "ClassDecl":
                self._analyze_class(child)

        return self.errors

    # ---------- Регистрация классов/методов/полей ----------

    def _register_class(self, node: ASTNode) -> None:
        class_name = node.value or "Anonymous"
        if class_name in self.classes:
            self._error(f"Класс '{class_name}' уже объявлен", node)
            return

        ci = ClassInfo(name=class_name)

        for child in node.children:
            if isinstance(child, ASTNode) and child.type == "Base":
                if child.value:
                    parts = child.value.split()
                    if len(parts) == 2 and parts[0] == "extends":
                        ci.super_name = parts[1]

        # Поля и методы на верхнем уровне тела класса.
        for child in node.children:
            if not isinstance(child, ASTNode):
                continue
            if child.type == "FieldDecl":
                var = self._field_decl_to_varinfo(child, is_field=True)
                if var is not None:
                    if var.name in ci.fields:
                        self._error(f"Поле '{var.name}' уже объявлено в классе '{class_name}'", child)
                    else:
                        ci.fields[var.name] = var
                        # Учитываем глобальные идентификаторы
                        self.global_var_count += 1
                        if self.global_var_limit is not None and self.global_var_count > self.global_var_limit:
                            self._error(
                                f"Превышено максимальное число глобальных идентификаторов ({self.global_var_limit})",
                                child,
                            )

            elif child.type == "MethodDecl":
                mi = self._extract_method_info(child, class_name, is_constructor=False)
                if mi is not None:
                    if mi.name in ci.methods:
                        self._error(f"Метод '{mi.name}' уже объявлен в классе '{class_name}'", child)
                    else:
                        ci.methods[mi.name] = [mi]

            elif child.type == "ConstructorDecl":
                mi = self._extract_method_info(child, class_name, is_constructor=True)
                if mi is not None:
                    if mi.name in ci.methods:
                        self._error(f"Метод '{mi.name}' уже объявлен в классе '{class_name}'", child)
                    else:
                        ci.methods[mi.name] = [mi]

        self.classes[class_name] = ci

    def _field_decl_to_varinfo(self, node: ASTNode, is_field: bool) -> Optional[VarInfo]:
        if not isinstance(node.value, str):
            return None
        parts = node.value.strip().split()
        if len(parts) < 2:
            return None
        type_str = " ".join(parts[:-1])
        name = parts[-1]
        tinfo = self._parse_type(type_str)
        return VarInfo(name=name, type=tinfo, is_field=is_field)

    def _extract_method_info(
        self,
        node: ASTNode,
        class_name: str,
        is_constructor: bool,
    ) -> Optional[MethodInfo]:
        if is_constructor:
            name = class_name
            return_type = TypeInfo("void")
        else:
            if not isinstance(node.value, str):
                return None
            parts = node.value.strip().split()
            if len(parts) < 2:
                return None
            ret_type_str = " ".join(parts[:-1])
            name = parts[-1]
            return_type = self._parse_type(ret_type_str)

        param_types: List[TypeInfo] = []
        for ch in node.children:
            if isinstance(ch, ASTNode) and ch.type == "Param" and isinstance(ch.value, str):
                p_parts = ch.value.strip().split()
                if len(p_parts) >= 1:
                    type_str = " ".join(p_parts[:-1]) if len(p_parts) > 1 else p_parts[0]
                    param_types.append(self._parse_type(type_str))

        return MethodInfo(
            name=name,
            return_type=return_type,
            param_types=param_types,
            is_static=self._has_static_modifier(node),
            is_constructor=is_constructor,
        )

    def _has_static_modifier(self, node: ASTNode) -> bool:
        for ch in node.children:
            if isinstance(ch, ASTNode) and ch.type == "Modifiers" and isinstance(ch.value, str):
                # 'PUBLIC,STATIC' -> ['PUBLIC', 'STATIC']
                raw = ch.value.replace(",", " ")
                for m in raw.split():
                    if m.upper() == "STATIC":
                        return True
        return False

    # ---------- Анализ внутри классов ----------

    def _analyze_class(self, node: ASTNode) -> None:
        class_name = node.value or "Anonymous"
        ci = self.classes.get(class_name)
        if ci is None:
            return

        class_scope = Scope(parent=None)
        for field_var in ci.fields.values():
            class_scope.declare(field_var)

        for ch in node.children:
            if not isinstance(ch, ASTNode):
                continue
            if ch.type in {"MethodDecl", "ConstructorDecl"}:
                self._analyze_method_or_constructor(ch, ci, class_scope)

    def _analyze_method_or_constructor(self, node: ASTNode, ci: ClassInfo, class_scope: Scope) -> None:
        method_scope = Scope(parent=class_scope)

        is_constructor = node.type == "ConstructorDecl"
        mi = self._extract_method_info(node, ci.name, is_constructor=is_constructor)

        is_static = mi.is_static if mi is not None else self._has_static_modifier(node)

        if not is_static:
            this_var = VarInfo(name="this", type=TypeInfo(ci.name), is_param=True)
            method_scope.declare(this_var)
            if ci.super_name:
                super_var = VarInfo(name="super", type=TypeInfo(ci.super_name), is_param=True)
                method_scope.declare(super_var)

        for ch in node.children:
            if isinstance(ch, ASTNode) and ch.type == "Param" and isinstance(ch.value, str):
                parts = ch.value.strip().split()
                if len(parts) < 1:
                    continue
                if len(parts) == 1:
                    p_type = TypeInfo("Unknown")
                    p_name = parts[0]
                else:
                    type_str = " ".join(parts[:-1])
                    p_name = parts[-1]
                    p_type = self._parse_type(type_str)
                var = VarInfo(name=p_name, type=p_type, is_param=True)
                if not method_scope.declare(var):
                    self._error(f"Повторное объявление параметра '{p_name}'", ch)

        prev_method = self._current_method
        self._current_method = mi

        for ch in node.children:
            if not isinstance(ch, ASTNode):
                continue
            if ch.type in {"Param", "Modifiers"}:
                continue
            self._analyze_statement(ch, method_scope, ci)

        self._current_method = prev_method

    # ---------- Анализ блоков и инструкций ----------

    def _analyze_block(self, block: ASTNode, scope: Scope, ci: ClassInfo) -> None:
        self._block_depth += 1
        if self.block_depth_limit is not None and self._block_depth > self.block_depth_limit:
            self._error(
                f"Превышена максимальная глубина вложенности блоков: {self._block_depth}",
                block,
            )

        try:
            block_scope = Scope(parent=scope)
            for stmt in block.children:
                if isinstance(stmt, ASTNode):
                    self._analyze_statement(stmt, block_scope, ci)
        finally:
            self._block_depth -= 1

    def _analyze_statement(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> None:
        t = node.type

        if t == "Block":
            self._analyze_block(node, scope, ci)

        elif t == "FieldDecl":
            var = self._field_decl_to_varinfo(node, is_field=False)
            if var is None:
                return
            if not scope.declare(var):
                self._error(f"Повторное объявление переменной '{var.name}'", node)

            init_expr = None
            for ch in node.children:
                if isinstance(ch, ASTNode) and ch.type == "Init":
                    if ch.children:
                        init_expr = ch.children[0]
                    break
            if init_expr is not None:
                rhs_type = self._analyze_expression(init_expr, scope, ci)

                if var.type.is_array and isinstance(init_expr, ASTNode) and init_expr.type == "ArrayInit":
                    elem_expected = var.type.element_type
                    for elem in init_expr.children:
                        if isinstance(elem, ASTNode):
                            elem_type = self._analyze_expression(elem, scope, ci)
                            self._check_assignment_compatibility(elem_expected, elem_type, elem)
                else:
                    self._check_assignment_compatibility(var.type, rhs_type, init_expr)

        elif t == "ExprStmt":
            if node.children:
                self._analyze_expression(node.children[0], scope, ci)

        elif t == "Assign":
            if len(node.children) >= 2:
                lhs = node.children[0]
                rhs = node.children[1]
                lhs_type = self._analyze_lhs(lhs, scope, ci)
                rhs_type = self._analyze_expression(rhs, scope, ci)
                self._check_assignment_compatibility(lhs_type, rhs_type, node)

        elif t == "IfStatement":
            cond_expr = node.value
            if cond_expr is not None:
                cond_type = self._analyze_expression(cond_expr, scope, ci)
                self._check_condition_boolean(cond_type, node, is_loop=False)

            for ch in node.children:
                if isinstance(ch, ASTNode):
                    self._analyze_statement(ch, scope, ci)

        elif t == "WhileStatement":
            if node.children:
                cond_expr = node.children[0]
                cond_type = self._analyze_expression(cond_expr, scope, ci)
                self._check_condition_boolean(cond_type, node, is_loop=True)
            for ch in node.children[1:]:
                if isinstance(ch, ASTNode):
                    self._analyze_statement(ch, scope, ci)

        elif t == "DoWhileStatement":
            cond_expr = node.children[0] if len(node.children) >= 1 else None
            body = node.children[1] if len(node.children) >= 2 else None

            if body is not None and isinstance(body, ASTNode):
                self._analyze_statement(body, scope, ci)
            if cond_expr is not None:
                cond_type = self._analyze_expression(cond_expr, scope, ci)
                self._check_condition_boolean(cond_type, node, is_loop=True)

        elif t == "ForStatement":
            self._analyze_for_statement(node, scope, ci)

        elif t == "Return":
            self._analyze_return(node, scope, ci)

        elif t == "SwitchStatement":
            self._analyze_switch_statement(node, scope, ci)

        elif t in {"Break", "Continue", "CaseLabel", "DefaultLabel", "TryStatement"}:
            for ch in node.children:
                if isinstance(ch, ASTNode):
                    if ch.type == "Block":
                        self._analyze_block(ch, scope, ci)
                    else:
                        self._analyze_statement(ch, scope, ci)

        else:
            for ch in node.children:
                if isinstance(ch, ASTNode):
                    self._analyze_statement(ch, scope, ci)

    def _analyze_for_statement(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> None:
        """
        1) for(init; cond; update) body
        2) for-each (T x : expr) body
        """
        loop_scope = Scope(parent=scope)

        children = [ch for ch in node.children if isinstance(ch, ASTNode)]
        if not children:
            return

        if (
            len(children) == 3
            and children[0].type == "Param"
            and children[2].type == "Block"
            and isinstance(children[0].value, str)
        ):
            param_node = children[0]
            collection_expr = children[1]
            body = children[2]

            parts = param_node.value.strip().split()
            if parts:
                type_str = " ".join(parts[:-1]) if len(parts) > 1 else parts[0]
                name = parts[-1]
                var_type = self._parse_type(type_str)
                var = VarInfo(name=name, type=var_type, is_field=False, is_param=False)
                if not loop_scope.declare(var):
                    self._error(f"Повторное объявление переменной '{name}' в заголовке цикла for-each", param_node)

                coll_type = self._analyze_expression(collection_expr, loop_scope, ci)

                if not coll_type.is_unknown:
                    elem_type = TypeInfo("Unknown")
                    if coll_type.is_array or coll_type.is_list:
                        elem_type = coll_type.element_type

                    if not elem_type.is_unknown:
                        self._check_assignment_compatibility(var_type, elem_type, collection_expr)

            self._analyze_block(body, loop_scope, ci)
            return
    
        body = None
        for ch in reversed(children):
            if ch.type == "Block":
                body = ch
                break

        for ch in children:
            if ch is body:
                continue
            if ch.type == "FieldDecl":
                var = self._field_decl_to_varinfo(ch, is_field=False)
                if var is not None:
                    if not loop_scope.declare(var):
                        self._error(f"Повторное объявление переменной '{var.name}'", ch)
                    init_expr = None
                    for sub in ch.children:
                        if isinstance(sub, ASTNode) and sub.type == "Init" and sub.children:
                            init_expr = sub.children[0]
                            break
                    if init_expr is not None:
                        rhs_type = self._analyze_expression(init_expr, loop_scope, ci)
                        self._check_assignment_compatibility(var.type, rhs_type, init_expr)

        cond_expr = None
        for ch in children:
            if ch is body:
                break
            if ch.type not in {"FieldDecl", "Block"}:
                cond_expr = ch
                break
        if cond_expr is not None:
            cond_type = self._analyze_expression(cond_expr, loop_scope, ci)
            self._check_condition_boolean(cond_type, node, is_loop=True)

        if body is not None:
            self._analyze_block(body, loop_scope, ci)

    def _analyze_return(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> None:
        expr = None
        if node.children:
            expr = node.children[0]

        expr_type: Optional[TypeInfo] = None
        if isinstance(expr, ASTNode):
            expr_type = self._analyze_expression(expr, scope, ci)

        mi = self._current_method
        if mi is None:
            return

        ret_type = mi.return_type

        if mi.is_constructor:
            if expr is not None:
                self._error("Конструктор не может возвращать значение", node)
            return

        if ret_type.name == "void":
            if expr is not None:
                self._error("Метод с типом void не должен возвращать значение", node)
            return

        if expr is None:
            self._error(f"Метод с типом {ret_type} должен возвращать значение", node)
            return

        if expr_type is not None:
            self._check_assignment_compatibility(ret_type, expr_type, expr)
            
    # ---------- Анализ левой части присваивания ----------

    def _analyze_switch_statement(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> None:
        if not node.children:
            return

        switch_expr = node.children[0]
        switch_type = TypeInfo("Unknown")
        if isinstance(switch_expr, ASTNode):
            switch_type = self._analyze_expression(switch_expr, scope, ci)

        if not switch_type.is_unknown and switch_type.is_boolean:
            self._error("switch по boolean не поддерживается", switch_expr)

        def _types_compatible_for_switch(sw_type: TypeInfo, case_type: TypeInfo) -> bool:
            """
            Логика намеренно упрощена:
            - если один из типов Unknown — не генерируем дополнительную ошибку;
            - если имена типов совпадают — считаем совместимыми;
            - если оба типа числовые — считаем совместимыми.
            """
            if sw_type.is_unknown or case_type.is_unknown:
                return True
            if sw_type.name == case_type.name:
                return True
            if sw_type.is_numeric and case_type.is_numeric:
                return True
            return False

        for case_node in node.children[1:]:
            if not isinstance(case_node, ASTNode):
                continue

            if case_node.type == "CaseLabel":
                if not case_node.children:
                    continue

                case_expr = case_node.children[0]
                case_type = self._analyze_expression(case_expr, scope, ci)

                if not _types_compatible_for_switch(switch_type, case_type):
                    self._error(
                        f"Тип выражения в case не согласован с типом switch: {switch_type} и {case_type}",
                        case_node,
                    )

                for stmt in case_node.children[1:]:
                    if isinstance(stmt, ASTNode):
                        self._analyze_statement(stmt, scope, ci)

            elif case_node.type == "DefaultLabel":
                for stmt in case_node.children:
                    if isinstance(stmt, ASTNode):
                        self._analyze_statement(stmt, scope, ci)

            else:
                self._analyze_statement(case_node, scope, ci)

    def _analyze_lhs(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> TypeInfo:
        """
        - Identifier (локальная/поле класса/параметр);
        - Member (obj.field).
        """
        if node.type == "Identifier":
            return self._analyze_expression(node, scope, ci)

        if node.type == "Member" and node.children:
            base_expr = node.children[0]
            base_type = self._analyze_expression(base_expr, scope, ci)
            field_name: Optional[str] = None
            if isinstance(node.value, str):
                field_name = node.value
            elif len(node.children) >= 2 and isinstance(node.children[1].value, str):
                field_name = node.children[1].value

            if base_type.is_unknown or field_name is None:
                return TypeInfo("Unknown")

            field_type = self._resolve_field_type(base_type.name, field_name)
            if field_type is None:
                return TypeInfo("Unknown")
            return field_type

        return self._analyze_expression(node, scope, ci)

    # ---------- Анализ выражений ----------

    def _analyze_expression(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> TypeInfo:
        t = node.type

        if t == "Literal":
            return self._infer_literal_type(node)

        if t == "Identifier":
            name = str(node.value)

            if name == "this":
                if self._current_method is not None and self._current_method.is_static:
                    self._error("Нельзя использовать this в статическом методе", node)
                    return TypeInfo("Unknown")
                return TypeInfo(ci.name)

            if name == "super":
                if self._current_method is not None and self._current_method.is_static:
                    self._error("Нельзя использовать super в статическом методе", node)
                    return TypeInfo("Unknown")
                if ci.super_name:
                    return TypeInfo(ci.super_name)
                return TypeInfo("Unknown")

            if name == "System":
                return TypeInfo("Unknown")

            var = scope.resolve(name)
            if var is None:
                self._error(f"Идентификатор '{name}' не объявлен", node)
                return TypeInfo("Unknown")
            return var.type

        if t == "Member":
            return self._analyze_lhs(node, scope, ci)

        if t == "ArrayInit":
            for ch in node.children:
                if isinstance(ch, ASTNode):
                    self._analyze_expression(ch, scope, ci)
            return TypeInfo("Unknown")
        
        if t == "BinaryOp":
            return self._analyze_binary_op(node, scope, ci)

        if t == "PrefixOp":
            return self._analyze_prefix_op(node, scope, ci)

        if t == "PostfixOp":
            return self._analyze_postfix_op(node, scope, ci)

        if t == "Ternary":
            return self._analyze_ternary(node, scope, ci)

        if t == "Call":
            return self._analyze_call(node, scope, ci)

        if t == "Assign":
            if len(node.children) >= 2:
                lhs_type = self._analyze_lhs(node.children[0], scope, ci)
                rhs_type = self._analyze_expression(node.children[1], scope, ci)
                self._check_assignment_compatibility(lhs_type, rhs_type, node)
                return lhs_type
            return TypeInfo("Unknown")

        for ch in node.children:
            if isinstance(ch, ASTNode):
                self._analyze_expression(ch, scope, ci)
        return TypeInfo("Unknown")

    def _analyze_binary_op(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> TypeInfo:
        op = str(node.value) if node.value is not None else ""
        left_type = self._analyze_expression(node.children[0], scope, ci) if node.children else TypeInfo("Unknown")
        right_type = self._analyze_expression(node.children[1], scope, ci) if len(node.children) > 1 else TypeInfo("Unknown")

        if left_type.is_unknown or right_type.is_unknown:
            return TypeInfo("Unknown")

        if op in {"ADD", "SUB", "MUL", "DIV", "MOD"}:
            if left_type.is_numeric and right_type.is_numeric:
                return left_type
            if op == "ADD" and left_type.is_string and right_type.is_string:
                return left_type
            self._error(
                f"Несовпадение типов операндов бинарного оператора '{op}': {left_type} и {right_type}",
                node,
            )
            return TypeInfo("Unknown")

        if op in {"LT", "GT", "LE", "GE", "EQ", "NE"}:
            if left_type.name == right_type.name or (left_type.is_numeric and right_type.is_numeric):
                return TypeInfo("boolean")
            self._error(
                f"Несовпадение типов операндов бинарного оператора '{op}': {left_type} и {right_type}",
                node,
            )
            return TypeInfo("boolean")

        if op in {"AND", "OR"}:
            if left_type.is_boolean and right_type.is_boolean:
                return TypeInfo("boolean")
            self._error(
                f"Логический оператор '{op}' применим только к boolean, получены {left_type} и {right_type}",
                node,
            )
            return TypeInfo("boolean")

        if op in {"BITAND", "BITOR", "CARET", "LSHIFT", "RSHIFT", "URSHIFT"}:
            if left_type.is_numeric and right_type.is_numeric:
                return left_type
            self._error(
                f"Побитовый оператор '{op}' применим только к числовым типам, получены {left_type} и {right_type}",
                node,
            )
            return TypeInfo("Unknown")

        return TypeInfo("Unknown")

    def _analyze_prefix_op(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> TypeInfo:
        op = str(node.value) if node.value is not None else ""
        expr = node.children[0] if node.children else None
        inner_type = self._analyze_expression(expr, scope, ci) if expr is not None else TypeInfo("Unknown")

        if op in {"INC", "DEC"}:
            if inner_type.is_unknown:
                return TypeInfo("Unknown")
            if not inner_type.is_numeric:
                self._error(f"Оператор {op} применим только к числовым типам, получен {inner_type}", node)
                return TypeInfo("Unknown")
            return inner_type

        if op in {"PLUS", "MINUS"}:
            if inner_type.is_numeric or inner_type.is_unknown:
                return inner_type
            self._error(f"Унарный оператор {op} применим только к числовым типам, получен {inner_type}", node)
            return TypeInfo("Unknown")

        if op == "NOT":
            if inner_type.is_unknown or inner_type.is_boolean:
                return TypeInfo("boolean")
            self._error(f"Унарный оператор '!' применим только к boolean, получен {inner_type}", node)
            return TypeInfo("boolean")

        return inner_type

    def _analyze_postfix_op(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> TypeInfo:
        op = str(node.value) if node.value is not None else ""
        expr = node.children[0] if node.children else None
        inner_type = self._analyze_expression(expr, scope, ci) if expr is not None else TypeInfo("Unknown")

        if op in {"INC", "DEC"}:
            if inner_type.is_unknown:
                return TypeInfo("Unknown")
            if not inner_type.is_numeric:
                self._error(f"Оператор {op} применим только к числовым типам, получен {inner_type}", node)
                return TypeInfo("Unknown")
            return inner_type

        return inner_type

    def _analyze_ternary(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> TypeInfo:
        if len(node.children) < 3:
            for ch in node.children:
                if isinstance(ch, ASTNode):
                    self._analyze_expression(ch, scope, ci)
            return TypeInfo("Unknown")

        cond_node = node.children[0]
        then_node = node.children[1]
        else_node = node.children[2]

        cond_type = self._analyze_expression(cond_node, scope, ci)
        if not cond_type.is_unknown and not cond_type.is_boolean:
            self._error(
                f"Условие тернарного оператора должно иметь тип boolean, получено {cond_type}",
                node,
            )

        then_type = self._analyze_expression(then_node, scope, ci)
        else_type = self._analyze_expression(else_node, scope, ci)

        if then_type.is_unknown or else_type.is_unknown:
            return TypeInfo("Unknown")

        if then_type.name == else_type.name:
            return then_type

        if then_type.is_numeric and else_type.is_numeric:
            return then_type

        self._error(
            f"Ветви тернарного оператора имеют несовместимые типы: {then_type} и {else_type}",
            node,
        )
        return TypeInfo("Unknown")

    def _analyze_call(self, node: ASTNode, scope: Scope, ci: ClassInfo) -> TypeInfo:
        arg_types: List[TypeInfo] = [
            self._analyze_expression(arg, scope, ci) for arg in node.children
        ]

        def types_compatible(expected: TypeInfo, actual: TypeInfo) -> bool:
            if expected.is_unknown or actual.is_unknown:
                return True
            if (
                expected.is_primitive
                or expected.is_string
                or actual.is_primitive
                or actual.is_string
            ):
                return expected.name == actual.name
            return True

        callee = node.value
        if not isinstance(callee, ASTNode):
            return TypeInfo("Unknown")

        method_name: Optional[str] = None
        base_expr: Optional[ASTNode] = None

        if callee.type == "Identifier":
            # f(...)
            name = str(callee.value)
            if name in {"this", "super"}:
                return TypeInfo("Unknown")
            method_name = name
            base_expr = None

        elif callee.type == "Member":
            # obj.f(...)
            if isinstance(callee.value, str):
                method_name = callee.value
            if callee.children:
                base_expr = callee.children[0]

        else:
            base_expr_type = self._analyze_expression(callee, scope, ci)
            return TypeInfo("Unknown")

        if not method_name:
            return TypeInfo("Unknown")
        target_class: Optional[ClassInfo] = None

        if base_expr is None:
            target_class = ci

        elif base_expr.type == "Identifier":
            base_name = str(base_expr.value)
            if base_name == "this":
                target_class = ci
            elif base_name == "super":
                # super.f(...)
                if ci.super_name:
                    target_class = self.classes.get(ci.super_name)
                    if target_class is None:
                        return TypeInfo("Unknown")
                else:
                    self._error("Вызов super в классе без базового класса", base_expr)
                    return TypeInfo("Unknown")
            else:
                # obj.f(...)
                var = scope.resolve(base_name)
                if var is None or var.type.is_unknown:
                    return TypeInfo("Unknown")
                target_class = self.classes.get(var.type.name)
                if target_class is None:
                    return TypeInfo("Unknown")

        else:
            base_type = self._analyze_expression(base_expr, scope, ci)
            if base_type.is_unknown:
                return TypeInfo("Unknown")
            target_class = self.classes.get(base_type.name)
            if target_class is None:
                return TypeInfo("Unknown")

        if target_class is None:
            return TypeInfo("Unknown")

        candidates: List[MethodInfo] = []
        current: Optional[ClassInfo] = target_class
        visited: set[str] = set()

        while current is not None and current.name not in visited:
            visited.add(current.name)
            methods_here = current.methods.get(method_name)
            if methods_here:
                candidates.extend(methods_here)
            if not current.super_name:
                break
            current = self.classes.get(current.super_name)

        if not candidates:
            self._error(
                f"Метод '{method_name}' не найден в классе '{target_class.name}'",
                node,
            )
            return TypeInfo("Unknown")

        same_arity = [m for m in candidates if len(m.param_types) == len(arg_types)]
        if not same_arity:
            self._error(
                f"Несоответствие числа аргументов при вызове '{method_name}': "
                f"ожидалось {len(candidates[0].param_types)}, получено {len(arg_types)}",
                node,
            )
            return TypeInfo("Unknown")

        def fmt_types(types: List[TypeInfo]) -> str:
            return ", ".join(t.name for t in types) if types else ""

        for m in same_arity:
            ok = True
            for expected, actual in zip(m.param_types, arg_types):
                if not types_compatible(expected, actual):
                    ok = False
                    break
            if ok:
                return m.return_type

        expected_sig = fmt_types(same_arity[0].param_types)
        actual_sig = fmt_types(arg_types)
        self._error(
            f"Несовпадение типов аргументов при вызове '{method_name}': "
            f"ожидалось ({expected_sig}), получено ({actual_sig})",
            node,
        )
        return TypeInfo("Unknown")


    # ---------- Вспомогательные проверки ----------

    def _check_assignment_compatibility(self, target: TypeInfo, rhs: TypeInfo, node: ASTNode) -> None:
        if target.is_unknown or rhs.is_unknown:
            return

        if target.is_primitive or target.is_string or rhs.is_primitive or rhs.is_string:
            if target.name != rhs.name:
                self._error(
                    f"Несовпадение типов при присваивании: слева {target}, справа {rhs}",
                    node,
                )
            return
        return

    def _check_condition_boolean(self, cond_type: TypeInfo, node: ASTNode, *, is_loop: bool) -> None:
        if cond_type.is_unknown:
            return
        if not cond_type.is_boolean:
            if is_loop:
                self._error(f"Условие цикла должно иметь тип boolean, получено {cond_type}", node)
            else:
                self._error(f"Условие if должно иметь тип boolean, получено {cond_type}", node)

    # ---------- Разбор типов и литералов ----------

    def _parse_type(self, type_str: str) -> TypeInfo:
        type_str = type_str.strip()
        if not type_str:
            return TypeInfo("Unknown")
        return TypeInfo(type_str)

    def _infer_literal_type(self, node: ASTNode) -> TypeInfo:
        text = str(node.value)

        if text == "true" or text == "false":
            return TypeInfo("boolean")

        if text == "null":
            return TypeInfo("null")

        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'") and len(text) >= 3):
            if text.startswith('"'):
                return TypeInfo("String")
            return TypeInfo("char")

        num = text
        if num[-1:] in "lLfFdD":
            num = num[:-1]

        try:
            int(num)
            return TypeInfo("int")
        except ValueError:
            pass

        try:
            float(num)
            return TypeInfo("double")
        except ValueError:
            pass

        return TypeInfo("Unknown")

    def _resolve_field_type(self, class_name: str, field_name: str) -> Optional[TypeInfo]:
        ci = self.classes.get(class_name)
        if ci is None:
            return None
        var = ci.fields.get(field_name)
        if var is None:
            return None
        return var.type

    # ---------- Регистрация ошибок ----------

    def _error(self, msg: str, node: Optional[ASTNode] = None) -> None:
        self.errors.append(SemanticError(msg, node))
