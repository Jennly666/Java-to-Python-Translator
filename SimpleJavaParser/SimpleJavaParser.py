from typing import Optional
from Token import Token

class ASTNode:
    def __init__(self, type_, value=None, children=None, token=None):
        self.type = type_
        self.value = value
        self.children = children or []
        self.token = token
        if token is not None:
            self.line = getattr(token, "line", None)
            self.column = getattr(token, "column", None)
        else:
            inherited_token = None
            for ch in self.children:
                if isinstance(ch, ASTNode) and getattr(ch, "token", None) is not None:
                    inherited_token = ch.token
                    break
            if inherited_token is not None:
                self.token = inherited_token
                self.line = getattr(inherited_token, "line", None)
                self.column = getattr(inherited_token, "column", None)
            else:
                self.line = None
                self.column = None

    def __repr__(self, level=0):
        indent = "  " * level
        s = f"{indent}{self.type}"
        if self.value is not None:
            s += f": {self.value}"
        for child in self.children:
            if isinstance(child, ASTNode):
                s += "\n" + child.__repr__(level + 1)
            else:
                s += "\n" + ("  " * (level + 1)) + repr(child)
        return s


class SimpleJavaParser:
    IGNORED = {"COMMENT", "LINE_COMMENT", "WS"}
    MODIFIERS = {"PUBLIC", "PRIVATE", "PROTECTED", "STATIC", "FINAL", "ABSTRACT"}
    TYPE_KEYWORDS = {"INT", "FLOAT", "DOUBLE", "BOOLEAN", "CHAR", "VOID", "STRING"}
    PRECEDENCE = {
        "MUL": 60, "DIV": 60, "MOD": 60,
        "ADD": 50, "SUB": 50,
        "GT": 40, "LT": 40, "GE": 40, "LE": 40,
        "EQUAL": 30, "NOTEQUAL": 30,
        "AND": 20, "OR": 10,
        "BITAND": 5, "BITOR": 5, "CARET": 5,
        "LSHIFT": 5, "RSHIFT": 5, "URSHIFT": 5,
    }

    def __init__(self, tokens):
        self.tokens = tokens
        self.current = self.tokens.LT(1)
        self._skip_ignored()
        self._current_class_name: Optional[str] = None

    # --------------- utilities ---------------
    def _skip_ignored(self):
        while self.current is not None and getattr(self.current, "type", None) in self.IGNORED:
            self.tokens.consume()
            self.current = self.tokens.LT(1)

    def advance(self):
        self.tokens.consume()
        self.current = self.tokens.LT(1)
        self._skip_ignored()

    def match(self, expected_type: str):
        if (self.current is None) or (self.current.type == Token.EOF and expected_type != Token.EOF):
            raise SyntaxError(f"Ожидался {expected_type}, получен EOF")
        if self.current.type != expected_type:
            raise SyntaxError(f"Ожидался {expected_type}, получен {self.current.type}")
        self.advance()

    def accept(self, expected_type: str) -> bool:
        if self.current is not None and self.current.type == expected_type:
            self.advance()
            return True
        return False

    def peek_type(self, k=1):
        t = self.tokens.LT(k)
        return t.type if t is not None else None

    def _peek_token(self, k: int):
        try:
            return self.tokens.LT(k)
        except Exception:
            return None

    def _peek_text(self, k: int):
        t = self._peek_token(k)
        return getattr(t, "text", None) if t is not None else None

    def _maybe_generic_suffix(self, base_type: str) -> str:
        """
        'List < String , Integer >' -> 'List<String,Integer>'.
        """
        if not (self.current and getattr(self.current, "type", None) == "LT"):
            return base_type
        depth = 0
        out = [base_type]
        while self.current and self.current.type != Token.EOF:
            t = self.current
            if t.type == "LT":
                depth += 1; out.append("<")
            elif t.type == "GT":
                depth -= 1; out.append(">")
            else:
                out.append(getattr(t, "text", t.type))
            self.advance()
            if depth == 0:
                break
        return "".join(out).replace(" ", "")

    def _is_constructor_start(self):
        if not self._current_class_name:
            return False
        i = 1
        while True:
            t = self._peek_token(i)
            if t is None:
                return False
            if getattr(t, "type", None) in self.MODIFIERS:
                i += 1
                continue
            break
        t = self._peek_token(i)
        t2 = self._peek_token(i + 1)
        if t is None:
            return False
        if getattr(t, "type", None) == "IDENTIFIER" and getattr(t2, "type", None) == "LPAREN":
            return getattr(t, "text", None) == self._current_class_name
        return False

    def _looks_like_method_decl(self):
        i = 1
        while self.peek_type(i) in self.MODIFIERS:
            i += 1
        if self.peek_type(i) in self.TYPE_KEYWORDS or self.peek_type(i) == "VOID" or self.peek_type(i) == "IDENTIFIER":
            if self.peek_type(i + 1) == "IDENTIFIER" and self.peek_type(i + 2) == "LPAREN":
                return True
        return False

    # --------------- entry ---------------
    def parse(self):
        return self.parse_compilation_unit()

    def parse_compilation_unit(self):
        children = []
        while self.current is not None and self.current.type != Token.EOF:
            if self.current.type in self.MODIFIERS or self.current.type == "CLASS":
                td = self.parse_type_declaration()
                if td:
                    children.append(td)
                else:
                    self.advance()
            else:
                self.advance()
        return ASTNode("CompilationUnit", children=children)

    # --------------- type / class ---------------
    def parse_type_declaration(self):
        modifiers = []
        while self.current is not None and self.current.type in self.MODIFIERS:
            modifiers.append(self.current.type)
            self.advance()
        if self.current is not None and self.current.type == "CLASS":
            return self.parse_class_declaration(modifiers)
        return None

    def parse_class_declaration(self, modifiers=None):
        modifiers = modifiers or []
        self.match("CLASS")
        if self.current is None:
            raise SyntaxError("Ожидался идентификатор класса, получен EOF")
        class_token = self.current
        class_name = class_token.text
        self.match("IDENTIFIER")

        bases = []
        if self.accept("EXTENDS"):
            if self.current and self.current.type == "IDENTIFIER":
                base = self.current.text
                self.advance()
                bases.append(base)

        self._current_class_name = class_name

        self.match("LBRACE")
        body_children = []

        if bases:
            body_children.append(ASTNode("Base", ",".join(bases)))

        while self.current is not None and self.current.type not in ("RBRACE", Token.EOF):
            if (self.current.type in self.MODIFIERS or
                self.current.type in self.TYPE_KEYWORDS or
                self.current.type == "IDENTIFIER" or
                self.current.type == "VOID"):

                if self._is_constructor_start():
                    node = self.parse_constructor_declaration()
                    if node:
                        body_children.append(node)
                elif self._looks_like_method_decl():
                    node = self.parse_method_declaration()
                    if node:
                        body_children.append(node)
                else:
                    node = self.parse_field_declaration()
                    if node:
                        body_children.append(node)
            else:
                if self.current.type == "LBRACE":
                    stmts = self.parse_block()
                    body_children.append(ASTNode("Block", children=stmts))
                else:
                    self.advance()

        if self.current is None or self.current.type == Token.EOF:
            raise SyntaxError(f"Unclosed class body for class {class_name} — reached EOF without '}}'")

        self.match("RBRACE")

        node = ASTNode("ClassDecl", class_name, body_children, token=class_token)
        if modifiers:
            node.children.insert(0, ASTNode("Modifiers", ",".join(modifiers)))
        self._current_class_name = None
        return node

    def parse_constructor_declaration(self):
        modifiers = []
        while self.current is not None and self.current.type in self.MODIFIERS:
            modifiers.append(self.current.type)
            self.advance()

        if self.current is None or self.current.type != "IDENTIFIER":
            raise SyntaxError("Ожидалось имя конструктора")
        constructor_name = self.current.text
        self.match("IDENTIFIER")

        self.match("LPAREN")
        params = self.parse_parameter_list()
        self.match("RPAREN")

        body = []
        if self.current and self.current.type == "LBRACE":
            body = self.parse_block()

        node = ASTNode("ConstructorDecl", constructor_name, params + body)
        if modifiers:
            node.children.insert(0, ASTNode("Modifiers", ",".join(modifiers)))
        return node

    # --------------- fields / locals ---------------
    def parse_field_declaration(self):
        mods = []
        while self.current and self.current.type in self.MODIFIERS:
            mods.append(self.current.type); self.advance()

        type_tok = None
        if self.current and (self.current.type in self.TYPE_KEYWORDS or self.current.type == "IDENTIFIER"):
            type_tok = self.current.text; self.advance()
            # generics
            type_tok = self._maybe_generic_suffix(type_tok)
            while self.current and self.current.type == "LBRACK":
                self.advance()
                if self.current and self.current.type == "RBRACK":
                    self.advance()
                    type_tok = (type_tok or "") + "[]"
                else:
                    break
        else:
            if self.current:
                self.advance()
            return ASTNode("FieldDecl", f"{type_tok} var", [])

        decls = []
        while True:
            if not (self.current and self.current.type == "IDENTIFIER"):
                break
            name_token = self.current
            name = name_token.text
            self.advance()

            init = None
            if self.accept("ASSIGN"):
                # new-массив
                if self.current and self.current.type == "NEW":
                    self.advance()
                    if self.current and (self.current.type in self.TYPE_KEYWORDS or self.current.type == "IDENTIFIER"):
                        _ = self.current.text; self.advance()
                        _ = self._maybe_generic_suffix(_)
                    while self.current and self.current.type == "LBRACK":
                        self.advance()
                        if self.current and self.current.type != "RBRACK":
                            _ = self.parse_expression()
                        self.match("RBRACK")
                    if self.current and self.current.type == "LBRACE":
                        self.advance()
                        elems = []
                        while self.current and self.current.type != "RBRACE":
                            elems.append(self.parse_expression())
                            if self.current and self.current.type == "COMMA":
                                self.advance()
                        self.match("RBRACE")
                        init = ASTNode("ArrayInit", None, elems)
                    else:
                        init = ASTNode("Unknown", "new-array")
                # короткая форма { ... }
                elif self.current and self.current.type == "LBRACE":
                    self.advance()
                    elems = []
                    while self.current and self.current.type != "RBRACE":
                        elems.append(self.parse_expression())
                        if self.current and self.current.type == "COMMA":
                            self.advance()
                    self.match("RBRACE")
                    init = ASTNode("ArrayInit", None, elems)
                else:
                    init = self.parse_expression()

            fd_children = []
            if mods:
                fd_children.append(ASTNode("Modifiers", ",".join(mods)))
            if init is not None:
                fd_children.append(ASTNode("Init", None, [init]))
            decls.append(ASTNode("FieldDecl", f"{type_tok} {name}", fd_children, token=name_token))

            if self.current and self.current.type == "COMMA":
                self.advance()
                continue
            break


        if self.current and self.current.type == "SEMI":
            self.advance()

        return decls[0] if len(decls) == 1 else ASTNode("Block", children=decls)

    def parse_local_variable_declaration_no_semi(self):
        while self.current and self.current.type in self.MODIFIERS:
            self.advance()

        type_tok = None
        if self.current and (self.current.type in self.TYPE_KEYWORDS or self.current.type == "IDENTIFIER"):
            type_tok = self.current.text; self.advance()
            type_tok = self._maybe_generic_suffix(type_tok)
            while self.current and self.current.type == "LBRACK":
                self.advance()
                if self.current and self.current.type == "RBRACK":
                    self.advance()
                    type_tok = (type_tok or "") + "[]"
                else:
                    break
        else:
            return ASTNode("FieldDecl", f"{type_tok} var", [])

        decls = []
        while True:
            if not (self.current and self.current.type == "IDENTIFIER"):
                break
            name = self.current.text; self.advance()

            init = None
            if self.accept("ASSIGN"):
                if self.current and self.current.type == "NEW":
                    self.advance()
                    if self.current and (self.current.type in self.TYPE_KEYWORDS or self.current.type == "IDENTIFIER"):
                        _ = self.current.text; self.advance()
                        _ = self._maybe_generic_suffix(_)
                    while self.current and self.current.type == "LBRACK":
                        self.advance()
                        if self.current and self.current.type != "RBRACK":
                            _ = self.parse_expression()
                        self.match("RBRACK")
                    if self.current and self.current.type == "LBRACE":
                        self.advance()
                        elems = []
                        while self.current and self.current.type != "RBRACE":
                            elems.append(self.parse_expression())
                            if self.current and self.current.type == "COMMA":
                                self.advance()
                        self.match("RBRACE")
                        init = ASTNode("ArrayInit", None, elems)
                    else:
                        init = ASTNode("Unknown", "new-array")
                elif self.current and self.current.type == "LBRACE":
                    self.advance()
                    elems = []
                    while self.current and self.current.type != "RBRACE":
                        elems.append(self.parse_expression())
                        if self.current and self.current.type == "COMMA":
                            self.advance()
                    self.match("RBRACE")
                    init = ASTNode("ArrayInit", None, elems)
                else:
                    init = self.parse_expression()

            fd = ASTNode("FieldDecl", f"{type_tok} {name}", [])
            if init is not None:
                fd.children.append(ASTNode("Init", None, [init]))
            decls.append(fd)

            if self.current and self.current.type == "COMMA":
                self.advance()
                continue
            break

        return decls[0] if len(decls) == 1 else ASTNode("Block", children=decls)

    # --------------- methods ---------------
    def parse_method_declaration(self):
        modifiers = []
        while self.current is not None and self.current.type in self.MODIFIERS:
            modifiers.append(self.current.type); self.advance()

        ret_type = None
        if self.current is not None and (self.current.type in self.TYPE_KEYWORDS or self.current.type == "IDENTIFIER" or self.current.type == "VOID"):
            ret_type = self.current.text; self.advance()
            while self.current is not None and self.current.type == "LBRACK":
                self.advance()
                if self.current and self.current.type == "RBRACK":
                    ret_type = (ret_type or "") + "[]"; self.advance()
        else:
            ret_type = "<unknown>"
            if self.current is not None:
                self.advance()

        if self.current is None:
            raise SyntaxError("Ожидался идентификатор метода, получен EOF")
        method_name = self.current.text
        self.match("IDENTIFIER")

        self.match("LPAREN")
        params = self.parse_parameter_list()
        self.match("RPAREN")

        body = []
        if self.current and self.current.type == "LBRACE":
            body = self.parse_block()

        node = ASTNode("MethodDecl", f"{ret_type} {method_name}", params + body)
        if modifiers:
            node.children.insert(0, ASTNode("Modifiers", ",".join(modifiers)))
        return node

    def parse_parameter_list(self):
        params = []
        while self.current is not None and self.current.type not in ("RPAREN", Token.EOF):
            if self.current.type in self.MODIFIERS:
                self.advance(); continue
            if self.current.type in self.TYPE_KEYWORDS or self.current.type == "IDENTIFIER":
                p_type = self.current.text; self.advance()
                while self.current and self.current.type == "LBRACK":
                    self.advance()
                    if self.current and self.current.type == "RBRACK":
                        p_type = (p_type or "") + "[]"; self.advance()
            else:
                p_type = "<unknown>"; self.advance()
            p_name = None
            name_token = None
            if self.current is not None and self.current.type == "IDENTIFIER":
                name_token = self.current
                p_name = name_token.text
                self.advance()
            params.append(ASTNode("Param", f"{p_type} {p_name}", token=name_token))
            if self.current is not None and self.current.type == "COMMA":
                self.advance(); continue
            else:
                break
        return params

    # --------------- blocks / statements ---------------
    def parse_block(self):
        stmts = []
        if self.current is not None and self.current.type == "LBRACE":
            self.advance()
        else:
            return []
        while self.current is not None and self.current.type not in ("RBRACE", Token.EOF):
            stmts.append(self.parse_statement())
        if self.current is None or self.current.type == Token.EOF:
            raise SyntaxError("Reached EOF while parsing a block — missing '}'")
        self.advance()  # RBRACE
        return stmts

    def _looks_like_local_decl_start(self) -> bool:
        t1 = self._peek_token(1)
        if t1 is None:
            return False
        if t1.type != "IDENTIFIER":
            return False

        i = 2

        # generics <...>
        if self.peek_type(i) == "LT":
            depth = 0
            while True:
                tok = self._peek_token(i)
                if tok is None:
                    return False
                if tok.type == "LT":
                    depth += 1
                elif tok.type == "GT":
                    depth -= 1
                i += 1
                if depth == 0:
                    break

        # массивные []
        while self.peek_type(i) == "LBRACK" and self.peek_type(i + 1) == "RBRACK":
            i += 2

        return self.peek_type(i) == "IDENTIFIER"

    def parse_statement(self):
        if self.current is None:
            return ASTNode("Empty")

        if self.current.type == "IF":
            return self.parse_if_statement()
        if self.current.type == "SWITCH":
            return self.parse_switch_statement()
        if self.current.type == "FOR":
            return self.parse_for_statement()
        if self.current.type == "WHILE":
            return self.parse_while_statement()
        if self.current.type == "DO":
            return self.parse_do_while_statement()
        if self.current.type == "TRY":
            return self.parse_try_statement()
        if self.current.type == "BREAK":
            self.advance()
            if self.current and self.current.type == "SEMI":
                self.advance()
            return ASTNode("Break")
        if self.current.type == "CONTINUE":
            self.advance()
            if self.current and self.current.type == "SEMI":
                self.advance()
            return ASTNode("Continue")
        if self.current.type == "RETURN":
            tok = self.current
            self.advance()
            expr = None
            if self.current and self.current.type != "SEMI":
                expr = self.parse_expression()
            if self.current and self.current.type == "SEMI":
                self.advance()
            return ASTNode("Return", children=[expr] if expr else [], token=tok)
        if self.current.type == "LBRACE":
            stmts = self.parse_block()
            return ASTNode("Block", children=stmts)

        if self.current.type in self.TYPE_KEYWORDS:
            node = self.parse_field_declaration()
            return node

        if self.current.type == "IDENTIFIER" and self._looks_like_local_decl_start():
            node = self.parse_local_variable_declaration_no_semi()
            if self.current and self.current.type == "SEMI":
                self.advance()
            return node

        left = self.parse_expression()

        if self.current is not None and self.current.type == "ASSIGN":
            self.advance()
            right = self.parse_expression()
            node = ASTNode("Assign", None, [left, right])
            if self.current and self.current.type == "SEMI":
                self.advance()
            return node

        compound = {
            "ADD_ASSIGN": "ADD",
            "SUB_ASSIGN": "SUB",
            "MUL_ASSIGN": "MUL",
            "DIV_ASSIGN": "DIV",
            "MOD_ASSIGN": "MOD",
            "AND_ASSIGN": "BITAND",
            "OR_ASSIGN":  "BITOR",
            "XOR_ASSIGN": "CARET",
            "LSHIFT_ASSIGN": "LSHIFT",
            "RSHIFT_ASSIGN": "RSHIFT",
            "URSHIFT_ASSIGN": "URSHIFT",
        }
        if self.current is not None and self.current.type in compound:
            op = compound[self.current.type]
            self.advance()
            rhs = self.parse_expression()
            node = ASTNode("Assign", None, [left, ASTNode("BinaryOp", op, [left, rhs])])
            if self.current and self.current.type == "SEMI":
                self.advance()
            return node

        if self.current and self.current.type == "SEMI":
            self.advance()
        return ASTNode("ExprStmt", None, [left])

    def parse_if_statement(self):
        self.match("IF")
        self.match("LPAREN")
        cond = self.parse_expression()
        self.match("RPAREN")
        then_block = ASTNode("Then", children=self.parse_block())
        else_node = None
        if self.accept("ELSE"):
            if self.current and self.current.type == "IF":
                else_node = self.parse_if_statement()
            elif self.current and self.current.type == "LBRACE":
                else_block_children = self.parse_block()
                else_node = ASTNode("Else", children=else_block_children)
            else:
                else_stmt = self.parse_statement()
                else_node = ASTNode("Else", children=[else_stmt])
        return ASTNode("IfStatement", cond, [then_block] + ([else_node] if else_node else []))

    # --------------- try/catch/finally ---------------
    def parse_try_statement(self):
        self.match("TRY")
        try_block = ASTNode("TryBlock", None, self.parse_block())

        catches = []
        while self.current and self.current.type == "CATCH":
            self.advance()
            self.match("LPAREN")
            ex_type = None
            var_name = None
            if self.current and (self.current.type in self.TYPE_KEYWORDS or self.current.type == "IDENTIFIER"):
                ex_type = self.current.text
                self.advance()
            if self.current and self.current.type == "IDENTIFIER":
                var_name = self.current.text
                self.advance()
            self.match("RPAREN")
            catch_block = self.parse_block()
            catches.append(ASTNode("Catch", f"{ex_type} {var_name}".strip(), catch_block))

        finally_node = None
        if self.accept("FINALLY"):
            finally_block = self.parse_block()
            finally_node = ASTNode("Finally", None, finally_block)

        children = [try_block] + catches + ([finally_node] if finally_node else [])
        return ASTNode("TryStatement", None, children)

    # --------------- expressions ---------------
    def parse_expression(self, min_prec=0):
        left = self.parse_primary()
        while True:
            if self.current is None:
                break
            if self.current.type == "QUESTION":
                self.advance()
                texpr = self.parse_expression()
                self.match("COLON")
                fexpr = self.parse_expression(min_prec)
                left = ASTNode("Ternary", None, [left, texpr, fexpr])
                continue

            op_type = self.current.type
            prec = self.PRECEDENCE.get(op_type, -1)
            if prec < min_prec:
                break
            op_tok = self.current
            self.advance()
            right = self.parse_expression(prec + 1)
            left = ASTNode("BinaryOp", op_tok.type, [left, right])
        return left

    def parse_primary(self):
        if self.current is None:
            return ASTNode("Empty")

        if self.current.type in ("INC", "DEC", "BANG", "ADD", "SUB", "TILDE"):
            op_token = self.current
            op = op_token.type
            self.advance()
            operand = self.parse_primary()
            return ASTNode("PrefixOp", op, [operand], token=op_token)

        if self.current.type == "LPAREN":
            self.advance()
            expr = self.parse_expression()
            self.match("RPAREN")
            return expr

        if self.current.type in ("NUMBER", "STRING", "CHAR"):
            tok = self.current
            val = tok.text
            self.advance()
            return ASTNode("Literal", val, token=tok)

        if self.current.type in ("TRUE", "FALSE", "NULL"):
            tok = self.current
            lit = tok.text
            self.advance()
            return ASTNode("Literal", lit, token=tok)

        if self.current.type in ("IDENTIFIER", "THIS", "SUPER"):
            id_token = self.current
            name = id_token.text.lower() if id_token.type in ("THIS", "SUPER") else id_token.text
            base = ASTNode("Identifier", name, token=id_token)
            self.advance()
            while True:
                if self.current is not None and self.current.type == "DOT":
                    self.advance()
                    if self.current and self.current.type == "IDENTIFIER":
                        member_tok = self.current
                        member_name = member_tok.text
                        self.advance()
                        base = ASTNode("Member", member_name, [base], token=member_tok)
                        continue
                    break
                if self.current is not None and self.current.type == "LPAREN":
                    call_tok = self.current
                    self.advance()
                    args = []
                    if self.current is not None and self.current.type != "RPAREN":
                        args.append(self.parse_expression())
                        while self.current is not None and self.current.type == "COMMA":
                            self.advance()
                            args.append(self.parse_expression())
                    self.match("RPAREN")
                    base = ASTNode("Call", base, args, token=call_tok)
                    continue
                if self.current is not None and self.current.type in ("INC", "DEC"):
                    op_tok = self.current
                    op = op_tok.type
                    self.advance()
                    base = ASTNode("PostfixOp", op, [base], token=op_tok)
                    continue
                break
            return base

        tok = self.current
        token_text = getattr(tok, "text", None)
        token_type = getattr(tok, "type", None)
        self.advance()
        return ASTNode("Unknown", f"{token_type}:{token_text}", token=tok)

    # --------------- while / do-while / for ---------------
    def parse_while_statement(self):
        self.match("WHILE")
        self.match("LPAREN")
        condition = self.parse_expression()
        self.match("RPAREN")
        body = ASTNode("Block", children=self.parse_block())
        return ASTNode("WhileStatement", children=[condition, body])

    def parse_do_while_statement(self):
        self.match("DO")
        body = ASTNode("Block", children=self.parse_block())
        self.match("WHILE")
        self.match("LPAREN")
        condition = self.parse_expression()
        self.match("RPAREN")
        if self.current and self.current.type == "SEMI":
            self.advance()
        return ASTNode("DoWhileStatement", children=[condition, body])

    def parse_for_statement(self):
        self.match("FOR")
        self.match("LPAREN")

        lookahead_index = 1
        found_colon = False
        while True:
            t = self.tokens.LT(lookahead_index)
            if t is None:
                break
            if t.type == "COLON":
                found_colon = True
                break
            if t.type == "SEMI" or t.type == "RPAREN":
                break
            lookahead_index += 1

        if found_colon:
            first_type = None
            if self.current.type in self.TYPE_KEYWORDS or self.current.type == "IDENTIFIER":
                first_type = self.current.text; self.advance()
                while self.current and self.current.type == "LBRACK":
                    self.advance()
                    if self.current and self.current.type == "RBRACK":
                        first_type = (first_type or "") + "[]"; self.advance()
            var_name = None
            name_token = None
            if self.current.type == "IDENTIFIER":
                name_token = self.current
                var_name = name_token.text
                self.advance()
            self.match("COLON")
            collection_expr = self.parse_expression()
            self.match("RPAREN")
            body = ASTNode("Block", children=self.parse_block())
            var_node = ASTNode("Param", f"{first_type} {var_name}", token=name_token)
            return ASTNode("ForStatement", children=[var_node, collection_expr, body])

        init = None
        if self.current.type != "SEMI":
            if self.current.type in self.TYPE_KEYWORDS:
                init = self.parse_local_variable_declaration_no_semi()
            else:
                init = self.parse_expression()
        if self.current and self.current.type == "SEMI":
            self.advance()
        else:
            raise SyntaxError("Ожидался ';' в заголовке for")
        condition = None
        if self.current.type != "SEMI":
            condition = self.parse_expression()
        if self.current and self.current.type == "SEMI":
            self.advance()
        else:
            raise SyntaxError("Ожидался ';' в заголовке for (между условием и обновлением)")
        update = None
        if self.current.type != "RPAREN":
            update = self.parse_expression()
        self.match("RPAREN")
        body = ASTNode("Block", children=self.parse_block())
        return ASTNode("ForStatement", children=[init, condition, update, body])

    # --------------- switch ---------------
    def parse_switch_statement(self):
        self.match("SWITCH")
        self.match("LPAREN")
        expr = self.parse_expression()
        self.match("RPAREN")
        if self.current and self.current.type == "LBRACE":
            self.advance()
        cases = []
        while self.current is not None and self.current.type not in ("RBRACE", Token.EOF):
            if self.current.type == "CASE":
                self.advance()
                case_val = self.parse_expression()
                if self.current and self.current.type == "COLON":
                    self.advance()
                stmts = []
                while self.current is not None and self.current.type not in ("CASE", "DEFAULT", "RBRACE"):
                    stmts.append(self.parse_statement())
                cases.append(ASTNode("CaseLabel", None, [case_val] + stmts))
            elif self.current.type == "DEFAULT":
                self.advance()
                if self.current and self.current.type == "COLON":
                    self.advance()
                stmts = []
                while self.current is not None and self.current.type not in ("CASE", "DEFAULT", "RBRACE"):
                    stmts.append(self.parse_statement())
                cases.append(ASTNode("DefaultLabel", None, stmts))
            else:
                self.advance()
        if self.current and self.current.type == "RBRACE":
            self.advance()
        return ASTNode("SwitchStatement", None, [expr] + cases)
