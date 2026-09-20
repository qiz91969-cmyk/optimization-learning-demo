# 实测摘要

results-summary.json是已保存0.5B和14B运行的精选导出，含逐视图成绩、统计、来源哈希及比较条件。不包含完整请求或连接信息，不等于公开了全部可审计轨迹。

源文件位于outputs/task2_v11及outputs/ollama14b_comparison，被Git忽略。持有源文件时运行：

```powershell
.\.venv\Scripts\python.exe scripts/export_public_results.py
```

导出不调用模型、不改变成绩。四道题为开发案例，人工复核仍待完成，不作为总体正确率或正式训练集验收结论。
