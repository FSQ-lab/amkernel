# AMKernel

**让 Coding Agent 连续完成真实操作，而不是每一步都重新开始。**

AMKernel 帮助 Coding Agent 在一个任务中持续保留上下文和操作状态。你只需要说明想要的结果、不能做的事，
以及怎样才算完成；Agent 负责选择操作步骤、检查环境，并在结束前确认结果。

> **0.1.5 是技术预览版。** 核心目前只在项目的 GitHub 托管 Ubuntu/macOS 环境和 Python 3.11–3.13
> 上完成验证。手机及原生 macOS 自动化仍是实验能力，不代表已经完成所有真实设备和应用的兼容认证。

[最新版本](https://github.com/FSQ-lab/amkernel/releases/latest) · [PyPI](https://pypi.org/project/amkernel/) · [问题反馈](https://github.com/FSQ-lab/amkernel/issues/new/choose)

## 它能做什么？

AMKernel 适合需要 Agent 连续观察、处理和验证的任务，例如：

- 在多个页面之间收集信息，最后汇总成一份结果；
- 读取项目中的表格或文件，持续分析并生成报告；
- 在 Android 或 iPhone 应用中查找信息、填写内容或完成多步骤操作；
- 操作原生 macOS 应用并确认最终界面状态；
- 在任务中保留已经打开的应用、已经读取的数据和中间结果，减少重复工作。

你不需要写自动化脚本，也不需要告诉 Agent 每一步点哪里。通常只需要说清楚：

1. **目标**：最终希望得到什么；
2. **范围**：在哪个设备、应用、文件或项目中操作；
3. **限制**：哪些内容不能修改、发送或删除；
4. **完成标准**：你希望 Agent 最后确认什么。

## 安装

### 第一步：准备环境

你需要：

- macOS 或 Ubuntu；
- [uv](https://docs.astral.sh/uv/getting-started/installation/)；
- OMP、Pi、Codex 或 GitHub Copilot 中的一个 Coding Agent 客户端；
- 一个准备启用 AMKernel 的项目目录。

Windows 当前不受支持。第一次安装 AMKernel 不需要连接手机；只有使用手机场景时，才需要准备对应设备和工具。

### 第二步：运行安装命令

在 Coding Agent 正在使用的项目目录中打开终端，复制并运行：

```bash
uvx --from amkernel amkernel install
```

安装器会：

1. 检测当前可用的 Coding Agent；
2. 如果检测到多个客户端，请你选择一个；
3. 展示即将进行的更改并请求确认；
4. 只为当前项目启用 AMKernel；
5. 告诉你是否需要重新加载 Coding Agent。

如果安装器提示重新加载，请先完成重新加载，再开始使用。

### 第三步：直接告诉 Agent 你的目标

无需学习命令或接口。可以使用下面的模板：

> 请在【设备、应用或项目】中完成【目标】。
>
> 不要【禁止的操作】。
>
> 完成后请确认【可以观察到的最终结果】。
>
> 如果需要安装工具、修改系统配置或处理敏感数据，请先说明影响并征得我的确认。

## 可以直接尝试的场景

### 场景一：分析项目中的数据

> 请读取当前项目中的 `sales.csv`，找出销售额最高的三个产品，并总结最近一个月的变化趋势。
> 不要修改原文件。把结果写成一份新的 Markdown 报告，并在完成后告诉我报告路径和关键结论。

这个场景不需要手机，适合安装后第一次体验。

### 场景二：查看 Android 手机信息

> 请在我已连接的 Android 手机上打开“设置”，找到“电池”页面，并告诉我当前电量和可见的电池状态。
> 不要修改任何设置。完成后请确认手机仍停留在电池页面。

### 场景三：总结测试邮箱中的非敏感会话

> 请在用于测试的 Gmail 账号中，搜索主题包含【测试关键词】的非敏感会话，打开正确的会话，
> 阅读其中的测试邮件并总结主要结论。不要发送、删除、归档或标记任何邮件。
> 完成后告诉我你阅读了哪一个会话以及总结依据。

邮件正文会提供给你当前配置的 Coding Agent 进行总结。不要对个人邮箱、工作邮箱或包含私人信息的会话使用这个场景。

### 场景四：比较股票信息

> 请在 iPhone 的股票应用中查看【股票 A】和【股票 B】，收集当前价格、当日涨跌和页面上可见的关键信息，
> 最后用表格比较。不要修改自选列表。

### 场景五：查看 Mac 存储空间

> 请打开 Mac 的系统设置，找到存储空间页面，告诉我当前可用空间和占用最多的类别。
> 不要删除文件或修改任何设置。完成后请确认仍停留在存储空间页面。

手机和原生 macOS 场景是实验能力。Agent 可能需要先检查设备、权限和相关工具；如果需要安装软件或修改系统，
应先解释影响并请求你的确认。

## 演示

### Android：总结测试账号中的合成 Gmail 会话

Agent 在测试账号中搜索、找到包含合成内容的正确会话、阅读多封测试邮件，并在一个连续任务中给出总结。

https://github.com/user-attachments/assets/ddd80181-c7c1-4474-8943-89693c5358b7

### iPhone：收集并分析股票信息

Agent 在多个页面之间收集市场信息，并在最后给出一份统一分析。

https://github.com/user-attachments/assets/43b9ca46-b83a-40ab-a5a0-541443c2cb00

## 使用时会发生什么？

收到任务后，Agent 应当：

1. 确认目标、设备或应用是否明确；
2. 检查当前环境是否已经具备所需条件；
3. 在安装工具、修改系统或执行敏感操作前说明影响并请求确认；
4. 连续执行任务，并在页面变化或操作失败后重新观察，而不是盲目重复；
5. 检查最终结果是否真的满足你的完成标准；
6. 分别说明任务结果、仍在运行的连接以及清理情况。

如果环境不支持、权限不足或结果无法确认，Agent 应明确说明实际停在哪里，而不是声称已经完成。

## 当前支持范围

| 项目 | 0.1.5 状态 |
| --- | --- |
| 已验证环境 | GitHub 托管的 Ubuntu 和 macOS，Python 3.11–3.13 |
| Coding Agent | OMP、Pi、Codex、GitHub Copilot |
| 普通项目与数据任务 | 技术预览 |
| Android、iPhone 自动化 | 实验能力，需要兼容的设备和环境 |
| 原生 macOS 自动化 | 实验能力 |
| Windows | 不支持 |
| 安全边界 | 在你的本机账户权限下运行，不是安全沙箱 |

AMKernel 能执行与当前本机用户相同权限范围内的操作。不要把密码、密钥、私人应用内容、个人设备标识或未经筛选的
完整日志发送给 Agent。对删除、发送、购买、发布、修改系统等高影响操作，应给出明确限制并要求执行前确认。

## 检查、更新或卸载

在项目目录中运行：

```bash
amkernel status      # 查看当前项目是否已启用
amkernel doctor      # 检查安装和项目配置
amkernel update      # 更新 AMKernel
amkernel uninstall   # 从当前项目移除 AMKernel
```

如果命令失败，可以把终端中的错误信息交给 Coding Agent，并告诉它：

> 请帮我检查当前项目的 AMKernel 安装问题。先运行诊断并解释原因；需要修改配置或重新安装前先征得我的确认。

全局卸载会影响所有已经启用 AMKernel 的项目，因此必须显式执行：

```bash
amkernel uninstall --global
```

AMKernel 不会默认关闭或删除原本已经存在的手机、模拟器、自动化服务或开发工具。

## 反馈问题

如果体验成功或失败，都可以通过 [GitHub Issue](https://github.com/FSQ-lab/amkernel/issues/new/choose) 告诉我们。建议包括：

- 使用的 Coding Agent 和操作系统；
- 操作的应用、设备或文件；
- 你给出的完整目标和限制；
- 最后一个确认成功的步骤；
- 实际错误或不符合预期的结果；
- 任务结束后应用、设备和连接是否仍可使用。

提交前请删除密码、密钥、私人内容、个人设备标识和其他敏感信息。

## 更多信息

- [架构与安全模型](https://github.com/FSQ-lab/amkernel/blob/main/docs/architecture.md)
- [开发与发布流程](https://github.com/FSQ-lab/amkernel/blob/main/docs/development.md)
- [手机自动化实验说明](https://github.com/FSQ-lab/amkernel/blob/main/docs/experiments/mobile-appium.md)
- [当前项目计划](https://github.com/orgs/FSQ-lab/projects/2)
