import io
import tempfile
from pathlib import Path
import streamlit as st

from FileStream.FileStream import FileStream
from JavaGrammarLexer.JavaGrammarLexer import JavaGrammarLexer
from TokenStream.TokenStream import TokenStream
from SimpleJavaParser.SimpleJavaParser import SimpleJavaParser, ASTNode
from Translator.Translator import Translator, INDENT_STR


def _read_uploaded_bytes_as_text(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    raw = uploaded_file.read()
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("latin-1", errors="replace")


def translate_java_to_python(java_code: str, indent: str = INDENT_STR) -> tuple[str, ASTNode]:
    if not java_code or "class" not in java_code:
        raise ValueError("В коде не найдено объявление класса (ключевое слово 'class').")

    with tempfile.NamedTemporaryFile("w", suffix=".java", delete=False, encoding="utf-8") as tmp:
        tmp.write(java_code)
        tmp_path = Path(tmp.name)

    try:
        input_stream = FileStream(str(tmp_path))
        lexer = JavaGrammarLexer(input_stream)
        tokens = TokenStream(lexer)
        parser = SimpleJavaParser(tokens)
        ast = parser.parse()

        t = Translator(indent_str=indent)
        python_code = t.translate(ast)
        return python_code, ast
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


st.set_page_config(page_title="Java → Python Translator", layout="wide")

st.markdown(
    """
    <style>
    textarea {
        -webkit-text-size-adjust: 100%;
        spellcheck: false !important;
    }
    textarea[spellcheck] {
        spellcheck: false !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Java → Python Translator")


if "java_code" not in st.session_state:
    st.session_state.java_code = ""

if "python_code" not in st.session_state:
    st.session_state.python_code = ""

if "show_result" not in st.session_state:
    st.session_state.show_result = False

if "ast_repr" not in st.session_state:
    st.session_state.ast_repr = ""

if "last_error" not in st.session_state:
    st.session_state.last_error = ""


with st.sidebar:
    st.subheader("Настройки")

    indent_choice = st.selectbox(
        "Отступы",
        options=[
            "    (4 пробела)",
            "  (2 пробела)",
            "\t (таб)",
        ],
        index=0,
    )
    if indent_choice.startswith("    "):
        indent_str = "    "
    elif indent_choice.startswith("  "):
        indent_str = "  "
    else:
        indent_str = "\t"

    show_ast = st.checkbox("Показать AST (debug)", value=False)

    st.markdown("---")
    st.caption("Загрузка/сохранение")



st.markdown("#### Загрузите .java")
uploaded_file = st.file_uploader("Файл Java", type=["java"], key="upload_java_file")

if uploaded_file is not None:
    text_from_file = _read_uploaded_bytes_as_text(uploaded_file)
    if text_from_file and text_from_file != st.session_state.java_code:
        st.session_state.java_code = text_from_file


st.markdown("#### Или вставьте Java-код вручную")
java_code_input = st.text_area(
    label="Исходный Java-код",
    key="java_code",
    height=260,
    placeholder=(
        'Пример:\n'
        'public class Hello {\n'
        '    public static void main(String[] a){\n'
        '        System.out.println("hi");\n'
        '    }\n'
        '}'
    ),
)


col_left, col_right = st.columns([1, 1])

with col_left:
    run = st.button("Translate", type="primary")

    if run:
        st.session_state.last_error = ""
        try:
            py_code, ast = translate_java_to_python(st.session_state.java_code, indent=indent_str)
            st.session_state.python_code = py_code
            st.session_state.show_result = True
            st.session_state.ast_repr = ast.__repr__() if show_ast and ast is not None else ""
            st.success("✅ Success!")
        except Exception as e:
            st.session_state.last_error = str(e)
            st.session_state.show_result = False
            st.session_state.python_code = ""
            st.session_state.ast_repr = ""

    if st.session_state.show_result and st.session_state.python_code:
        st.subheader("Python:")
        st.code(st.session_state.python_code, language="python")

        st.download_button(
            label="Скачать translated.py",
            data=st.session_state.python_code,
            file_name="translated.py",
            mime="text/x-python",
            use_container_width=True,
        )

        if show_ast and st.session_state.ast_repr:
            with st.expander("AST (debug)", expanded=False):
                st.text(st.session_state.ast_repr)

    if st.session_state.last_error:
        st.error(f"❌ Ошибка перевода: {st.session_state.last_error}")

with col_right:
    with st.expander("ℹ️ Примечания", expanded=True):
        st.markdown(
            """
- Поддерживаются классы, методы, конструкторы, поля, `if / for / while / do-while / switch`, `try / catch / finally`.
- Нестатические поля переносятся в `__init__` как `self.field`, статические остаются на уровне класса.
- `System.out.println()` и `System.out.print()` преобразуются в `print()` (соответственно с/без `end=''`).
- Типы конвертируются в аннотации Python (`int`, `bool`, `str`, `list[T]`, `dict[K, V]`, `Optional[T]`).
- Требуется Python **3.10+** (используется `match-case`).
            """
        )

st.caption("© FEFU Software engineering")
