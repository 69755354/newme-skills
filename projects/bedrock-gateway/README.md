# Bedrock multi-customer gateway · Bedrock 多客户服务网关

**English**　[Engineering handbook](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/) · [Interactive prototype](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/prototype/) · [Read on GitHub](docs/handbook.en.md) · [Propose a change](CONTRIBUTING.md#english)

**中文**　[工程手册](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/) · [交互原型](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/prototype/) · [GitHub 中文全文](docs/handbook.md) · [提交修改](CONTRIBUTING.md#中文)

Customers connect from their own production environments to an independent gateway run by the service provider. The gateway controls each customer's Dubai egress IPs, budgets and billing. Amazon Bedrock runs model inference.

客户从各自的生产环境接入由服务商运营的独立网关。网关控制每个客户的迪拜出口 IP、用量和账单，Amazon Bedrock 负责模型推理。

| What you need | English | 中文 |
| --- | --- | --- |
| Project scope and product workflow · 需求与产品 | [Requirements](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/#overview) · [Customer journey](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/#product) | [项目要求](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/#overview) · [客户流程](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/#product) |
| Architecture, network and access · 架构与权限 | [Request path](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/#architecture) · [Dubai egress](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/#network) · [IAM](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/#identity) | [调用链路](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/#architecture) · [固定出口](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/#network) · [客户身份](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/#identity) |
| Budgets and billing · 额度与分账 | [Budget controls](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/#quota) · [Reconciliation](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/#billing) | [额度控制](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/#quota) · [账单核对](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/#billing) |
| Operations and cutover · 运维与迁移 | [Runbook](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/#operations) · [Release criteria](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/#launch) | [故障处置](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/#operations) · [上线验收](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/#launch) |
| Pilot acceptance · 双客户验收 | [Two-customer pilot](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/#pilot) | [双客户试点](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/zh/#pilot) |
| GitHub and mobile · 仓库与手机 | [Read on GitHub](docs/handbook.en.md) · [Mobile prototype](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/en/mobile.html) | [GitHub 正文](docs/handbook.md) · [手机尺寸预览](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/mobile.html) |
| Download · 离线文件 | [PDF](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/downloads/Bedrock_Gateway_Design_EN.pdf) · [Word](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/downloads/Bedrock_Gateway_Design_EN.docx) | [PDF](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/downloads/Bedrock_Gateway_Design_CN.pdf) · [Word](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/downloads/Bedrock_Gateway_Design_CN.docx) |
| Verification · 验收记录 | [Verification record](VERIFICATION.en.md) | [验收记录](VERIFICATION.md) |

[Download both languages in one ZIP · 下载中英双语完整交付包](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/downloads/Bedrock_Gateway_Handoff.zip)

**Try the prototype.** In Overview, send a sample request twice with the same idempotency key. In Customers & limits, change a budget. In Billing, import the sample AWS Cost and Usage Report (CUR) and export one customer's CSV. The demo uses fictional data stored in your browser. The pilot covers actual AWS charges and Dubai egress.

**试用原型。** 在运营总览用同一幂等键提交两次请求，到客户与额度页调整预算，再在账单核对页导入示例 CUR 并导出单个客户的 CSV。原型使用保存在浏览器里的虚构数据，实际 AWS 费用与迪拜线路由部署团队在试点验收。
