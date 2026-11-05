# AMKernel

**AMKernel — Automation MCP Kernel**

> Persistent Python execution for agentic automation.
>
> 面向 Agent 自动化的持久 Python Execution MCP。

AMKernel is a persistent Python execution MCP for agentic automation. Mobile automation through Appium is its first experimental vertical.

AMKernel 是一个面向 Agent 自动化的持久 Python Execution MCP。基于 Appium 的移动自动化是它的第一个实验方向。

**AMKernel 0.1.2 is a technical preview.** It tests whether Coding Agents can use one persistent local Python Runtime and existing automation libraries to complete continuous, multi-step work in real applications and devices.

**AMKernel 0.1.2 是技术预览版。** 它正在验证 Coding Agent 能否通过一个持久的本地 Python Runtime，直接使用现有自动化库，在真实应用和设备中完成连续、多步骤任务。

This is not yet a finished Mobile Use or Computer Use product. We invite developers and early users to try it, tell us what works and what fails, and help identify the scenarios that should be evaluated next. Those experiments and evaluations will inform future Mobile Use and Computer Use tools.

它目前还不是一个已经完成的 Mobile Use 或 Computer Use 产品。我们希望开发者和早期用户实际试用，反馈哪些场景有效、哪些场景失败，以及下一步应该测评什么。后续的实验和系统化测评将为真正的 Mobile Use 与 Computer Use 工具提供依据。

Latest release: [`0.1.2`](https://github.com/FSQ-lab/amkernel/releases/tag/v0.1.2) · [PyPI](https://pypi.org/project/amkernel/0.1.2/) · [Changelog](https://github.com/FSQ-lab/amkernel/blob/main/CHANGELOG.md)

## Technical preview demos / 技术预览演示

These demos show experimental capabilities, not finished product or platform-support claims.

这些视频用于展示技术实验，不代表已经完成的产品或正式的平台支持承诺。

### Android: summarize a Gmail conversation / Android：在 Gmail 中查找并总结邮件

A Coding Agent uses AMKernel, Python, and Appium to search Gmail, open the correct conversation, read multiple messages, and summarize the thread as one continuous task.

Coding Agent 通过 AMKernel、Python 和 Appium 操作真实 Android Gmail，完成搜索、定位会话、读取多封邮件和总结内容的连续任务。

https://github.com/user-attachments/assets/ddd80181-c7c1-4474-8943-89693c5358b7

### iPhone: analyze stock information / iPhone：读取股票信息并进行技术分析

A Coding Agent uses the same AMKernel Runtime to operate a connected iPhone, collect market data and technical indicators for MSFT, GOOG, and AMZN across multiple pages, and produce one analysis from persistent Python state.

Coding Agent 使用同一个 AMKernel Runtime 操作已连接的 iPhone，跨多个页面采集 MSFT、GOOG 和 AMZN 的行情与技术指标，并通过持久 Python 状态生成统一分析。

https://github.com/user-attachments/assets/43b9ca46-b83a-40ab-a5a0-541443c2cb00

## What we are testing / 我们正在验证什么

- **Persistent state** — imports, variables, functions, and live automation objects remain available across tool calls.
- **Direct library use** — the Agent uses official Python libraries instead of a growing catalog of AMKernel-specific action tools.
- **Multi-step work** — the Agent can observe a result, keep useful state, and decide the next operation.
- **Local computation** — Python can filter, transform, compare, and summarize large external state before returning bounded output.
- **Agent-quality output** — structured values, images, progress, stdout/stderr, and large artifacts are first-class results.
- **Truthful recovery** — timeouts, ordinary errors, kernel death, reset, and managed cleanup remain distinguishable.

The first completed experiment uses Appium with Android and iOS. Future experiments may explore Playwright, Selenium, pywinauto, PyAutoGUI, macOS Accessibility, and other automation ecosystems. These experiments validate the underlying technique; they do not make those platforms part of the AMKernel core.

首个已完成实验使用 Appium 操作 Android 和 iOS。未来可能继续测试浏览器、Windows 和 macOS 自动化生态。实验的目标是验证底层技术，而不是把所有平台操作封装进 AMKernel 核心。

## Try AMKernel 0.1.2 / 开始试用

AMKernel uses one user-level `uv`-managed Runtime and project-scoped Coding Agent activation. From the project directory, run:

```bash
uvx --from amkernel amkernel install
```

The interactive installer detects OMP, Pi, Codex, and GitHub Copilot project clients. One detected client is selected automatically; multiple or missing candidates open a single-choice prompt.

For non-interactive installation, specify the complete contract:

```bash
uvx --from amkernel amkernel install --client codex --scope project --yes --json
```

The installer manages one shared user Runtime plus the selected project's AMKernel Skill, pinned official Appium Skills source, and native MCP configuration. Each activated project still starts an independent Server, Runner, Python namespace, and artifact lifecycle.

Useful lifecycle commands:

```bash
amkernel status
amkernel doctor
amkernel update
amkernel uninstall
```

`amkernel uninstall --global` is explicit because it affects every activated project. AMKernel does not itself install or supervise Appium Server, platform drivers, SDKs, devices, simulators, or WebDriverAgent; the installed Skill guides the Agent through the relevant prerequisites when a mobile experiment needs them.

For Android, the [packaged setup procedure](src/amkernel/skill/references/android-setup.md) first reuses verified JDK/SDK installations, then selects only target-relevant components. The Agent discloses installation methods, versions, locations and impact, executes approved changes through host tools, and verifies them. Physical-device readiness does not require emulator/AVD inventory; configured AVDs and successful doctor/status checks do not prove a live session. Setup does not expand AMKernel's platform support.

Agent setup and MCP repair may use shell, PowerShell, native host tools, or focused diagnostic
probes; they do not require an already-working `python_exec` connection. Appium session and
device/application interaction code runs through the official Python Client in `python_exec`.
For a missing or incorrect project MCP entry, diagnose the launcher and active configuration,
apply the authorized correction through the same installer with the complete non-interactive
flags, then reload the Coding Agent if required. A successful CLI or SDK probe proves only its
own check; verify the actual Agent connection after reload before calling it ready for execution.

## Share feedback / 提交反馈

AMKernel needs real usage evidence, including unsuccessful experiments. Open a [GitHub Issue](https://github.com/FSQ-lab/amkernel/issues/new/choose) and describe:

- the Coding Agent and version;
- the host operating system and Python version;
- the automation library, application, and target device or environment;
- the task you asked the Agent to complete;
- what completed successfully;
- the exact step where the experiment stopped or behaved unexpectedly;
- whether the Python kernel and external automation session remained usable;
- which scenario you want the project to evaluate next.

Please do not attach credentials, private application content, personal device identifiers, or unrestricted raw logs.

我们同样需要失败场景。请告诉我们你原本希望完成什么、实际完成到哪一步、在哪一步停止，以及你希望后续测评哪些真实任务。

## From technical preview to future tools / 从技术预览到未来工具

1. **Now — technical preview:** publish a reliable persistent Python execution kernel and exercise it in real automation tasks.
2. **Next — systematic evaluation:** compare different Coding Agents, devices, operating systems, applications, task types, failure modes, and recovery behavior.
3. **Future — product integration:** use the measured results to design and integrate dedicated Mobile Use and Computer Use tools.

This is a direction, not a claim that the current package already provides those finished products. Live priority, blockers, and evaluation status remain in [GitHub Project #2](https://github.com/orgs/FSQ-lab/projects/2).

## How it works / 工作方式

```text
Coding Agent
  → MCP
  → persistent local Python kernel
  → official automation library
  → external system
```

For the first mobile experiment:

```text
Coding Agent
  → AMKernel
  → Appium Python Client
  → Appium Server
  → XCUITest / UiAutomator2
  → mobile device
```

The primary model-facing interface is Python execution, not predefined mobile, browser, or desktop actions. This lets the Agent retain live objects, write loops and explicit waits, transform data locally, call project helpers, and reuse the official automation ecosystem directly.

## Current scope and support / 当前范围与支持

- The packaged core supports CPython 3.11, 3.12, and 3.13.
- The qualified operating-system claim is limited to current GitHub-hosted Ubuntu and macOS environments exercised by the native lifecycle and installed-wheel official-client matrices.
- CPython 3.14, Windows, and other operating systems remain unsupported.
- The Android/iOS Appium reference experiment and failure matrix are complete, but Mobile/Appium remains experimental and unsupported as a product platform.
- AMKernel is unrestricted local same-user Python execution, not a sandbox.
- Artifact resource URIs are ephemeral. Read and verify every manifest part before another large-output call or server shutdown.

## Why the name

- **Automation** — Appium, Playwright, Windows, macOS, and other automation environments. / Appium、Playwright、Windows、macOS 等自动化场景。
- **MCP** — the standard interface that attaches AMKernel to different Coding Agents. / 挂载到不同 Coding Agent 的标准接口。
- **Kernel** — a persistent Python namespace with object reuse, incremental execution, and interrupt recovery. / 持久 Python namespace、对象复用、增量执行和中断恢复。

## Project documents

- [`docs/architecture.md`](https://github.com/FSQ-lab/amkernel/blob/main/docs/architecture.md) — generic AMKernel core architecture.
- [`docs/development.md`](https://github.com/FSQ-lab/amkernel/blob/main/docs/development.md) — development workflow, quality gates, and release procedure.
- [`docs/experiments/mobile-appium.md`](https://github.com/FSQ-lab/amkernel/blob/main/docs/experiments/mobile-appium.md) — completed Mobile/Appium experiment and retained support boundary.
- [`docs/stage-1-implementation-plan.md`](https://github.com/FSQ-lab/amkernel/blob/main/docs/stage-1-implementation-plan.md) — persistent execution and lifecycle contracts.
- [`docs/stage-2-implementation-plan.md`](https://github.com/FSQ-lab/amkernel/blob/main/docs/stage-2-implementation-plan.md) — output, artifact, recovery, and support contracts.
- [`docs/stage-3-implementation-plan.md`](https://github.com/FSQ-lab/amkernel/blob/main/docs/stage-3-implementation-plan.md) — Mobile/Appium experiment contract and graduation criteria.
- [`docs/stage-4-implementation-plan.md`](https://github.com/FSQ-lab/amkernel/blob/main/docs/stage-4-implementation-plan.md) — active cross-client evidence contract.
- [`docs/decisions/`](https://github.com/FSQ-lab/amkernel/tree/main/docs/decisions) — accepted architecture and implementation decisions.
- [GitHub Project](https://github.com/orgs/FSQ-lab/projects/2) and [GitHub Issues](https://github.com/FSQ-lab/amkernel/issues) — live priorities, work items, blockers, and evidence.
