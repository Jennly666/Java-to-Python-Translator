# Java-to-Python Translator

Инструмент для преобразования подмножества языка **Java** в **Python-код**.  
Проект реализует минимальный, но цельный компилятор высокого уровня: от токенизации до семантического анализа, оптимизации AST и генерации кода.

---

## 1. Архитектура

```text
Java source (.java)
   ↓
FileStream / InputStream      — чтение исходника
   ↓
JavaGrammarLexer / Lexer      — токенизация
   ↓
TokenStream                   — управление токенами (lookahead, consume)
   ↓
SimpleJavaParser              — синтаксический анализ и построение AST
   ↓
SemanticAnalyzer              — таблицы символов и семантические проверки
   ↓
AstOptimizer                  — локальная оптимизация и свёртка констант в AST
   ↓
Translator                    — обход AST и генерация Python-кода
   ↓
Python source (.py)
````

**Пример использования:**

```python
from FileStream import FileStream
from JavaGrammarLexer import JavaGrammarLexer
from TokenStream import TokenStream
from SimpleJavaParser import SimpleJavaParser
from SemanticAnalyzer import SemanticAnalyzer
from AstOptimizer import AstOptimizer
from Translator import Translator

input_stream = FileStream("Example.java")
lexer = JavaGrammarLexer(input_stream)
tokens = TokenStream(lexer)

parser = SimpleJavaParser(tokens)
ast = parser.parse()

sem = SemanticAnalyzer()
errors = sem.analyze(ast) or []
for e in errors:
    print(e)

optimizer = AstOptimizer()
ast = optimizer.optimize(ast)

t = Translator()
python_code = t.translate(ast)
print(python_code)
```

---

## 2. Основные компоненты

### **ASTNode**

Универсальный узел абстрактного синтаксического дерева, представляющий конструкции Java.

Содержит:

* `type` — тип конструкции (`CompilationUnit`, `ClassDecl`, `MethodDecl`, `ConstructorDecl`, `FieldDecl`, `IfStatement`, `ForStatement`, `SwitchStatement`, `BinaryOp`, `Literal`, `Identifier` и др.);
* `value` — текстовое значение (имя класса/метода/поля, оператор, литерал и т.д.);
* `children` — список дочерних узлов.

---

### **SimpleJavaParser**

Рекурсивный нисходящий парсер, формирующий AST по потоку токенов.

**Поддерживаемые элементы:**

* объявления классов, конструкторов, методов и полей;
* управляющие конструкции:
  `if / else`, `while`, `do-while`,
  классический `for(init; cond; update)`,
  расширенный `for (Type x : collection)`,
  `switch`, `try / catch / finally`, `break`, `continue`;
* выражения: вызовы методов, доступ к полям, бинарные и унарные операции (в т.ч. `++`, `--`), тернарный оператор, литералы, массивы и простые коллекции.

**Особенности:**

* различает объявления и присваивания;
* поддерживает массивные типы (`String[] args`) и базовые generics в сигнатурах;
* обрабатывает модификаторы (`public`, `private`, `static`, `final` и др.);
* множества объявлений (`int a = 1, b = 2;`) разбираются в виде отдельных `FieldDecl`.

---

### **SemanticAnalyzer**

Выполняет семантический проход по AST после синтаксического анализа.

**Модель данных:**

* `ClassInfo` — сведения о классе (имя, поля, методы, базовый класс);
* `MethodInfo` — имя, тип результата и список типов параметров;
* `VarInfo` — тип и имя переменной (поле, параметр или локальная переменная);
* `Scope` — область видимости с ссылкой на родителя и локальной таблицей переменных.

**Основные проверки:**

* использование необъявленных идентификаторов;
* повторное объявление локальных переменных и параметров;
* несовпадение типов при инициализации и присваивании;
* тип условий в `if`, `while`, `do-while`, `for` (только `boolean`);
* корректность `++` / `--` (только числовые типы);
* вызовы методов: существование метода, число и типы аргументов;
* тернарный оператор `?:` (булево условие, согласованные типы веток);
* `switch`: тип выражения и меток `case`, запрет `switch` по `boolean`;
* поведение `this` / `super` в статических контекстах;
* `System.out.print/println` допускаются без ошибок как особый случай.

Семантические ошибки **не блокируют** генерацию кода: Python-файл всё равно формируется по исходному AST.

---

### **AstOptimizer**

Модуль локальной оптимизации, работающий между `SemanticAnalyzer` и `Translator`.

**Реализованные приёмы:**

* свёртка констант в арифметических и логических выражениях (`2 + 3 * 4 → 14`, `true && false → false`);
* свёртка унарных операторов над константами (`-(1 + 2) → -3`, `!true → false`);
* упрощение тернарного оператора с константным условием (`true ? a : b → a`);
* простые алгебраические и булевы упрощения (`x + 0 → x`, `1 * x → x`, `true && p → p`, `false || p → p`).

Оптимизации **не удаляют** операторы присваивания и вызовы методов и не меняют структуру управляющих конструкций.

---

### **Translator**

Формирует читаемый Python-код по AST, максимально сохраняя семантику Java.

**Основные принципы:**

* классы → `class` в Python;
* конструкторы → `__init__`; при нескольких конструкторах — объединение в один с параметрами по умолчанию;
* методы:

  * нестатические → `def method(self, ...)`;
  * статические → `@staticmethod` + `def method(...)`;
* `this` → `self`, вызовы `this(...)` / `super(...)` в конструкторах → `self.__init__(...)` / `super().__init__(...)`;
* `System.out.print/println` → `print(..., end="")` / `print(...)`;
* `switch` → `match expr: case ...: ... case _:` (Python 3.10+);
* `try / catch / finally` → `try / except / finally`.

**Поля:**

* нестатические — инициализируются в `__init__` как `self.field`;
* статические — выводятся на уровне класса.

---

## 3. Маппинг типов и значений

| Java тип         | Python эквивалент | Значение по умолчанию |
| ---------------- | ----------------- | --------------------- |
| `int`            | `int`             | `0`                   |
| `float`/`double` | `float`           | `0.0`                 |
| `boolean`        | `bool`            | `False`               |
| `char`           | `str`             | `""`                  |
| `String`         | `str`             | `""`                  |
| `T[]`            | `list[T]`         | `[]`                  |
| `List<T>`        | `list[T]`         | `[]`                  |
| `Map<K,V>`       | `dict[K, V]`      | `{}`                  |
| `void`           | `None`            | —                     |

---

## 4. Примеры преобразований

### Класс с конструктором

**Java**

```java
public class Foo {
    private int x;
    public Foo(int x) {
        this.x = x;
    }
}
```

**Python**

```python
class Foo:
    def __init__(self, x: int):
        self.x: int = x
```

---

### Циклы и условия

**Java**

```java
for (int i = 0; i < 3; i++) {
    System.out.println(i);
}
```

**Python**

```python
for i in range(0, 3):
    print(i)
```

---

### Switch и try/catch

**Java**

```java
switch (x) {
    case 1: System.out.println("one"); break;
    default: System.out.println("other");
}
```

**Python**

```python
match x:
    case 1:
        print("one")
    case _:
        print("other")
```

---

## 5. Пример комплексной трансляции

**Java**

```java
public class Counter {
    private int value;

    public Counter(int start) { 
        this.value = start; 
    }

    public void inc() { 
        value++; 
    }

    public int get() { 
        return value; 
    }
}
```

**Python**

```python
class Counter:
    def __init__(self, start: int):
        self.value: int = start

    def inc(self) -> None:
        self.value += 1

    def get(self) -> int:
        return self.value
```

---

## 6. Ограничения

* не поддерживаются: `interface`, `enum`, аннотации, лямбда-выражения, `instanceof`;
* generics обрабатываются синтаксически, без полноценного вывода типов;
* модификаторы доступа (`private`, `protected`) не учитываются при генерации кода;
* требуется **Python 3.10+** (используется `match-case`);
* часть сложных контекстных условий (особенно для расширенных ссылочных типов) остаётся на ответственности Java-компилятора и разработчика.
