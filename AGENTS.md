# nai_pic_plugin

NovelAI 画图能力的 MaiBot 插件，包含 `sdk_runtime.py`（SDK runtime）与 `plugin.py`（动作/命令分发）。

## Agent skills

### Issue tracker

议题与 PRD 都走 GitHub Issues（仓库：`saberlights/nai_pic_plugin`），统一使用 `gh` CLI。详见 `docs/agents/issue-tracker.md`。

### Triage labels

使用五个标准分诊标签（`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`），未做改名。详见 `docs/agents/triage-labels.md`。

### Domain docs

单一上下文（single-context）：根目录一个 `CONTEXT.md` 配一个 `docs/adr/`。详见 `docs/agents/domain.md`。
