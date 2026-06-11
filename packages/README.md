# Shared Packages

`packages/` 放跨客户端共享资产，不放终端采集逻辑。

- `client-contracts/`：Web / mobile / widget / desktop client 共享的数据合同、fixture 和字段说明。
- `design-tokens/`：跨端视觉 token、状态色、间距和组件密度规则。

规则：

- 共享包只能描述展示合同和视觉规则。
- 不放 token、生产配置、usage 原始日志或本地机器路径。
- 不把共享包变成新的业务聚合层；usage / limits 口径仍由 server read model 决定。
