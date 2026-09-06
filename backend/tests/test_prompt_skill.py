# tests/test_prompt_skill.py —— 独立 prompt 加载与 skill 注册单测
from app import prompt_loader, skill_registry


class _Template:
    def __init__(self, type_id, gen_prompt):
        self.type_id = type_id
        self.gen_prompt = gen_prompt


class TestPromptLoader:
    def test_load_prompt_reads_st_file(self):
        text = prompt_loader.load_prompt("single_choice-system.st")
        assert "教研员" in text

    def test_load_prompt_strips_prefix(self):
        assert prompt_loader.load_prompt("prompts/reading-user.st") == (
            prompt_loader.load_prompt("reading-user.st")
        )

    def test_render_replaces_placeholders(self):
        out = prompt_loader.render("知识点：{{kp}}；难度：{{diff}}", {"kp": "语法", "diff": "易"})
        assert out == "知识点：语法；难度：易"

    def test_render_keeps_missing_placeholder(self):
        out = prompt_loader.render("x={{a}}", {})
        assert out == "x={{a}}"

    def test_build_user_prompt_appends_rag(self):
        tpl = _Template("single_choice", {"user": "single_choice-user.st"})
        out = prompt_loader.build_user_prompt(
            tpl, {"knowledge_point": "时态", "rag_context": "参考资料X"}
        )
        assert "时态" in out
        assert "参考资料X" in out

    def test_build_system_prompt_injects_skill(self):
        tpl = _Template("single_choice", {"system": "single_choice-system.st"})
        out = prompt_loader.build_system_prompt(tpl, {}, skill_md="出题技能规范内容")
        assert "出题技能规范" in out
        assert "出题技能规范内容" in out


class TestSkillRegistry:
    def test_get_skill_md_exact_match(self):
        md = skill_registry.get_skill_md("single_choice")
        assert "单选题" in md

    def test_get_skill_md_falls_back_to_generate_question(self):
        md = skill_registry.get_skill_md("unknown_type")
        assert "通用" in md or "英语教研员" in md

    def test_skill_meta_yml_loads(self):
        import os

        import yaml

        path = os.path.join(skill_registry.SKILLS_DIR, "single_choice", "skill.meta.yml")
        data = yaml.safe_load(open(path, encoding="utf-8"))
        assert data["displayName"]
        assert data["categories"][0]["key"]
