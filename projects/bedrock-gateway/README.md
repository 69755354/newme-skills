# Bedrock 多客户服务网关

面向产品、开发、网络、财务及值班人员的中文工程交接。所有演示客户、地址、金额均为虚构数据。

**[打开公开手册](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/)　·　[直接操作原型](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/prototype/)　·　[手机尺寸预览](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/mobile.html)**

| 需要查看 | 入口 |
| --- | --- |
| 业务背景、范围和交付要求 | [背景与范围](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/#overview) |
| 产品页面与客户旅程 | [产品设计](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/#product) |
| 技术架构、网络与客户身份 | [技术架构](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/#architecture) · [迪拜出口](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/#network) · [IAM 与企业档案](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/#identity) |
| 用量控制与账单 | [额度计算](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/#quota) · [成本核对](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/#billing) |
| 运维、旧 IAM 迁移与验收 | [故障处置](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/#operations) · [上线验收](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/#launch) |
| 在 GitHub 阅读完整正文 | [完整手册](docs/handbook.md) |
| 下载交付材料 | [PDF](downloads/Bedrock_Gateway_Design_CN.pdf) · [可编辑 Word](downloads/Bedrock_Gateway_Design_CN.docx) · [ZIP](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/downloads/Bedrock_Gateway_Handoff.zip) |

## 原型如何试用

打开在线原型，在“运营总览”发送一笔示例请求，再次提交相同幂等键可回放结果。进入“客户与额度”修改企业或服务的日预算。进入“账单核对”，导入示例 CUR 后可按客户导出 CSV。所有变更保存在当前浏览器，可随时重置演示。

## 目录

- `index.html` 是手册入口。`docs/handbook.md` 为 GitHub 可直接阅读的正文。
- `prototype/` 是纯静态浏览器应用，包含页面、脚本和样式。
- `assets/` 存放架构图、界面示意和手册样式。`downloads/` 存放可转交的文件。
- 在当前目录使用静态 HTTP 服务即可预览。公开网站使用同一份页面资源。

发布范围为产品与工程设计和模拟数据。真实线路、AWS 账单与生产并发以手册的上线证据为准。
