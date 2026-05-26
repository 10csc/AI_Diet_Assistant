"""测试 RAG 模块导入"""

import sys
import unittest

sys.path.insert(0, "f:/CodeFile/AI_Diet_Assistant/ai_core")


class TestRagImports(unittest.TestCase):
    """验证 nutrition_kb 拆分后导入正常"""

    def test_import_rag_functions(self):
        from rag import build_rag_context, build_secondary_prompt, format_local_analysis
        self.assertTrue(callable(build_rag_context))
        self.assertTrue(callable(build_secondary_prompt))
        self.assertTrue(callable(format_local_analysis))

    def test_import_sub_modules(self):
        from rag import knowledge_rules, data_loader, embedder, retriever, profile_builder
        self.assertTrue(hasattr(knowledge_rules, "TERM_KEYWORDS"))
        self.assertTrue(hasattr(knowledge_rules, "SEASON_RULES"))

    def test_knowledge_rules_constants(self):
        from rag.knowledge_rules import (
            TERM_KEYWORDS, SEASON_RULES, IMAGE_CATEGORY_RULES
        )
        self.assertGreater(len(TERM_KEYWORDS), 0)
        self.assertEqual(len(SEASON_RULES), 4)
        self.assertGreater(len(IMAGE_CATEGORY_RULES), 0)


if __name__ == "__main__":
    unittest.main()
