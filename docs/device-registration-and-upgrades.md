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

发布 owner 使用 `scripts/build_signed_release.py` 从干净提交构建并签名；签名私钥必须在仓库外、仅属于当前用户、权限为 `600`，不输出或进入 Git。工具生成公开的签名清单、公钥审核产物及平台包，不自动发布远端。

Ed25519 的使用遵循 [cryptography 官方接口](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)。客户端仅信任代码内固定的 `release_trust.RELEASE_PUBLIC_KEYS`，发布下载不能提供自己的信任根。签名公钥和默认清单地址未配置时安全关闭更新。

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

Mac 使用菜单“检查 App 更新…”；更新器运行于独立复制的 helper，避免替换 App 时破坏更新器自身。候选通过 App 标识、版本、完整构建 SHA、代码签名与内置采集器启动预检后才退出旧 App、等待旧采集器退出并替换。新采集器上报与新摘要缓存检查失败则恢复旧 App；成功保留一个上版本，下一次升级自动轮换。升级不改用户 token、来源身份、原始日志或 outbox。结果写入私有 `last-upgrade.json`，不得把文件切换成功当成生产回源验收。

手动触发检查与升级，不引入客户端短轮询。Linux 依赖环境须通过 `pip install .` 安装项目声明依赖；Mac 内置相同验签依赖，无需用户配置 Python。

## Ops 启用顺序与边界

生产操作由 MBA Ops 完成：

1. 审核并应用 `0015_device_enrollment.sql`，配置独立 `AIUSAGE_DEVICE_ADMIN_TOKEN`，部署对应 Worker。旧共享 token **不具备管理员权限**。
2. 在管理机器配置一次管理员凭据；逐设备验证注册、来源限制、读取权限与撤销，不替用户批量自动批准。
3. 管理签名私钥、固定公开公钥和清单地址，重建正式 Linux 与 Mac 发布产物，按通道逐台发布。
4. 每台设备完成真实升级、上报、用户可见非空数据、健康失败回滚演练；保留既有设备配置和缓冲数据。
5. 所有设备完成注册后可撤掉旧共享 token；只保留管理员凭据与设备凭据的生产模式仍禁止匿名访问。尚未迁移的旧设备需明确安排迁移，不能静默断供。
6. 发布后执行 `scripts/check_cf_usage.py` 回源巡检（等级 7）。未做回源前不宣称生产升级完成。

注册入口限定 4 KiB 请求、16 个待批申请、每小时 32 次新申请、64 个设备凭据记录；写入批量执行，过期申请与旧计数清理。客户端申请和确认均手动单次请求。达到限额时返回明确错误，不无限扩张存储。生产 Secret、签名信任根、真实部署与正式发布均需 Ops 的独立权限，本机不修改生产配置。
