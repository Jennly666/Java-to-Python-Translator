class TokenStream:
    def __init__(self, lexer):
        self.lexer = lexer
        self.tokens = []
        self.pos = 0
        self._fill_tokens()

    def _fill_tokens(self):
        while True:
            tok = self.lexer.nextToken()
            if getattr(tok, "channel", 0) == 1:  # Token.HIDDEN_CHANNEL
                continue
            self.tokens.append(tok)
            if tok.type == tok.EOF:
                break

    def LT(self, k: int):
        index = self.pos + k - 1
        if 0 <= index < len(self.tokens):
            return self.tokens[index]
        return self.tokens[-1]  # EOF fallback

    def consume(self):
        if self.pos < len(self.tokens) - 1:
            self.pos += 1

    def LA(self, k: int):
        return self.LT(k).type
