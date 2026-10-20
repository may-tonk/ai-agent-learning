"""提示词加载：提示词放在 prompts/*.md 里，和代码分开。

真实项目这样做的原因：提示词会频繁调整，单独成文件方便对比修改记录（git diff 一眼看出改了哪句），
也方便不写代码的同事（产品、运营）参与修改。代码里只负责把变量填进去。
"""
import config


def build_system_prompt(data_access):
    template = (config.PROMPTS_DIR / "system.md").read_text(encoding="utf-8")
    # 模板里的 {data_access} 会被替换；示例 JSON 里的花括号写成了 {{ }}，format 之后变回 { }
    return template.format(data_access=data_access)


def build_task(claim_id):
    return f"请审核报销单 {claim_id}。"
