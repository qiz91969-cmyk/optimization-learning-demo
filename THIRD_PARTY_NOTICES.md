# 第三方来源与使用说明

本仓库是独立公开民用教学演示，不包含合同、想定或原项目私有数据。自编代码不代表上游官方实现。仓库已公开，但尚未替项目决定整体开源许可证；公开可见不等于所有内容均可直接打包商业交付。

## NL4Opt

来源：https://github.com/nl4opt/nl4opt-competition

原有3条题目加v1.3新增4条题干，共7条，均来自generation_data/test.jsonl。新增编号为1751406188（玻璃）、741805703（灯具）、703345038（配料）、-1394927728（会计人员）；其中仅玻璃题进入本轮模型实测，其余是待核验候选。上游版本固定为49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea。英文题干原样保留，中文译解、字段组织、整数解释为本演示新增，不改变或冒充原始LP标注。2026-09-21重新核对上游仓库LICENSE为MIT，原文如下。

MIT License

Copyright (c) 2022 Huawei Technologies

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Google OR-Tools

题目事实和5×4成本矩阵来自Google Developers的Solving an Assignment Problem：
https://developers.google.com/optimization/assignment/assignment_example

查阅日期2026-09-19。英文和中文描述重新整理，没有复制求解实现。按页面声明，说明内容为CC BY 4.0，示例代码为Apache 2.0（页面另有声明时从其声明）。本项目不用OR-Tools依赖，用SciPy独立实现相同教材问题，不能称为官方OR-Tools复现结果。

## COIN-OR PuLP

配送题的数字和基础模型来自A Transportation Problem：
https://coin-or.github.io/pulp/CaseStudies/a_transportation_problem.html

查阅日期2026-09-19。原案例为啤酒仓库向销售点配送，本项目保留这一民用用途。英文/中文描述重新整理，未复制PuLP求解代码，也不包含教程后续虚拟节点扩展。公开再分发前仍需核对上游文档具体条款；当前标记下游再分发复核待完成，不擅自把整套数据宣布为MIT。

## 模型和依赖

v1.3新增12道候选中，4道为上述公开题干，8道为新编民用教学题，不属于NL4Opt原始记录。仅使用一般资源/任务分配概念，不含私有原文、实际对象、参数、地点或行动要求。四份材料的访问状态与采用位置记录在data/task2_v13/catalog.json；想定原文件和抽取内容不纳入仓库。

OptiMUS仓库及2023年论文仅作为流程参考。其关联NLP4LP数据注明CC BY-NC 4.0与研究用途限制，本轮未下载、复制或用于模型测试。NL4Opt 2024官网所指向的nl4opt-competition-v2仓库在2026-09-21仍返回404，因此仅参考LP/MIP区分与评价思路，不宣称已采用其数据。

Qwen2.5-0.5B-Instruct仅从本机缓存加载，权重不纳入仓库，模型信息见https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct 。

SciPy/NumPy/jsonschema/pytest等依赖保留各自许可证；本项目不把它们的包文件纳入Git。OptiMUS只作为反馈机制参考，没有复制其代码，也没有下载受限的NLP4LP数据。
