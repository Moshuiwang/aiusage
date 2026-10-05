import Foundation

public enum CollectorSetupError: Error, LocalizedError {
    case invalidServer, missingToken, invalidSource, changedServer
    public var errorDescription: String? {
        switch self {
        case .invalidServer: "请输入有效的 HTTPS 服务地址（不含密码、查询参数或片段）。"
        case .missingToken: "首次连接需要访问令牌。"
        case .invalidSource: "来源标识需以字母或数字开头，只能包含字母、数字、短横线和下划线。"
        case .changedServer: "更换服务地址时需要重新填写该服务的访问令牌。"
        }
    }
}

/// Connection and collection settings belong to the current OS user, outside the App bundle.
public struct CollectorSettingsStore {
    public let root: URL
    public init(root: URL) { self.root = root }
    public var directory: URL { root.appendingPathComponent("collector") }
    public var deviceURL: URL { directory.appendingPathComponent("device.json") }
    public var settingsURL: URL { directory.appendingPathComponent("settings.json") }
    public var limitsURL: URL { directory.appendingPathComponent("limits.json") }
    public var statusURL: URL { directory.appendingPathComponent("status.json") }
    public var isEnabled: Bool { (read(settingsURL)["enabled"] as? Bool) == true }
    public var sourceID: String? { read(deviceURL)["source_id"] as? String }
    public var server: String { read(root.appendingPathComponent("config.json"))["server_url"] as? String ?? "https://aiusage.chunbai.com" }

    public var enrollmentURL: URL { directory.appendingPathComponent("enrollment.json") }
    public var hasToken: Bool { !(read(root.appendingPathComponent("config.json"))["token"] as? String ?? "").isEmpty }
    public var sourceIDs: [String] {
        var ids = sourceID.map { [$0] } ?? []
        for item in read(limitsURL)["providers"] as? [[String: Any]] ?? [] {
            if let id = item["source_id"] as? String, !ids.contains(id) { ids.append(id) }
        }
        return ids
    }

    public var administratorToken: String? {
        let config = read(root.appendingPathComponent("device-admin.json"))
        guard config["server_url"] as? String == server else { return nil }
        return config["token"] as? String
    }
    public func configureAdministrator(token: String) throws {
        guard !token.isEmpty else { throw CollectorSetupError.missingToken }
        try write(["server_url": server, "token": token], to: root.appendingPathComponent("device-admin.json"))
    }

    public func setEnabled(_ enabled: Bool) throws { try write(["enabled": enabled], to: settingsURL) }

    public func configure(server: String, token: String, sourceID: String, home: URL = FileManager.default.homeDirectoryForCurrentUser, awaitingApproval: Bool = false) throws {
        guard var parts = URLComponents(string: server.trimmingCharacters(in: .whitespacesAndNewlines)),
              parts.scheme == "https", let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/" else {
            throw CollectorSetupError.invalidServer
        }
        parts.path = parts.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if !parts.path.isEmpty { parts.path = "/" + parts.path }
        guard let base = parts.string else { throw CollectorSetupError.invalidServer }
        var display = read(root.appendingPathComponent("config.json"))
        if token.isEmpty, let previous = display["server_url"] as? String,
           previous.trimmingCharacters(in: CharacterSet(charactersIn: "/")) != base.trimmingCharacters(in: CharacterSet(charactersIn: "/")),
           !(display["token"] as? String ?? "").isEmpty { throw CollectorSetupError.changedServer }
        let value = token.isEmpty ? (display["token"] as? String ?? "") : token
        guard awaitingApproval || !value.isEmpty else { throw CollectorSetupError.missingToken }
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        guard !sourceID.isEmpty, sourceID.count <= 128, sourceID.first.map({ $0.isLetter || $0.isNumber }) == true, sourceID.unicodeScalars.allSatisfy({ allowed.contains($0) }) else {
            throw CollectorSetupError.invalidSource
        }
        var device = read(deviceURL)
        if device.isEmpty {
            device = ["schema_version": 1, "source_id": sourceID, "platform": "darwin",
                      "timezone": "Asia/Shanghai", "machine": ProcessInfo.processInfo.hostName,
                      "host": ProcessInfo.processInfo.hostName, "os_user": NSUserName(),
                      "token_env": "AI_USAGE_INGEST_TOKEN",
                      "outbox": ["enabled": true, "path": directory.appendingPathComponent("outbox.sqlite").path]]
        }
        device["server_url"] = base + "/ingest"
        display["server_url"] = base
        display["token"] = value
        display["refresh_interval_seconds"] = display["refresh_interval_seconds"] ?? 600
        display["default_period"] = display["default_period"] ?? "today"
        try write(display, to: root.appendingPathComponent("config.json"))
        if !FileManager.default.fileExists(atPath: limitsURL.path) {
            var providers: [[String: Any]] = []
            let codex = home.appendingPathComponent(".codex/auth.json")
            if FileManager.default.fileExists(atPath: codex.path) {
                providers.append(["provider": "codex", "source_id": sourceID + "-codex", "auth_file": codex.path])
            }
            let claude = home.appendingPathComponent(".claude/.credentials.json")
            if FileManager.default.fileExists(atPath: claude.path) {
                providers.append(["provider": "claude", "source_id": sourceID + "-claude", "auth_file": claude.path])
            }
            try write(["schema_version": 1, "timezone": "Asia/Shanghai", "providers": providers], to: limitsURL)
        }
        // Reuse the explicitly configured quota account; never guess among multiple accounts.
        var fingerprintSources = device["account_fingerprint_sources"] as? [String: String] ?? [:]
        if fingerprintSources["codex"] == nil {
            let providers = (read(limitsURL)["providers"] as? [[String: Any]] ?? []).filter {
                $0["provider"] as? String == "codex" && ($0["enabled"] as? Bool ?? true)
            }
            let paths = providers.compactMap { ($0["auth_file"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
            if paths.count == providers.count, Set(paths).count == 1, let path = paths.first {
                fingerprintSources["codex"] = path
            }
        }
        if !fingerprintSources.isEmpty { device["account_fingerprint_sources"] = fingerprintSources }
        try write(device, to: deviceURL)
        try setEnabled(!awaitingApproval)
    }

    public func statusText(isRunning: Bool) -> String {
        guard isEnabled else { return "本机采集已暂停" }
        guard isRunning else { return "本机采集未运行" }
        let status = read(statusURL)
        let jobs = ["usage", "limits"].compactMap { status[$0] as? [String: Any] }
        if jobs.count == 2, jobs.allSatisfy({ $0["success"] as? Bool == true }) { return "本机用量与额度已上报" }
        if jobs.contains(where: { $0["exit_code"] as? Int == 75 }) { return "本机数据已缓冲，等待网络恢复后补推" }
        if jobs.contains(where: { $0["success"] as? Bool == false }) { return "本机采集失败，将在下次定时重试" }
        return "正在采集本机用量与额度…"
    }

    private func read(_ url: URL) -> [String: Any] {
        guard let data = try? Data(contentsOf: url), let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return dict
    }

    private func write(_ object: [String: Any], to url: URL) throws {
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .prettyPrinted])
        // Restrict the temporary file before any credential bytes are written.
        let temp = url.deletingLastPathComponent().appendingPathComponent(UUID().uuidString + ".tmp")
        guard FileManager.default.createFile(atPath: temp.path, contents: nil, attributes: [.posixPermissions: 0o600]) else { throw CocoaError(.fileWriteUnknown) }
        defer { try? FileManager.default.removeItem(at: temp) }
        try data.write(to: temp)
        if FileManager.default.fileExists(atPath: url.path) {
            _ = try FileManager.default.replaceItemAt(url, withItemAt: temp)
        } else {
            try FileManager.default.moveItem(at: temp, to: url)
        }
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
}
