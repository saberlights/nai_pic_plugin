# 分诊标签（Triage Labels）

各 skill 内部用五个标准分诊角色名说事，这张表把它们映射到本仓库 issue tracker 里实际使用的标签字符串。

| skill 内部角色名     | 本仓库使用的标签   | 含义                           |
| -------------------- | ------------------ | ------------------------------ |
| `needs-triage`       | `needs-triage`     | 维护者需要先评估               |
| `needs-info`         | `needs-info`       | 等待报告人补信息               |
| `ready-for-agent`    | `ready-for-agent`  | 已完整规格化，AFK agent 可接手 |
| `ready-for-human`    | `ready-for-human`  | 需要人来实现                   |
| `wontfix`            | `wontfix`          | 不会处理                       |

skill 提到某个角色（例如“打上 AFK-ready 分诊标签”）时，使用本表右列对应的标签字符串。

如果后续启用了别的标签名（例如改用 `bug:triage`），改右列即可。
