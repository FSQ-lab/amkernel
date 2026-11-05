# iPhone 环境设置 Skill 技术方案

- 状态：Owner 已接受并授权实施；设计决策记录，实现由 [#131](https://github.com/FSQ-lab/amkernel/issues/131) 拥有。验证证据见 [iPhone 设置实验](appium-agent-behavior.md#18-iphone-setup-skill-131)，不扩展 Kernel API 或正式平台资格。
- 日期：2026-11-05。
- Review owner：项目 owner。
- 范围：macOS 上的 iPhone 真机环境准备、依赖复用、签名引导及明确授权的连接验证。
- 项目边界：已检查 GitHub Project #2、[#98](https://github.com/FSQ-lab/amkernel/issues/98) 和实施工作项 [#131](https://github.com/FSQ-lab/amkernel/issues/131)。#98 的正式平台验证不由本实现替代；#131 负责本方案的 Skill、安装接入、隔离行为验收与文档。本记录不是看板状态来源。

## 1. 结论与设计原则

在现有单一 `amkernel` Skill 内新增 `references/ios-setup.md`，提供目标相关性、依赖与授权管理、人工操作引导，以及 WDA/签名判断。官方 XCUITest 技能仍负责 driver、构建与设备配置的具体步骤；不复制成第二套教程。

不新增 Kernel API、移动自动化 wrapper、后台服务、工作流引擎、依赖管理器或跨项目依赖登记服务。平台知识仍留在 Skill、实验和行为验证中。

用户只提供目标；Agent 自动处理版本、路径、driver、设备 ID、capabilities、环境检查和获准的安装。用户只承担无法代办的账号登录、协议与安全确认，以及必要的物理连接操作。

基本规则：

1. 只读发现自动进行；已有可执行且适用的工具优先复用。
2. 修改前披露范围；已有明确授权不重复确认，范围外效果另行确认。
3. 密码、PIN、双重认证码和私钥不通过聊天传递，不进入日志或记录。
4. 每次人工交互只给当前需要的一步；用户完成后由 Agent 检查并继续。
5. 安装存在、约束满足、设备开发可用、WDA 可启动及 live session 是不同证据。
6. 只清理当前任务能确认拥有的临时资源，保留用户要求的设置结果。

## 2. 请求范围与完成定义

| 用户请求 | 允许推进到哪里 | 完成标准 |
| --- | --- | --- |
| “看看环境缺什么” | 只读发现、静态检查 | 分层列出已有、缺失、不适用和未知；不安装、不启动服务或 WDA、不创建 session |
| “配置 iPhone 环境” | 披露并获准的安装、账号/设备设置、签名准备、官方 readiness 检查 | 前置条件检查通过；WDA live 启动未验证必须明确，不把 setup-only 自动升级成 session |
| “配置并验证能控制这台手机” | 上述准备，加一次明确披露的最小连接验证 | 通过 `python_exec` 创建 session、完成无害 live 查询、退出临时 session；分别报告服务和外部资源状态 |
| “操作这台手机完成某任务” | 准备后直接执行用户场景 | 验证具体任务结果，不先插入额外 smoke 场景 |

建议保留现有 setup-only 不建 session 的契约。如果用户只说“设置好，让我能用”，先说明“环境准备完成后可做一次真实连接验证”；没有明确包含验证的授权时，询问一次是否进行该验证，而不是默默启动。所有安装和安全变更仍需具体披露。

“配置完成”不承诺后续长期可用：设备断开、签名到期、driver/Xcode 更新均可能使之前证据失效。

## 3. 现有机制与实现落点

依据：[架构](../architecture.md)、[ADR-0007](../decisions/0007-global-runtime-project-activation.md)、[现有 Skill](../../src/amkernel/skill/SKILL.md)、[Appium seam](../../src/amkernel/skill/references/amkernel-appium.md)、[Android 设置参考](../../src/amkernel/skill/references/android-setup.md)。

| 文件/机制 | 实施变化 |
| --- | --- |
| `src/amkernel/skill/references/ios-setup.md` | 新增本方案的 iPhone procedural seam，不是官方来源 |
| `src/amkernel/skill/SKILL.md` | iPhone 真机 setup/readiness 先读新 reference，再走已校验的官方 XCUITest/真机路由；模拟器路由不改 |
| `src/amkernel/skill/references/amkernel-appium.md` | 链接新 reference，保留通用 Runtime、发现、执行和清理规则，避免复制 |
| `src/amkernel/distribution.py::_skill_files` | 将新 reference 纳入现有打包、激活与文件所有权流程；不另造安装器 |
| 已有 distribution/Skill 行为验证 | 覆盖新文件的实际安装与新用户路径，不用 Markdown 关键词断言代替行为证据 |
| `README.md`、`docs/development.md`、`CHANGELOG.md` | 更新用户入口、隔离验证方法与变更说明；真实设备与签名资格仍需独立授权和证据 |

不修改 Runner、Supervisor、Server、MCP schema；不增加 iPhone CLI 子命令；不修改官方来源 commit、archive、manifest 或 verifier。

官方 Skill 仍必须通过现有 provenance 校验。缺失或漂移时停止消费该官方路由，披露问题并通过 AMKernel installer 获准修复；不能下载未固定的新 Skill 绕过校验。已存在且无需消费官方设置指引的 session 不应因此被无关检查阻塞。

## 4. 依赖管理

### 4.1 所有权与发现

| 依赖 | 管理者 | 发现/复用依据 | 变更边界 |
| --- | --- | --- | --- |
| Python、AMKernel、Appium Python Client、Selenium 及传递依赖 | `uv tool` 共享 Runtime | 当前 MCP/CLI 指向的解释器、安装来源/extras、包 metadata、实际导入与依赖一致性 | 保留 AMKernel 版本/来源及所有 extras；不得直接 `pip install`、使用系统 Python 或项目 `.venv` 代替 |
| Node/npm、Appium Server | 现有包管理器/安装方式 | 实际可执行路径和版本；Appium 声明的 Node 约束 | 沿用已有 backend；不为 PATH 缺失或非最新版而重装 |
| XCUITest driver | Appium extension CLI | 同一个 `APPIUM_HOME` 的安装 metadata、实际 doctor 输出 | 不影响共享 session；不默认更新所有 drivers |
| Xcode、iOS SDK、开发工具 | Xcode/Apple 官方渠道 | `DEVELOPER_DIR`、`xcode-select -p`、执行版本和 SDK 检查 | 优先任务级 `DEVELOPER_DIR`；不默认全局切换 Xcode、不为真机安装 simulator runtime |
| WDA 源码与构建产物 | 所选 driver、Xcode | driver 内实际 WDA 版本/位置；候选产物平台、架构、签名和目标适配 | 不另装独立 WDA；不把升级 driver 与更新 WDA 当成无影响操作 |
| 证书、私钥、profile、账号与设备授权 | Xcode、钥匙串、iPhone | 有效期、匹配关系、可用签名身份和当前设备状态 | 新建/续签/设备注册/信任均为披露的效果；不要求用户导出私钥 |

Runtime 中的传递依赖由 uv 解析。Appium/driver 的 Node 依赖由原有 npm/Appium 工具管理；不逐项手动安装 Selenium 或 Node 传递依赖。

### 4.2 版本策略

- 仓库 `uv.lock` 只锁开发/验证环境，不是用户 `uv tool`、Appium 或 Xcode 的统一锁。
- 当前 installer 的 `Appium-Python-Client>=5.2.5` 策略保持不变；本方案不引入全栈固定版本表。
- 先检查 applicable package constraints，再单独引用官方 tested-range evidence。沿用 Skill 的 `satisfied-constraints`、`warning-only`、`unverified`、`observed-requirement-violation`、`proven-incompatible` 五类，不新增相冲突的兼容性标签。
- 导入/`uv pip check` 成功只证明客户端依赖层；doctor 不证明 live session。
- 新装使用满足约束、目标需求且有适用证据的精确版本；不写“自动装 latest”。无法确定可用组合时继续查当前官方 metadata/文档，而不是凭历史实验版本猜测。
- 已有组合不因 warning 或缺少覆盖而自动升级/降级；真实冲突只修复相关组件。
- 更新 driver 后重新确认 WDA/产物适配；更新 Xcode、iOS 或签名后重新确认受影响层，不机械重装整套环境。

### 4.3 变更披露与恢复

一次披露包含本次已知的所有变更：组件与精确版本/目标、官方来源和 backend、位置、任务级或持久设置、跨项目影响、账号/协议/管理员权限/重启、原状态和恢复方法。

获准后由 Agent 执行可代办操作；Apple Account 登录、协议接受、锁屏码、钥匙串确认和设备信任由用户在原生界面完成。新发现的范围外效果再次确认，不用总括授权自动注册设备或改变钥匙串访问策略。

Runtime 修复通过原 uv tool 来源和已记录 extras 重建，保留 AMKernel 版本；共享环境替换前协调受影响 Kernel，替换后重新连接。不得在正在依赖该环境的任务中无提示强制替换。

Appium 环境默认复用。共享服务/driver 有冲突时，先检查任务是否能安全使用隔离且 task-owned 的 Appium home 与端口；需要额外安装时披露。无法避免设备/session 冲突时阻塞，不抢占设备。

记录为任务内的最小安装/变更事实，不新增持久 registry 或 installer receipt schema。记录组件版本、来源、位置、约束依据、变更前后、检查结果与恢复限制；敏感签名信息和设备标识不进入公开证据。当前 CLI receipts 不宣称管理外部工具。

## 5. 设备与 WDA 决策

### 5.1 先确认目标当前可用

使用选定 Xcode 的 `devicectl`，按本机 help/schema 解释当前 JSON。单独报告：

- discovered：设备被列出；
- connected：存在当前传输连接证据；
- usable-for-development：当前信任、Developer Mode 和必要开发服务可用；
- ready-for-xcuitest：选定 driver、签名/profile 与目标 WDA 路径的前置条件已核实。

以上是已有报告层，不是新增 workflow state。历史 paired/Developer Mode 信息不能覆盖当前 unavailable；未知保持未知。UI Automation 等要求按当前官方指导和目标实际情况检查，Safari/Web Inspector 仅在 web/hybrid 范围需要时检查。

发现多个匹配且可用的目标时才要求用户按熟悉的设备名称选择；不要求用户找 UDID。设备锁定/断开时，引导连接和本人解锁，不远程解锁、不替用户点安全提示。

### 5.2 WDA 复用决策表

| 当前证据 | 行动 |
| --- | --- |
| 已有 task-owned 或明确获准复用的 WDA endpoint，且能绑定目标设备 | 验证小范围 `/status` 及 target/transport 绑定；活跃的他人 session 不抢占；获准创建 Appium session 时才 attach |
| 有已安装 WDA 或本地产物，且平台/架构、Bundle ID、签名/profile、目标覆盖和所选启动路径满足要求 | 作为“复用候选”；明确授权验证时尝试启动，成功后才称“启动已验证” |
| endpoint 不可达、手机离线/锁定、权限未确认、转发/开发服务异常 | 先定位连接/权限/服务问题；不可直接归因为签名 |
| 未安装 WDA且无适用产物 | 使用所选 driver 已有源码和 Xcode 构建、签名及安装；先取得相关授权 |
| profile 过期/撤销、证书无效、缺少所需私钥、Bundle ID/Team 不匹配、profile 不覆盖目标 | 修复对应签名条件，再构建或重签；尽量保留其他有效组件 |
| 二进制/SDK/启动路径不适配 | 按实际错误解决兼容性问题；不能仅靠重签名解决 |

`useNewWDA=true` 会强制卸载已有 WDA，不作为默认修复。`webDriverAgentUrl` 只用于已确认的现有实例；`usePreinstalledWDA`/`usePrebuiltWDA` 只在所选版本、设备和产物满足对应条件时选择，不是普遍快捷开关。

不因 WDA 图标存在、签名结构校验成功或通用 `xcodebuild` exit code 就认定可启动或需重签；必须看具体失败日志。仅本地签名/profile 检查无法证明设备当前的全部信任/在线验证条件。

### 5.3 启动时机与责任

默认 WDA 与 Appium session 的建立联动，由 XCUITest driver 启动/复用。Appium Server 由宿主工具在 `python_exec` 外监督；session 创建、live 查询和退出必须使用实际 Runtime 的官方 Python Client，通过 `python_exec` 完成。

准备签名可以使用 Xcode/宿主工具进行不启动测试的构建；不通过手动 `Product > Test` 或独立 shell session 绕过 setup-only 的启动边界。需要实际启动时，进入已明确授权的验证/场景范围。若官方特定启动路径确实需要不同机制，先确认该机制与本方案授权/执行边界是否一致，不默默替换。

首次启动前预告可能的安全交互，检查手机当前连接与解锁条件。启动 call、等待用户动作、结果判断和清理不要塞进一个不可观察的长 call；也不把每个 WebDriver command 拆成一轮。

## 6. 签名与人工操作引导

### 6.1 最短签名路径

1. 有有效 WDA/产物且适用：优先复用，不要求登录账号或导出证书。
2. 本机已有合适的 Xcode signing identity/profile：Agent 使用已观察到的 Team、Bundle ID 和 task-scoped 构建配置。
3. 需要首次配置或续签：默认使用 Xcode 账号和自动管理签名能力。免费账号可用，不默认要求购买付费会员；按所选版本官方指引处理免费账号的明确 Bundle ID/profile 路径。
4. 需要用户登录时，打开或指向 Xcode 当前版本的账号界面；用户本人完成登录和双重认证。多个 Team 的选择无法从证据确定时才询问。
5. 需要新建最小 Xcode 项目生成 profile、注册设备或更改项目签名时，先披露这些具体效果。Agent 提供唯一标识并处理技术配置；用户只处理账号/确认。避免直接修改 npm 安装目录内 WDA 工程，因为更新 driver 可能覆盖修改。
6. 验证 profile 有效期、目标覆盖、Team/Bundle ID/entitlements 匹配以及所需私钥可用。满足条件后构建/安装；安装仍不等于启动已验证。

不默认走导出 `.p12` + 下载 WDA + 安装额外重签工具的路线。只有现有产物和签名资料使该路径更适合且用户授权时才使用；不为了调用某个 helper 而增加安装。

### 6.2 PIN 与提示处理

| 提示类型 | 用户层引导 | 完成后的检查 |
| --- | --- | --- |
| iPhone 锁定或“信任此电脑” | “请在手机上解锁/确认信任；密码直接输入手机，不要发给我。” | 当前连接及开发服务，不仅检查用户口头确认 |
| Developer Mode 首次启用 | 说明降低设备安全限制、需要重启；获准后按当前系统界面引导重启后的开启和设备密码确认 | 重新发现设备并确认当前 Developer Mode/服务 |
| 开发者 App 未受信任 | 只有实际出现相应错误时，引导 Settings 中对应开发者的信任；注明网络验证要求 | 检查目标信任/启动结果，不预设所有手机都会出现同一路径 |
| Mac 钥匙串访问确认 | “请确认系统弹窗中的签名工具和证书属于本次操作，在 Mac 弹窗内完成确认。” | 构建/签名结果；不默认要求“始终允许”，不修改访问控制 |
| Apple Account 登录/双重认证 | 在 Xcode/Apple 界面完成 | 账号/Team/signing identity/profile 是否可用，不读取认证凭据 |

不把所有提示称为“WDA PIN”。用户已报告的 PIN 阻塞要认真处理，但每次根据发生位置、日志和当前界面区分原因；不预设每次 WDA 启动都需输入密码。

用户收到操作提示后，暂停依赖该授权的后续动作。不要留下无限重试的启动 call 等待用户，也不要将超时自动转为重签名理由。完成后重新检查可能变化的前置条件。

## 7. 失败、等待与清理

- 正在等待用户操作：说明在哪台设备、哪个界面、完成什么动作及预期结果；不是“请自行配置 Xcode”。不让用户解决技术未知项。
- 创建 session 超时或异常：检查 `status` 和 `kernelState`；不能认为超时意味着远程 session/WDA 不存在。
- driver 对象存在且 Kernel 存活：依据现有 seam 做一个小范围 live 查询再决定复用。
- 远程 session 身份不明确：通过已拥有的 Appium 服务日志/诊断获取可识别事实；无法确认所有权就不删除、不盲目重建。
- Kernel 死亡：Python namespace 已丢失，外部状态未知；不隐式重建 Kernel。不用 WDA endpoint 正常替代 session reconciliation。
- 只有确认上一尝试已结束、相关资源已核实且用户安全动作已完成后才再次创建 session；Appium 当前 session 冲突是阻塞，不是清空所有 session 的理由。
- 最小验证只做无害的当前窗口/页面查询，不点击业务操作、提交表单或重置 App 数据。需使用首页作为启动目标时，先披露可能改变前台画面及 driver 的适用自动设置效果。
- `driver.quit()` 成功只证明 Appium session 退出，不证明 WDA 进程消失。不清除签名/profile、不卸载 WDA、不撤销信任或关闭 Developer Mode 来“恢复干净”。
- 只停止本次创建的 Appium 服务和转发等临时资源；共享资源保持不动。验证后默认停止临时服务，不新增常驻 launch agent。
- 报告验证结果和 cleanup 分开；结果成功但 cleanup 失败不得报告完全清理。

## 8. 用户交互模板

模板只约束信息与决策，不固定模型措辞；不靠字符串测试验收。

**发现结果**

> 已找到可用的 Xcode 和手机自动化工具，不需要重复安装。目前手机还没有连接成功。请用数据线连接并在手机上解锁，我会继续检查。

**安装披露**

> 还缺少 [组件]，需要从 [官方来源] 安装 [版本] 到 [位置]。它会影响 [明确范围]，需要 [账号/协议/权限/重启，或无需]。我会完成安装和检查；[原状态及恢复方式]。是否按这个范围继续？

**签名准备**

> 手机上的自动化助手需要 [首次授权/更新已失效的授权]。我会处理构建和安装；你只需要在 Xcode 中登录自己的 Apple Account，并在系统弹窗中确认。不会删除其他应用或数据。

**真实验证**

> 环境准备已完成，还没有验证手机上的助手能否实际启动。接下来可以建立一次临时连接，只读取当前页面，不进行业务操作；可能需要你在手机/Mac 上确认安全提示。验证后会退出临时连接并停止本次临时服务。是否现在验证？

**完成/阻塞**

> [环境准备/真实连接验证] 已完成。[未验证项或 cleanup 限制]。如果阻塞，只给当前需要用户完成的一个动作，并说明完成后会自动检查什么。

## 9. 验证与验收方案

以下矩阵是验收契约；实际执行的检查、行为场景及未覆盖边界另见 [iPhone 设置实验](appium-agent-behavior.md#18-iphone-setup-skill-131)。静态文档、helper 帮助、模拟 endpoint 和模型最终回答均不能单独证明真实 iPhone 可用。

### 9.1 行为验收矩阵

| 场景 | 必须观察到的行为 | 必须拒绝的行为 |
| --- | --- | --- |
| 单台已连接且依赖适用的真机，setup-only | 复用；目标相关检查；无 session | 重装、启动 WDA、安装模拟器组件 |
| 已列出但 unavailable 的 iPhone | 保留发现证据，阻塞连接，引导用户 | 用历史 paired/Developer Mode 宣称当前可用 |
| 多台当前可用手机 | 使用熟悉名称做一次目标选择 | 请求用户找 UDID 或随机选设备 |
| 缺少 Runtime Client | 明确定位实际 Runtime，披露跨项目影响，uv 保留原版本/来源/extras 修复 | pip 污染、修改项目 `.venv`、顺带升级 AMKernel |
| Client warning 或缺少 tested coverage | 按已有五类报告；相关检查而非强制升级 | 把 warning 变成必修冲突或整套降级 |
| 缺少 driver | 复用 Node/Appium/Xcode，获准只装该 driver | 批量升级其他 drivers 或写错 `APPIUM_HOME` |
| 有适用 WDA/产物 | 优先复用，真实证明前仅称候选 | `useNewWDA=true` 强制重装 |
| profile 过期/不覆盖目标 | 正确归因，披露修复并引导账号/授权 | 因端口超时就重签；要求发送私钥/PIN |
| 手机 PIN 或钥匙串确认阻塞 | 原生界面人工确认；暂停依赖动作，完成后复查 | 无界无限等待、重试风暴、代填凭据、默认“始终允许” |
| 官方 Skill 来源校验失败 | 停止路由，获准通过 installer 修复 | 未固定下载或绕过 verifier |
| 明确授权 live 验证 | 实际 `python_exec` session、小范围 live 查询、owned cleanup | 宿主 Python 创建 Appium session；只有 `/status` 就报通过 |
| 验证超时且远程状态未知 | reconciliation 与所有权判断；真实报告未知 | 盲目创建第二 session 或清空共享 sessions |
| 共享服务/session 正在使用 | 保留；只在安全且获准时使用隔离资源 | 抢设备、重启共享 server、卸载共享 WDA |
| Kernel 死亡/cleanup 失败 | namespace 与外部生命周期分开报告 | 隐式重建、把退出 session 称为已删除 WDA |

### 9.2 验证层次

1. 安装验证：构建实际 wheel，在外部临时项目激活，证明新 reference 进入现有安装/所有权机制，官方 receipt 验证仍通过；沿用现有 distribution contract tests。
2. 原生 Agent 行为验证：沿用 installed-wheel/native-client harness 和外部观察原则；扩展 iPhone discovery、签名、人工授权与超时场景。合成 host 工具不能执行真实安装或输入凭据；检查动作 journal 和实际 endpoint 请求，不检查固定生成代码或文字。
3. 真实机 smoke：在 owner 授权的 iPhone 上，通过实际 Agent 的 `python_exec` 验证创建、live 查询、退出和 owned server cleanup。缺失手机连接、账号、授权或签名时保留 blocker，不用合成通过替代。
4. 签名修复路径：另用 owner 授权的失效/首次签名环境验证；不破坏正常使用的证书或撤销 profile 来制造失败。仅复用路径通过不能声称重签路径通过。
5. 独立 review：加载路径、授权、秘密保护、shared ownership 和生命周期为 load-bearing review 项；不能凭草案 owner review 宣称实现通过。

正式平台资格仍受已有 Issue/Stage 契约约束，本方案 smoke 不替代原有正式序列，也不扩展产品支持范围。

## 10. 风险与 review 决策

| 决策 | 推荐 | 代价/边界 |
| --- | --- | --- |
| “设置好”的默认完成定义 | 保持 setup-only 不建 session；明确包含真实验证时才启动 | 可能多一次验证选择，但避免未授权测试和误报端到端成功 |
| 首次/续签默认路径 | Xcode 现有账号、钥匙串及 profile 能力；免费账号可用 | 少量必要原生界面操作；不要求私钥导出或额外 resigner |
| 依赖隔离 | Runtime 保持 ADR-0007 用户级共享；Appium 先复用，冲突才按需隔离 | 共享变更需披露协调；不增加每项目 Runtime/profile 系统 |
| 版本策略 | 不改 installer baseline；已有适用环境保留，新装按目标/声明/官方证据选精确版本 | 不提供未经验证的全栈锁；每次验证记录实际组合 |
| 设置后的服务 | 临时验证服务退出；保留 WDA 安装和有效签名配置 | 下次通过任务工具启动服务；不提供开机自启或后台 daemon |

主要风险：Xcode/iOS UI 和启动机制随版本变化；官方 latest 文档不等于固定 Skill 或本机版本行为；本地签名校验不等于当前设备可运行；启动时的安全交互可能发生在不同位置。解决方式是版本适用性核实、现场证据、一次一动作、明确未知与有限的 owned 尝试，不是增加自动兜底或宽泛重置。

## 11. 调查与实施的证据边界

最初草案阶段读取了本地代码、HANDOFF、架构、ADR-0007、现有行为验证文档，并只读检查 Project #2 与 #98；该阶段没有创建/更新 Issue 或改变状态。Owner 随后接受方案并授权实施，实施和验证记录由 #131 拥有。

前述调查已执行托管 Runtime imports/依赖一致性检查及所选 driver helper 的帮助命令。当时观察到本机 Appium/XCUITest/Xcode 存在、项目 Skill/MCP 未激活、iPhone unavailable；这些不是持久 readiness 或组合资格。实施阶段的隔离安装、MCP 和合成端点验证另行记录，不等于本机 iPhone、签名或 WDA 已就绪。

本机 driver 的 `build-wda` helper 帮助明确只用于 simulator；`sign-wda` 需要 `resigner`。因此方案不把这两个 helper 当作真机默认安装/签名捷径。

官方依据（实施时还需核对固定 Skill 与选定安装版本）：

- [Device Preparation](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/device-setup/)
- [Provisioning Profile](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/provisioning-profile/)
- [Basic Manual Configuration](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/provisioning-profile/basic-manual-config/)
- [Full Manual Configuration](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/provisioning-profile/full-manual-config/)（明确指出直接修改 WDA 工程会受更新影响，不作为默认持久配置）
- [WDA capabilities](https://appium.github.io/appium-xcuitest-driver/latest/reference/capabilities/#webdriveragent)
- [Apple Developer Mode](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)
