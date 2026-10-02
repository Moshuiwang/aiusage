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

}
