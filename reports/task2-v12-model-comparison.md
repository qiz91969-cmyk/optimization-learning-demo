# v1.2固定输入模型对比

16个基础视图与6个边界视图的首轮请求逐项相同。反馈轨迹和串联中间结果可不同。均为开发材料，不是独立测试集。

| 分组 | 0.5B首轮/最终 | 14B首轮/最终 |
|---|---|---|
| 基础视图 | 7/16、7/16 | 14/16、14/16 |
| 边界视图 | 1/6、1/6 | 5/6、5/6 |

## 基础逐项

| 视图 | 0.5B最终 | 14B最终 | 14B尝试次数 |
|---|---|---|---|
| assignment:understanding | 未通过 | 通过 | 1 |
| assignment:method | 通过 | 通过 | 1 |
| assignment:call | 通过 | 通过 | 1 |
| assignment:result | 未通过 | 通过 | 1 |
| printers:understanding | 未通过 | 未通过 | 1 |
| printers:method | 通过 | 通过 | 1 |
| printers:call | 通过 | 通过 | 1 |
| printers:result | 未通过 | 通过 | 1 |
| bakery:understanding | 未通过 | 通过 | 1 |
| bakery:method | 通过 | 通过 | 1 |
| bakery:call | 未通过 | 通过 | 1 |
| bakery:result | 未通过 | 通过 | 1 |
| advertising:understanding | 未通过 | 未通过 | 1 |
| advertising:method | 通过 | 通过 | 1 |
| advertising:call | 未通过 | 通过 | 1 |
| advertising:result | 通过 | 通过 | 1 |

## 边界逐项

| 视图 | 0.5B最终 | 14B最终 | 14B尝试次数 |
|---|---|---|---|
| missing_matrix_understanding:understanding | 未通过 | 未通过 | 3 |
| missing_matrix_call:call | 未通过 | 通过 | 1 |
| extraction_omission:understanding | 未通过 | 通过 | 1 |
| multiple_legal_methods:method | 通过 | 通过 | 1 |
| inapplicable_candidate:method | 未通过 | 通过 | 1 |
| consistent_permutation:call | 未通过 | 通过 | 1 |

## 本次待修问题

14B打印机题将整数写成连续变量。广告题的数学对齐通过，但显式次数边界的ads单位被仅含dollars的参考约束单位集合拦截，属于检查过窄的待修问题；原始14/16保留，不追改成绩。
缺矩阵理解视图识别出了缺失项，却保留空矩阵；模板保持exact keys与省略缺字段的要求存在歧义，需要统一后另起版本复测。本次五个其他边界视图首轮通过，无真实反馈修复成功。

## 边界与证据

两组模型的硬件、量化与推理环境不同，不将耗时直接解释为模型速度差异。文字依据、来源语义仍待人工复核。

逐项检查、来源哈希与模型标识见task2-v12-model-comparison.json。完整轨迹保留在本机outputs，不把原始请求或服务器信息复制到公开摘要。
