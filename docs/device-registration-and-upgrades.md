# 设备授权与签名升级

对应 [#222](https://github.com/Moshuiwang/aiusage/issues/222)、[#223](https://github.com/Moshuiwang/aiusage/issues/223)、[#224](https://github.com/Moshuiwang/aiusage/issues/224)。任务进度以 GitHub Issue 为准。

## 交付单元与版本

macOS 是一个 App：呈现层读取服务端汇总，独立内置采集器在当前 OS 用户下收集与批量推送。App 退出即停止采集，不再要求单独安装 Python 或两个 LaunchAgent。App 版本来自 `clients/macos/VERSION`；内置采集器和 Linux 采集器版本都来自 `version_contract.COLLECTOR_VERSION`。Worker 的目标版本随正式发布更新，最低支持线单独管理，不随普通升级抬高。

发布清单同时声明 App 版本、采集器版本、通道、完整构建 SHA、最低升级来源版本、发布时间、每个平台产物的大小和 SHA-256。Linux 产物为源码包；Mac 产物包含完整 App 与内置运行时。

## 新机器如何连接

新设备自己生成 256 位凭据与独立申请秘密，并先以 `600` 权限保存申请。服务端只接收它们的 SHA-256 摘要，不存原始凭据。申请十分钟有效，管理员需要核对配对码、机器、OS 用户、来源和读取权限。批准后设备激活自己早已保存的凭据；网络不传输管理员 token，也无需 SSH 写入新机器。

Mac 首次连接时填服务地址和来源标识，令牌留空申请授权。管理员在管理机器的菜单“管理设备申请…”逐台批准；申请机器选择“检查本机授权”后开始采集。申请未批准时采集保持暂停。更换服务地址不能自动复用旧服务的凭据。

Linux 在所属 OS 用户下运行，必须把用量和所有额度 provider 的来源标识一并申请：

```sh
ai-usage-widget devices enroll --server https://aiusage.chunbai.com \
  --source-id linux-alice --source-id linux-alice-codex
# 管理员核对配对码、机器、用户和来源后，在管理机器批准：
ai-usage-widget devices list --server https://aiusage.chunbai.com
ai-usage-widget devices approve --server https://aiusage.chunbai.com --request-id REQUEST_UUID
# 回到申请机器：只检查一次，不做短轮询。
ai-usage-widget devices check --token-env-file "$HOME/.local/share/ai-usage/secrets/ingest.env"
```

管理员命令只读取 `AI_USAGE_DEVICE_ADMIN_TOKEN` 环境变量；Mac 管理凭据独立保存在当前用户的私有文件里，并绑定服务地址。Linux 设备凭据使用既有 systemd 的 `EnvironmentFile` 入口；`--token-env` 可明确指定设备配置中的变量名。凭据值不打印，也不放入命令行参数。

新设备只能上报已批准来源；无读取权限的 Linux 设备不能读取全局汇总。额度来源由 owner 解析后的实际 `source_id` 判权限，包括省略字段后的默认值。有效设备不能重复占用同一个来源。设备不能批准其他设备，批准后不能扩大权限；撤销后立即失去上报和读取权限。

```sh
ai-usage-widget devices revoke --server https://aiusage.chunbai.com --request-id REQUEST_UUID
```

源身份应沿用已有配置，不能为了重新注册创造重复来源。原始日志、provider 账户配置和 outbox 不因注册改变。

## 发布与升级

### Release 管理规范

GitHub Release 是设备升级产物的发布入口；Milestone 管交付范围，Issue 管任务与证据，三者互相链接。菜单栏升级仍由用户手动触发，不增加后台短轮询。仅修改工作区版本号、安装本机 App 或上传草稿，不算完成正式发布。

1. **版本与标签**：Mac App 与 collector 分别使用 `MAJOR.MINOR.PATCH`，保持各自唯一版本来源（`clients/macos/VERSION` 与 `version_contract.COLLECTOR_VERSION`）。修复使用 PATCH，新增功能使用 MINOR；不兼容变化须单独评审，并遵守现有 API 合约。包含 Mac App 的联合发布标签为 `v<app_version>`；仅采集器发布为 `collector-v<collector_version>`。发布清单同时记录两个版本，不要求数字相同。正式发布过的版本不覆盖包、不移动标签，修复另发新版本。
2. **源码与门禁**：正式产物必须来自干净、可追溯且已通过要求检查的提交，并按 `scripts/merge_pr.sh` 合并。草稿可绑定未合并候选 SHA，但发布前必须确认最终合并提交；提交或内容变化后重新生成并验签产物。不得用 Release 绕过 CI，也不得把本机安装版本当成默认分支已经交付。
3. **平台产物**：复用 `scripts/build_signed_release.py`，一次生成签名清单和本次支持的平台包。平台、架构、App/collector 版本、构建 SHA、下载 URL、大小与 SHA-256 必须对应；不宣称未生成或未验收的平台可升级。签名私钥留在发布 owner 的仓库外私有目录，不上传 Release；公钥固定在客户端代码，不能从下载包取得新的信任根。
4. **草稿与正式发布**：先建 draft Release、上传包与 `release-manifest.json`、写发布说明，再核对清单签名、全部附件大小/哈希、安全解包及候选预检。草稿和 prerelease 不作为 stable 可用更新。当前客户端固定读取 GitHub `releases/latest/download/release-manifest.json`，因此被选为 latest 的正式 Release 必须提供完整、有效且前向版本检查可接受的 stable 清单与所需平台包。仅采集器发布也必须验证现有 Mac 用户的检查行为；不适用的版本不能被误报为可升级。
5. **发布说明**：写明用户变化、App/collector 版本、准确源码 SHA、支持平台、已知限制、服务端前置条件、回滚方式和关联 Issue/Milestone。测试、CI、部署、用户可见验证与回源证据分别记录，未知项明写未知。升级检查需区分已是最新版、网络/下载失败、清单校验失败与发布服务未配置；现有笼统提示作为 #223 的交付缺口跟踪。
6. **服务依赖与验收**：注册接口、D1 迁移和管理员配置按下节 MBA Ops 顺序完成，发布 owner 按机器权限生成与发布产物。正式发布前完成离线候选预检与回滚验证；发布后逐平台完成真实升级、配置/outbox 保留、非空数据和失败恢复验证，并回源巡检 Cloudflare 水位。Milestone 只有相关 Issue 验收缺口补齐才关闭，不能仅因 Release 已发布关闭。
7. **失败处理**：校验、预检或升级健康检查失败时保留或恢复旧版，不关闭安全校验，不静默降级为任意包安装。正式产物不可原位修改；严重发布缺陷先阻止有问题版本继续被当作 latest，核验旧版可用性，再发布修复版本，不能把旧版包装成新版本突破前向检查。

GitHub 管理使用各机器规定的 App API 入口，不依赖浏览器个人登录；工作流权限、生产部署权限与 Release Contents 权限分别核验。

发布 owner 使用 `scripts/build_signed_release.py` 从干净提交构建并签名；签名私钥必须在仓库外、仅属于当前用户、权限为 `600`，不输出或进入 Git。工具生成公开的签名清单、公钥审核产物及平台包，不自动发布远端。

Ed25519 的使用遵循 [cryptography 官方接口](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)。客户端仅信任代码内固定的 `release_trust.RELEASE_PUBLIC_KEYS`，发布下载不能提供自己的信任根。当前版本已固定发布公钥及 GitHub Releases 的公开清单地址；签名私钥保存在发布 owner 的仓库外私有目录。

```sh
# 签名发布 owner；先在源码中固定正式公钥，再从干净提交重建所有产物。
python scripts/build_signed_release.py --output .build/release \
  --artifact-base-url HTTPS_RELEASE_ASSET_BASE \
  --minimum-collector-version 0.3.0 --signing-key PRIVATE_KEY_OUTSIDE_REPO \
  --mac-app "PATH_TO/AI Usage Menu Bar.app"

# Linux 设备；使用当前采集器所属 OS 用户及其已配置的 Python 环境。
ai-usage-widget upgrade check
ai-usage-widget upgrade stage --destination "$HOME/.cache/ai-usage/candidate-VERSION"
ai-usage-widget upgrade apply --root "$HOME/.local/share/ai-usage"
```

客户端依次完成验签、通道与前向版本检查、大小及 SHA-256 校验、安全解包和候选入口启动预检。失败产物不会成为可安装目录。Linux 继续使用已有 release/current/previous 原子切换机制，暂停原定时任务后切换；新版本须能采集并实际上报，健康检查失败回滚，再恢复定时任务。system 级多用户部署需由各 OS 用户与 Ops 协调，不能由 root 代采其他用户数据。

Mac 使用菜单“检查 App 更新…”；更新器运行于独立复制的 helper，避免替换 App 时破坏更新器自身。候选通过 App 标识、版本、完整构建 SHA、代码签名与内置采集器启动预检后才退出旧 App、等待旧采集器退出并替换。新采集器上报与十分钟内的非空摘要缓存检查失败则恢复旧 App；成功保留一个上版本，下一次升级自动轮换。升级不改用户 token、来源身份、原始日志或 outbox。结果写入私有 `last-upgrade.json`，不得把文件切换成功当成生产回源验收。

手动触发检查与升级，不引入客户端短轮询。Linux 依赖环境须通过 `pip install .` 安装项目声明依赖；Mac 内置相同验签依赖，无需用户配置 Python。

## Ops 启用顺序与边界

生产操作由 MBA Ops 完成：

1. 审核并应用 `0015_device_enrollment.sql`，配置独立 `AIUSAGE_DEVICE_ADMIN_TOKEN`，部署对应 Worker。旧共享 token **不具备管理员权限**。
2. 在管理机器配置一次管理员凭据；逐设备验证注册、来源限制、读取权限与撤销，不替用户批量自动批准。
3. 发布 owner 保管签名私钥；公钥及公开清单地址已固定在源码。重建正式 Linux 与 Mac 发布产物，按通道逐台发布。
4. 每台设备完成真实升级、上报、用户可见非空数据、健康失败回滚演练；保留既有设备配置和缓冲数据。
5. 所有设备完成注册后可撤掉旧共享 token；只保留管理员凭据与设备凭据的生产模式仍禁止匿名访问。尚未迁移的旧设备需明确安排迁移，不能静默断供。
6. 发布后执行 `scripts/check_cf_usage.py` 回源巡检（等级 7）。未做回源前不宣称生产升级完成。

注册入口限定 4 KiB 请求、16 个待批申请、每小时 32 次新申请、64 个设备凭据记录；写入批量执行，过期申请与旧计数清理。客户端申请和确认均手动单次请求。达到限额时返回明确错误，不无限扩张存储。生产 Secret 与 Worker 真实部署需 Ops 权限；发布 owner 可用本机发布签名密钥和 GitHub Contents 权限生成并发布签名产物。本机不修改生产配置。
