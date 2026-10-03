public enum UpgradeCheckMessage {
    public static func text(status: String?, errorType: String?) -> String {
        if status == "up_to_date" { return "当前已是最新可用版本" }
        switch errorType {
        case "not_configured": return "更新服务尚未配置，请联系发布管理员"
        case "download_failed": return "无法获取正式发布清单或产物，请检查网络及正式 Release"
        case "verification_failed": return "发布清单或产物校验失败，当前版本已保留"
        default: return "无法完成更新检查，请稍后重试"
        }
    }
}
