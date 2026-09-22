from tree_sitter import Query, QueryCursor, Parser
from src.helpers.code_document import CodeDocument


class SymbolExtractor:

    QUERIES = {
        "python": """
        (class_definition name: (identifier) @name) @definition.class
        (function_definition name: (identifier) @name) @definition.function
        """,
        "javascript": """
        (class_declaration name: (identifier) @name) @definition.class
        (function_declaration name: (identifier) @name) @definition.function
        (method_definition name: (property_identifier) @name) @definition.method
        """,
        "typescript": """
        (class_declaration name: (type_identifier) @name) @definition.class
        (function_declaration name: (identifier) @name) @definition.function
        (method_definition name: (property_identifier) @name) @definition.method
        (interface_declaration name: (type_identifier) @name) @definition.interface
        (type_alias_declaration name: (type_identifier) @name) @definition.type
        """,
        "java": """
        (class_declaration name: (identifier) @name) @definition.class
        (interface_declaration name: (identifier) @name) @definition.interface
        (enum_declaration name: (identifier) @name) @definition.enum
        (method_declaration name: (identifier) @name) @definition.method
        """,
        "cpp": """
        (class_specifier name: (type_identifier) @name) @definition.class
        (struct_specifier name: (type_identifier) @name) @definition.struct
        (function_definition declarator: (function_declarator declarator: (identifier) @name)) @definition.function
        """,
        "csharp": """
        (class_declaration name: (identifier) @name) @definition.class
        (interface_declaration name: (identifier) @name) @definition.interface
        (struct_declaration name: (identifier) @name) @definition.struct
        (enum_declaration name: (identifier) @name) @definition.enum
        (method_declaration name: (identifier) @name) @definition.method
        """,
        "go": """
        (type_declaration (type_spec name: (type_identifier) @name)) @definition.type
        (function_declaration name: (identifier) @name) @definition.function
        (method_declaration name: (field_identifier) @name) @definition.method
        """,
        "rust": """
        (struct_item name: (type_identifier) @name) @definition.struct
        (enum_item name: (type_identifier) @name) @definition.enum
        (trait_item name: (type_identifier) @name) @definition.trait
        (function_item name: (identifier) @name) @definition.function
        (impl_item type: (type_identifier) @name) @definition.implementation
        """,
        "php": """
        (class_declaration name: (name) @name) @definition.class
        (interface_declaration name: (name) @name) @definition.interface
        (method_declaration name: (name) @name) @definition.method
        (function_definition name: (name) @name) @definition.function
        """
    }

    def __init__(self, parser):
        self.code_parser = parser
        self.languages = parser.languages
        self.queries = {}

        for language, query_source in self.QUERIES.items():
            if language not in self.languages:
                continue
            
            lang_obj = self.languages[language]
            try:
                self.queries[language] = (lang_obj, query_source)
            except Exception as e:
                print(f"⚠️ Failed to configure Tree-sitter query for {language}: {e}")

    def extract(self, code: str, file_path: str, language: str) -> list[CodeDocument]:
        if language not in self.queries:
            return []

        try:
            code_bytes = code.encode("utf-8")
            lang_obj, query_source = self.queries[language]

            parser = Parser(lang_obj)
            tree = parser.parse(code_bytes)
            query = Query(lang_obj, query_source)
            cursor = QueryCursor(query)

            try:
                captures_dict = cursor.captures(tree.root_node)
            except Exception as e:
                print(f"⚠️ Warning: QueryCursor captures failed for {file_path}: {e}")
                return []

            extracted_symbols = []

            for capture_name, nodes in captures_dict.items():
                if not capture_name.startswith("definition."):
                    continue

                symbol_type = capture_name.split(".", 1)[1]

                for node in nodes:
                    try:
                        name_node = node.child_by_field_name("name")
                        if not name_node:
                            for child in node.children:
                                if "identifier" in child.type or child.type == "name":
                                    name_node = child
                                    break

                        if not name_node:
                            continue

                        name_start = int(name_node.start_byte)
                        name_end = int(name_node.end_byte)
                        symbol_name = code_bytes[name_start:name_end].decode("utf-8", errors="replace")

                        start_row = int(node.start_point[0])
                        end_row = int(node.end_point[0])
                        start_byte = int(node.start_byte)
                        end_byte = int(node.end_byte)

                        extracted_symbols.append({
                            "type": symbol_type,
                            "name": symbol_name,
                            "start_row": start_row,
                            "end_row": end_row,
                            "start_byte": start_byte,
                            "end_byte": end_byte
                        })
                    except Exception:
                        continue

            documents = []
            for sym in extracted_symbols:
                parent_name = self._find_parent_symbol_by_range(sym, extracted_symbols)
                content = code_bytes[sym["start_byte"]:sym["end_byte"]].decode("utf-8", errors="replace")

                document = CodeDocument(
                    file=file_path,
                    language=language,
                    symbol=sym["name"],
                    type=sym["type"],
                    parent=parent_name,
                    start_line=sym["start_row"] + 1,
                    end_line=sym["end_row"] + 1,
                    content=content
                )
                documents.append(document)

            return documents

        except Exception as e:
            print(f"⚠️ Warning: Symbol extraction error in file {file_path} ({language}): {e}")
            return []

    def _find_parent_symbol_by_range(self, target_sym: dict, all_symbols: list[dict]) -> str | None:
        best_parent = None
        min_size = float("inf")

        target_start = target_sym["start_byte"]
        target_end = target_sym["end_byte"]

        for sym in all_symbols:
            if sym["type"] not in {"class", "struct", "interface", "enum", "trait"}:
                continue

            if (sym["start_byte"] <= target_start and 
                sym["end_byte"] >= target_end and 
                sym["start_byte"] != target_start):

                size = sym["end_byte"] - sym["start_byte"]
                if size < min_size:
                    min_size = size
                    best_parent = sym["name"]

        return best_parent
