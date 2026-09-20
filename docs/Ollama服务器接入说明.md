# 用SSH隧道连接服务器Ollama

当前接入方式：本机Demo发送消息 → 本机127.0.0.1:11435 → 用户维持的SSH隧道 → 服务器127.0.0.1:11434 → Ollama qwen2.5:14b。模板、Harness、求解器与参考核验仍在本机运行。

## 1. 保持隧道终端打开

在本地PowerShell运行下面的形式，替换账号和服务器地址；密码只在终端输入，不写入文件。SSH首次指纹需核对。

```powershell
ssh -N -L 127.0.0.1:11435:127.0.0.1:11434 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 用户名@服务器地址
```

认证成功后没有输出是正常现象。这个终端专门维持连接，不用在里面继续输入运行Demo的命令。端口绑定在本机回环地址，不把服务器模型接口开放到公网。无需更改服务器监听地址或防火墙，也不停止别人的模型服务。

## 2. 新开本地终端检查连接

在项目目录执行：

```powershell
.\.venv\Scripts\python.exe run_templates.py probe --backend ollama
```

该命令只读取版本、已安装模型与加载状态，不发推理请求、不下载模型。默认模型为qwen2.5:14b，默认地址http://127.0.0.1:11435；可以用 `--model`、`--ollama-url` 或 `DEMO_OLLAMA_URL` 环境变量指定。

## 3. 单题与整批运行

每次使用一个尚未存在的目录，不覆盖历史记录。

```powershell
.\.venv\Scripts\python.exe run_templates.py instantiate --directory outputs/ollama14b_mytest
.\.venv\Scripts\python.exe run_templates.py run --directory outputs/ollama14b_mytest --backend ollama --case printers --form call --retries 0
```

获得共享服务器使用许可后，可另建目录运行16视图和串联：

```powershell
.\.venv\Scripts\python.exe run_templates.py instantiate --directory outputs/ollama14b_full
.\.venv\Scripts\python.exe run_templates.py run --directory outputs/ollama14b_full --backend ollama --chain
```

程序串行请求，不并发占用资源。默认请求超时300秒，最多1400输出token；通过 `--model-timeout` 调整请求超时。HTTP故障或超时不会自动重试。超时表示客户端等待结束，不保证服务端任务立即取消，先检查状态再重试。退出码0只表示有界运行完成，不代表核验全部通过。

本轮不强制JSON模式或Schema约束，以免把模型变化与结构化输出机制变化混在一起。temperature设为0；不覆盖服务器num_ctx和keep_alive设置，不主动卸载模型。加载时上下文与实际调用配置未必相同，日志中的loaded_context_length仅表示探测时状态。

## 4. 代码改动

- demo/ollama_backend.py：对接原生 `/api/chat`，关闭流式，提取message.content作为模型原文，保留模型摘要、量化信息和时长。
- run_templates.py：新增probe命令、backend/model/URL/timeout选项；默认依然使用本地模型。
- task2/report.py：显示实际模型名称，不再对新结果写死0.5B。
- tests/test_ollama_backend.py：使用模拟HTTP响应测试协议、超时、错误与禁止自动下载；不调用共享服务器。

## 5. 比较时注意

服务器14B是GGUF Q4_K_M量化模型，旧0.5B使用Transformers本地权重。模型规模、量化、推理实现、硬件、上下文默认值和超时均可能不同，不能称作只改变模型规模的严格对照。对比报告必须说明模板是否一致、同一视图是否都运行、工具是否真实执行，以及耗时包含哪些环节。

本次只发送已有公开民用题和模板输入。合同、想定、隐藏参考、密码均不发给远程模型。原始结果保留在各自输出目录，不自动提交或推送GitHub。

接口参考：[Ollama官方API文档](https://github.com/ollama/ollama/blob/main/docs/api.md)。
