"""测试模型提供者抽象层"""

import sys
import unittest

sys.path.insert(0, "f:/CodeFile/AI_Diet_Assistant/ai_core")

from models.base import init_providers, get_provider, list_providers


class TestProviderRegistry(unittest.TestCase):
    """测试 provider 注册与查找"""

    @classmethod
    def setUpClass(cls):
        init_providers()

    def test_all_providers_registered(self):
        """三个 provider 都已注册"""
        providers = list_providers()
        self.assertIn("ollama:", providers)
        self.assertIn("deepseek:", providers)
        self.assertIn("llamacpp:", providers)

    def test_get_ollama_provider(self):
        provider = get_provider("ollama:deepseek-r1:7b")
        self.assertEqual(provider.key_prefix(), "ollama:")

    def test_get_deepseek_provider(self):
        provider = get_provider("deepseek:deepseek-chat")
        self.assertEqual(provider.key_prefix(), "deepseek:")

    def test_get_llamacpp_provider(self):
        provider = get_provider("llamacpp:")
        self.assertEqual(provider.key_prefix(), "llamacpp:")

    def test_unsupported_model_raises(self):
        with self.assertRaises(ValueError):
            get_provider("unknown:model")


if __name__ == "__main__":
    unittest.main()
