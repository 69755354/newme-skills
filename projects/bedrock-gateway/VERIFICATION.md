# 公开版本验收记录

## v1.1 工程手册及下载验收

2026-11-25，迪拜，[工程版本 77ff89f](https://github.com/69755354/newme-skills/commit/77ff89f9e36c173e6d53c77bf4ed0dc1c57a4f5e)。

- 未登录浏览器从公开 GitHub 项目 README 点击“双客户试点验收”，到达[手册对应章节](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/#pilot)。网页显示 v1.1，列明网关和 Bedrock 各自承担的工作、两种接口的分账方法及四个岗位的试验。
- 通过公开网页下载 PDF 和 ZIP，并与 GitHub 发布版本对应文件比对。PDF 共 12 页，第 10 页为双客户试点验收。ZIP 完整性校验通过，其内 Word 有相同章节，内含 PDF 与单独下载的一致。
- PDF 的 SHA-256 为 `9be988cd7bd09c17009be37c6d6cdd35a450d716fc56266d9bbd75c930e41086`。ZIP 的 SHA-256 为 `5d2dc17d0e05d210a86ba994db0a23536eeef0558599624de34c9da4324dc4b6`。
- 这次核验覆盖公开交付材料。真实迪拜线路、两客户云账单、并发及隔离须由部署团队按第 10 页留证签收。

## v1.0 原型与交互验收

2026-11-25，迪拜。受测版本为 `4878baef03d87a3e31f6461b59a48350074f927c` 上的 15 个交付文件。[公开手册](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/) · [交互原型](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/prototype/) · [手机尺寸预览](https://bedrock-gateway-handbook.bright-bass-8857.chatgpt.site/mobile.html)

## 访问与下载

- GitHub 访客页显示 Sign in，工程目录及 README 可读。从 README 的“直接操作原型”和手册首页的“打开交互原型”，都进入了能操作的运营总览。
- 网站的已发布访问模式为 public。独立外部抓取端在没有工程账户凭证的情况下取回了手册正文。
- 从公开首页取得 PDF、Word 和 ZIP。下载内容与发布文件的 SHA-256 一致。PDF 可解析为 11 页，ZIP 完整性校验通过，内含 PDF、Word 和单文件原型。

## 浏览器操作结果

| 场景 | 做了什么 | 读回结果 |
| --- | --- | --- |
| 计费与重复提交 | 企业 A 提交预占上界 $2.50 的请求，再次提交同一幂等键 | 首次显示已计 $2.00，第二次显示幂等回放。总用量费保持 $94.80。 |
| 超额拦截 | 用新键提交 $999.00 的预占 | 页面显示 429、剩余 $19.80、本笔未发送。 |
| 客户改额 | 日预算由 $100.00 调为 $120.00，确认保存 | 变更后该客户可预占 $37.80，页面显示保存成功。 |
| 客户分账 | 导入演示 CUR，核对企业 A 并下载该行的 CSV | 浏览器实际下载的 CSV 有一行表头和一行客户记录。TEN-017 的用量费 $62.40、固定业务服务费 $20.00、应付 $82.40，状态为已核对。 |
| 手机布局与隔离 | 在浏览器实际测量为 390 CSS 像素宽的视口中切到“客户与额度”并进入客户视图 | 看见企业 A 的余额、账单与服务，页面未显示企业 B。 |
| 固定出口与主备切换 | 在手机视图模拟 DXB-01 断线并确认 | 固定单出口的企业 A 显示停发，已批准备用出口的企业 B 显示 DXB-02。 |
| 演示复位 | 点击“重置演示”并确认，重新从 GitHub 进入 | 恢复三个示例客户及默认 $92.80 总用量费。 |

检查覆盖公开网页、示例数据和浏览器导出。手机宽度检查在桌面浏览器中完成。iPhone 实机、真实 AWS 账单和迪拜线路仍属于生产环境验收范围。

## 下载文件校验

| 文件 | SHA-256 |
| --- | --- |
| Bedrock_Gateway_Design_CN.pdf | `98727abb8be172c36ba0fe677fcee1ba75f8458ab88bf190058923de14a4a69a` |
| Bedrock_Gateway_Design_CN.docx | `7ba55fa626366c96b364fbd7e03b3363dff463aa2c448c63b980e42c7cff91e4` |
| Bedrock_Gateway_Handoff.zip | `81baa44864b2825b914c2a8e5b6b6166ce32e668887275c6d907bae108b161e3` |