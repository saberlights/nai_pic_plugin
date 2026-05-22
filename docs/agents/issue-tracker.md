# 议题跟踪：GitHub

本仓库的 issue 与 PRD 全部落在 GitHub Issues 上（`saberlights/nai_pic_plugin`），统一使用 `gh` CLI。

## 约定

- **创建 issue**：`gh issue create --title "..." --body "..."`，多行正文用 heredoc。
- **查看 issue**：`gh issue view <number> --comments`，需要时配合 `jq` 过滤评论，并同时拉标签。
- **列出 issue**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，按需加 `--label`、`--state` 过滤。
- **评论**：`gh issue comment <number> --body "..."`
- **打/取标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭**：`gh issue close <number> --comment "..."`

仓库由 `git remote -v` 自动推断——在 clone 内运行 `gh` 时无需手动指定。

## 当某个 skill 说“发布到 issue tracker”

= 在 GitHub 上建一个 issue。

## 当某个 skill 说“拉取相关工单”

= 跑 `gh issue view <number> --comments`。
