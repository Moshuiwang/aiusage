import Foundation
import XCTest
@testable import AIUsageMenuBarCore

final class CollectorSettingsTests: XCTestCase {
    func testSetupWritesPrivateFilesAndPreservesSourceAndOutboxOnReconnect() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = CollectorSettingsStore(root: root)
        try store.configure(server: "https://example.test", token: "secret-test", sourceID: "mac-test", home: root)
        XCTAssertTrue(store.isEnabled)
        var device = try JSONSerialization.jsonObject(with: Data(contentsOf: store.deviceURL)) as! [String: Any]
        XCTAssertEqual(device["source_id"] as? String, "mac-test")
        XCTAssertEqual(device["server_url"] as? String, "https://example.test/ingest")
        device["outbox"] = ["enabled": true, "path": "/original/outbox.sqlite"]
        try JSONSerialization.data(withJSONObject: device).write(to: store.deviceURL)
        try store.configure(server: "https://example.test/", token: "", sourceID: "different", home: root)
        let newDevice = try JSONSerialization.jsonObject(with: Data(contentsOf: store.deviceURL)) as! [String: Any]
        XCTAssertEqual(newDevice["source_id"] as? String, "mac-test")
        XCTAssertEqual((newDevice["outbox"] as? [String: Any])?["path"] as? String, "/original/outbox.sqlite")
        let config = try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("config.json"))) as! [String: Any]
        XCTAssertEqual(config["token"] as? String, "secret-test")
        for url in [store.deviceURL, store.settingsURL, root.appendingPathComponent("config.json")] {
            let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
            XCTAssertEqual((attrs[.posixPermissions] as? NSNumber)?.intValue, 0o600)
        }
        try store.setEnabled(false)
        XCTAssertFalse(store.isEnabled)
    }

    func testInvalidConnectionNeverEnablesOrWritesSecrets() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = CollectorSettingsStore(root: root)
        XCTAssertThrowsError(try store.configure(server: "http://example.test", token: "secret-test", sourceID: "test", home: root))
        XCTAssertThrowsError(try store.configure(server: "https://user:secret@example.test", token: "secret-test", sourceID: "test", home: root))
        XCTAssertThrowsError(try store.configure(server: "https://example.test", token: "", sourceID: "test", home: root))
        XCTAssertFalse(store.isEnabled)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("config.json").path))
    }
    func testPendingPairingAndAdministratorAreSeparateAndChangingServerRequiresNewCredential() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = CollectorSettingsStore(root: root)
        try store.configure(server: "https://example.test", token: "", sourceID: "mac-test", home: root, awaitingApproval: true)
        XCTAssertFalse(store.isEnabled)
        XCTAssertFalse(store.hasToken)
        XCTAssertEqual(store.sourceIDs, ["mac-test"])
        try store.configure(server: "https://example.test", token: "test-device", sourceID: "mac-test", home: root)
        try store.configureAdministrator(token: "test-admin")
        XCTAssertEqual(store.administratorToken, "test-admin")
        XCTAssertThrowsError(try store.configure(server: "https://other.test", token: "", sourceID: "mac-test", home: root))
        XCTAssertEqual(store.server, "https://example.test")
    }

    func testCodexAccountPathIsConfiguredFromCreatedLimits() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let auth = root.appendingPathComponent(".codex/auth.json")
        try FileManager.default.createDirectory(at: auth.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data().write(to: auth)
        let store = CollectorSettingsStore(root: root)
        try store.configure(server: "https://example.test", token: "test-device", sourceID: "mac-test", home: root)
        let device = try JSONSerialization.jsonObject(with: Data(contentsOf: store.deviceURL)) as! [String: Any]
        XCTAssertEqual(device["account_fingerprint_sources"] as? [String: String], ["codex": auth.path])
        let attrs = try FileManager.default.attributesOfItem(atPath: store.deviceURL.path)
        XCTAssertEqual((attrs[.posixPermissions] as? NSNumber)?.intValue, 0o600)
    }

    func testReconnectUsesExistingExplicitLimitsAndPreservesExplicitFingerprintPaths() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = CollectorSettingsStore(root: root)
        try store.configure(server: "https://example.test", token: "test-device", sourceID: "mac-test", home: root)
        let auth = root.appendingPathComponent("custom-codex-auth.json").path
        try JSONSerialization.data(withJSONObject: ["providers": [["provider": "codex", "auth_file": auth]]]).write(to: store.limitsURL)
        try store.configure(server: "https://example.test", token: "", sourceID: "ignored", home: root)
        var device = try JSONSerialization.jsonObject(with: Data(contentsOf: store.deviceURL)) as! [String: Any]
        XCTAssertEqual(device["account_fingerprint_sources"] as? [String: String], ["codex": auth])
        XCTAssertEqual(device["source_id"] as? String, "mac-test")
        let explicit = ["codex": "/explicit/codex.json", "claude": "/explicit/claude.json"]
        device["account_fingerprint_sources"] = explicit
        try JSONSerialization.data(withJSONObject: device).write(to: store.deviceURL)
        try store.configure(server: "https://example.test", token: "", sourceID: "ignored", home: root)
        let saved = try JSONSerialization.jsonObject(with: Data(contentsOf: store.deviceURL)) as! [String: Any]
        XCTAssertEqual(saved["account_fingerprint_sources"] as? [String: String], explicit)
    }

    func testCodexAccountPathRequiresUnambiguousEnabledAuthConfiguration() throws {
        let cases: [(providers: [[String: Any]], expected: String?)] = [
            ([], nil),
            ([["provider": "codex", "auth_file": "/a", "enabled": false]], nil),
            ([["provider": "codex", "rpc": true]], nil),
            ([["provider": "codex", "auth_file": "   "]], nil),
            ([["provider": "claude", "auth_file": "/a"]], nil),
            ([["provider": "codex", "auth_file": "/a"], ["provider": "codex", "auth_file": "/b"]], nil),
            ([["provider": "codex", "auth_file": "/a"], ["provider": "codex", "rpc": true]], nil),
            ([["provider": "codex", "auth_file": "/a"], ["provider": "codex", "auth_file": "/b", "enabled": false]], "/a"),
            ([["provider": "codex", "auth_file": "/a"], ["provider": "codex", "auth_file": "/a"]], "/a")
        ]
        XCTAssertEqual(cases.count, 9)
        for (index, item) in cases.enumerated() {
            let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: root) }
            let store = CollectorSettingsStore(root: root)
            try store.configure(server: "https://example.test", token: "test-device", sourceID: "mac-test", home: root)
            try JSONSerialization.data(withJSONObject: ["providers": item.providers]).write(to: store.limitsURL)
            try store.configure(server: "https://example.test", token: "", sourceID: "mac-test", home: root)
            let device = try JSONSerialization.jsonObject(with: Data(contentsOf: store.deviceURL)) as! [String: Any]
            let sources = device["account_fingerprint_sources"] as? [String: String]
            XCTAssertEqual(sources?["codex"], item.expected, "case \(index)")
            XCTAssertNil(sources?["claude"], "case \(index)")
        }
    }

}
