# 实测摘要

当前v1.3结果见task2-v13-results.json：12道新增候选、4道程序核验、15个适用视图；0.5B首轮5/15、最终6/15，14B首轮与最终14/15。完整记录在本地outputs/task2_v13_comparison。摘要只导出白名单字段，不含服务器地址、原始请求或私有材料。测试证据为outputs/task2_v13_engineering/tests.xml。重新导出不会调用模型或追改评分：

```powershell
.\.venv\Scripts\python.exe scripts/export_v13_results.py
```

脚本核对实例与实际首轮请求哈希，并附原始结果、数据与测试文件哈希。新版本模板与题目变化，不能拿历史成绩当作严格版本提升实验。下列为历史阶段说明。

最新同输入14B对照见task2-v12-model-comparison.md/json：22个独立视图首轮请求完全一致，原始规则得分保留；广告单位检查的过窄判定及缺字段表达歧义已在项目README单独说明。scripts/export_v12_comparison.py可从四份本机原始记录再生成摘要。

v1.2本地阶段见task2-v12-summary.json：包括原0.5B与新版基础视图的开发比较、六个边界实测、当时工程测试统计及来源哈希。该历史摘要不包含后续14B结果。持有完整本机记录时可运行scripts/export_v12_results.py重新生成；模板与输入不同，不是严格同输入实验。

results-summary.json是已保存0.5B和14B运行的精选导出，含逐视图成绩、统计、来源哈希及比较条件。不包含完整请求或连接信息，不等于公开了全部可审计轨迹。

源文件位于outputs/task2_v11及outputs/ollama14b_comparison，被Git忽略。持有源文件时运行：

```powershell
.\.venv\Scripts\python.exe scripts/export_public_results.py
```

导出不调用模型、不改变成绩。四道题为开发案例，人工复核仍待完成，不作为总体正确率或正式训练集验收结论。
