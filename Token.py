from io import StringIO
from typing import Optional, Tuple


class Token(object):
    __slots__ = ('source', 'type', 'channel', 'start', 'stop', 'tokenIndex', 'line', 'column', '_text')

    INVALID_TYPE = 0
    EPSILON = -2
    MIN_USER_TOKEN_TYPE = 1
    EOF = -1

    DEFAULT_CHANNEL = 0
    HIDDEN_CHANNEL = 1

    def __init__(self):
        self.source: Optional[Tuple] = None
        self.type: Optional[int] = None
        self.channel: Optional[int] = None
        self.start: Optional[int] = None
        self.stop: Optional[int] = None
        self.tokenIndex: Optional[int] = None
        self.line: Optional[int] = None
        self.column: Optional[int] = None
        self._text: Optional[str] = None

    @property
    def text(self) -> Optional[str]:
        return self._text

    @text.setter
    def text(self, text: Optional[str]) -> None:
        self._text = text

    def getTokenSource(self):
        return self.source[0] if self.source else None

    def getInputStream(self):
        return self.source[1] if self.source else None


class CommonToken(Token):
    EMPTY_SOURCE = (None, None)

    def __init__(self, source: tuple = EMPTY_SOURCE, type: int = None, channel: int = Token.DEFAULT_CHANNEL, start: int = -1, stop: int = -1):
        super().__init__()
        self.source = source
        self.type = type
        self.channel = channel
        self.start = start
        self.stop = stop
        self.tokenIndex = -1
        if source[0] is not None:
            self.line = getattr(source[0], "line", None)
            self.column = getattr(source[0], "column", -1)
        else:
            self.line = None
            self.column = -1

    def clone(self):
        t = CommonToken(self.source, self.type, self.channel, self.start, self.stop)
        t.tokenIndex = self.tokenIndex
        t.line = self.line
        t.column = self.column
        t.text = self.text
        return t

    @property
    def text(self) -> Optional[str]:
        if self._text is not None:
            return self._text
        input_stream = self.getInputStream()
        if input_stream is None:
            return None
        if self.start is None or self.stop is None:
            return None
        n = input_stream.size
        if 0 <= self.start < n and 0 <= self.stop < n:
            return input_stream.getText(self.start, self.stop)
        return "<EOF>"

    @text.setter
    def text(self, text: Optional[str]) -> None:
        self._text = text

    def __str__(self) -> str:
        with StringIO() as buf:
            buf.write("[@")
            buf.write(str(self.tokenIndex))
            buf.write(",")
            buf.write(str(self.start))
            buf.write(":")
            buf.write(str(self.stop))
            buf.write("='")
            txt = self.text
            if txt is not None:
                txt = txt.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            else:
                txt = "<no text>"
            buf.write(txt)
            buf.write("',<")
            buf.write(str(self.type))
            buf.write(">")
            if self.channel is not None and self.channel > 0:
                buf.write(",channel=")
                buf.write(str(self.channel))
            buf.write(",")
            buf.write(str(self.line))
            buf.write(":")
            buf.write(str(self.column))
            buf.write("]")
            return buf.getvalue()
        

class CommonTokenFactory:

    DEFAULT = None
    
    def create(self, source, type_, text, channel, start, stop, line, column):
        t = CommonToken(source, type_, channel, start, stop)
        t._text = text
        t.line = line
        t.column = column
        return t


CommonTokenFactory.DEFAULT = CommonTokenFactory()
