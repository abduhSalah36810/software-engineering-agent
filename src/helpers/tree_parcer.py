from tree_sitter import Language, Parser

import tree_sitter_python as ts_python
import tree_sitter_javascript as ts_javascript
import tree_sitter_typescript as ts_typescript
import tree_sitter_java as ts_java
import tree_sitter_cpp as ts_cpp
import tree_sitter_c_sharp as ts_c_sharp
import tree_sitter_go as ts_go
import tree_sitter_rust as ts_rust
import tree_sitter_php as ts_php


class CodeParser:

    def __init__(self):
        self.languages = {
            "python": Language(ts_python.language()),
            "javascript": Language(ts_javascript.language()),
            "typescript": Language(ts_typescript.language_typescript()),
            "java": Language(ts_java.language()),
            "cpp": Language(ts_cpp.language()),
            "csharp": Language(ts_c_sharp.language()),
            "go": Language(ts_go.language()),
            "rust": Language(ts_rust.language()),
            "php": Language(ts_php.language_php()),
        }
        self.parsers = {
            lang: Parser(lang_obj)
            for lang, lang_obj in self.languages.items()
        }

    def parse(self, code: str | bytes, language: str):
        if language not in self.languages:
            raise ValueError(f"Unsupported language: {language}")

        if language not in self.parsers:
            self.parsers[language] = Parser(self.languages[language])

        if isinstance(code, str):
            code_bytes = code.encode("utf-8")
        else:
            code_bytes = code

        return self.parsers[language].parse(code_bytes)
