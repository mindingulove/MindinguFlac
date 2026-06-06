import unittest

import gemini_proxy


class TestGeminiProxy(unittest.TestCase):
    def test_compose_prompt_prefers_messages(self):
        prompt = "Raw prompt"
        messages = [
            {"role": "system", "content": "Return only JSON."},
            {"role": "user", "content": "Rank these candidates."},
        ]
        composed = gemini_proxy._compose_prompt(prompt, messages)
        self.assertIn("Return only JSON.", composed)
        self.assertIn("Rank these candidates.", composed)
        self.assertNotIn("Raw prompt", composed)


if __name__ == "__main__":
    unittest.main()
