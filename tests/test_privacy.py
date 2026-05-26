"""测试隐私模糊模块"""

import json
import sys
import unittest

sys.path.insert(0, "f:/CodeFile/AI_Diet_Assistant/ai_core")

from privacy import blur_personal_info, blur_profile_text


class TestBlurPersonalInfo(unittest.TestCase):
    """测试 blur_personal_info"""

    def test_blurs_age_to_range(self):
        """具体年龄（28）→ 年龄段（25-29岁）"""
        result = json.loads(blur_personal_info('{"age": 28}'))
        self.assertEqual(result.get("age_range"), "25-29岁")
        self.assertNotIn("age", result)

    def test_blurs_age_young(self):
        """23岁 → 20-24岁"""
        result = json.loads(blur_personal_info('{"age": 23}'))
        self.assertEqual(result.get("age_range"), "20-24岁")

    def test_blurs_bmi_normal(self):
        """身高175cm、体重70kg → BMI 正常"""
        result = json.loads(blur_personal_info('{"age": 28, "height": 175, "weight": 70}'))
        self.assertEqual(result.get("body_type"), "正常")
        self.assertNotIn("height", result)
        self.assertNotIn("weight", result)

    def test_blurs_bmi_underweight(self):
        bmi_under = blur_personal_info(json.dumps({"age": 25, "height": 175, "weight": 50}))
        result = json.loads(bmi_under)
        self.assertEqual(result.get("body_type"), "偏瘦")

    def test_blurs_bmi_overweight(self):
        result = json.loads(blur_personal_info(json.dumps({"age": 30, "height": 170, "weight": 80})))
        self.assertEqual(result.get("body_type"), "超重")

    def test_blurs_bmi_obese(self):
        result = json.loads(blur_personal_info(json.dumps({"age": 35, "height": 160, "weight": 90})))
        self.assertEqual(result.get("body_type"), "肥胖")

    def test_handles_invalid_input(self):
        """无效输入应原样返回"""
        self.assertEqual(blur_personal_info("not json"), "not json")
        self.assertEqual(blur_personal_info(""), "")

    def test_handles_empty_dict(self):
        result = blur_personal_info("{}")
        self.assertIn("{}", result)


class TestBlurProfileText(unittest.TestCase):
    """测试 blur_profile_text"""

    def test_blurs_age_in_text(self):
        """28岁 → 20多岁"""
        self.assertEqual(blur_profile_text("用户28岁"), "用户20多岁")

    def test_blurs_age_bracket(self):
        """35岁 → 30多岁"""
        self.assertEqual(blur_profile_text("35岁男性"), "30多岁男性")

    def test_removes_height(self):
        """删除身高精确数值"""
        self.assertEqual(blur_profile_text("身高175cm，其他正常"), "其他正常")

    def test_removes_weight(self):
        """删除体重精确数值"""
        self.assertEqual(blur_profile_text("体重70kg，建议"), "建议")

    def test_empty_input(self):
        self.assertEqual(blur_profile_text(""), "")
        self.assertEqual(blur_profile_text(None), "")


if __name__ == "__main__":
    unittest.main()
