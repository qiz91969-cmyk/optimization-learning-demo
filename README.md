# optimization-learning-demo

公开民用优化教学Demo：从英文描述或结构化JSON开始，经过校验、固定工具求解、有限反馈修正和独立核验，留下可检查的运行记录。

**这不是正式项目的全部实现，也不验证军事用途。** 只使用5道公开生产、广告、工人分配和配送练习。不导入合同或想定，不微调，不调用付费API，不执行模型生成的Python。

## 先看什么

1. [本次实测结果](docs/本次实测结果.md)：实际跑通什么、失败在哪里、证据位置。
2. [从一道题读懂代码](docs/从一道题读懂代码.md)：字段、输入输出、函数和真实案例。
3. [数据来源与五道题](docs/数据来源与五道题.md)：原始编号、数学模型、整数约定和参考结果。
4. [过程记录与待确认](docs/过程记录与待确认.md)：困难、处理办法和后续讨论事项。

## 本机直接运行

在VS Code打开本仓库，在PowerShell终端运行。已建立新环境，不需要先激活，也不需要重复安装PyTorch。

```powershell
Set-Location 'G:\研究生内容\研0\OR\optimization-learning-demo'
.\.venv\Scripts\python.exe check_environment.py
.\.venv\Scripts\python.exe run_demo.py --entry json --case printers --require-success
.\.venv\Scripts\python.exe run_demo.py --entry nl --case assignment
.\.venv\Scripts\python.exe run_demo.py --entry both --case all
```

每次新建 `outputs/时间戳/`，终端最后打印 `SUMMARY.md` 路径。先读摘要，再看 `assignment_nl.json` 等完整轨迹。默认退出码0只表示已生成报告，不表示题目全部答对；`--require-success` 会把任一核验失败变为非零退出码。

`json` 不调用模型；`nl` 调用本地Qwen；`both` 分别运行、分别统计。`--retries 0` 禁用反馈；默认最多2次修正，即最多3次模型回答。输出目录不覆盖先前运行。

## 换一台电脑

求解与测试使用Python 3.12。在仓库建立独立环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_demo.py --entry json --case all --require-success
```

自然语言入口另需已安装PyTorch和Transformers的环境，以及完整本地Qwen2.5-0.5B-Instruct权重。本机复用了已有环境，没有修改旧环境；其他电脑可显式配置：

```powershell
$env:DEMO_MODEL_PYTHON = 'D:\your-model-env\Scripts\python.exe'
$env:DEMO_MODEL_PATH = 'D:\your-local-Qwen2.5-0.5B-Instruct'
.\.venv\Scripts\python.exe check_environment.py
.\.venv\Scripts\python.exe run_demo.py --entry nl --case assignment
```

也可用 `--model-python`、`--model-path`。脚本不自动下载权重。本机已验证的模型环境是PyTorch 2.5.1+cu121、Transformers 4.57.6，模型版本与显存等见轨迹的 `model_metadata`。当前模型worker要求CUDA，没有实现CPU推理回退；无CUDA会明确报错。环境检查需要模型和求解两端均可用才返回0；仅模型缺失不妨碍运行JSON入口。

## 流程与边界

```text
公开英文题干 -> 公开关键词选模板、给定实体ID -> Qwen提取problem
                                                        |
已整理的JSON问题 ----------------------------------------+
                                                        v
Schema/维度/范围/引用检查 -> 固定工具调用 -> SciPy求解 -> 保存实际结果
           |
      接口错误反馈，最多2次修正

在线环路结束 -> 独立参考评估 -> 中文摘要与完整轨迹
```

自然语言入口使用受限辅助：题干出现worker/warehouse时选分配/配送模板，其余限定在线性资源练习范围内；实体次序预先给定。提示提供另一道虚构教学例题演示格式。**验证的是给定模板后的读题填参，不是自由算法选择或通用类别识别。** 5题均用于开发调试，不是未见测试集。

工具只有 `solve_linear`、`solve_assignment`、`solve_transportation`。SciPy/HiGHS的LP或MILP处理实际求解。分配接口固定每人至多一项、每项恰好一人；配送固定供应上限、需求下限，不含车辆路线。

Schema通过不等于题意正确。离线评估另检查参考模型对齐、原题约束、整数性、目标重算和参考最优值；多个最优解不要求逐项相同。单位只检查标签，数学等价识别也只支持有限形式，均不能替代人工核对。

接口错误可以反馈，隐藏参考解和最优值不能反馈。无解时不删条件；超时和重试耗尽均保留失败状态。报错反馈不保证提高正确率。

## 五道题

|编号|内容|已整理JSON的参考核验结果|
|---|---|---|
|printers|NL4Opt打印机生产|20台彩色、15台黑白，利润5050|
|bakery|NL4Opt面包房生产|0个面包、3000批饼干，利润9000|
|advertising|NL4Opt广告预算|无解：最低费用395250超过250000|
|assignment|OR-Tools五工人四工作|最小成本265|
|transportation|PuLP两仓五销售点|最小运输成本8600，允许剩余供应|

这不是模型成绩。改写、整数解释和来源见数据说明；再分发事项见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。所有样本人工复核状态仍为 `pending`。

## 测试与人工故障演示

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe run_fault_checks.py
```

测试包括真实求解、独立算术/枚举核验、格式错误、非法工具、参数维度、非法数值、重试上限、无解、无界、模拟超时及答案隔离。人工故障轨迹位于 `outputs/faults_时间/`，标为synthetic；证明的是程序分支可用，不是Qwen真实纠错成功。超时测试采用注入，不能说真实运行曾全部遇到。

## 文件分工

|位置|内容|
|---|---|
|data/inputs/|公开题干、约定、来源；中文解释不给模型|
|data/problems/|已整理的问题，用于JSON入口及事后参考评估|
|data/references/answers.json|参考状态、目标、可行见证与核验依据|
|demo/prompts.py|公开模板选择、字段规则、独立教学示例|
|demo/backend.py、model_worker.py|跨环境本地Qwen调用、限时、元数据|
|demo/validation.py|JSON Schema、数值/维度检查、固定工具白名单|
|demo/harness.py|在线有界反馈，不读取参考答案|
|demo/solver.py|模型构造、LP/MILP执行与返回|
|demo/evaluation.py|独立事后核验，不参与模型反馈|
|run_demo.py|运行入口、保存过程、生成摘要|
|tests/|自动化测试，替身与真实模型隔离|
|outputs/|本机运行记录，默认不提交Git|

日志只是候选材料。需人工核对原题、建模、参数和执行证据，再按训练任务分离输入与目标；失败回答不直接成为标准答案。

## GitHub Desktop

本目录已是克隆的仓库。在Desktop中选择它即可；列表中没有时用 **File > Add local repository** 选择本目录，不要克隆到自身里面。在VS Code编辑后，Changes会自动显示变化，不用每次网页上传。

确认修改后自行Commit，再Push origin才上传。本次没有自动提交或推送。首次提交检查Changes，排除密钥、合同、想定、权重、虚拟环境。`.gitignore` 排除了常见本机产物，但不是敏感信息检测器。分享日志时另选公开示例的脱敏记录，不要强制上传整个outputs目录。
