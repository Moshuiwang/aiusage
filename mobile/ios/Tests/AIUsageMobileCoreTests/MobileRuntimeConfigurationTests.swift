import Foundation
import XCTest
@testable import AIUsageMobileCore

final class MobileRuntimeConfigurationTests: XCTestCase {
    func testSavesServerURLAndTokenWithoutPlainUserDefaultsToken() throws {
        let defaults = try makeIsolatedDefaults()
        let tokenStore = InMemoryTokenStore()

        let config = try MobileSummaryRuntimeConfig.saveSettings(
            baseURLString: " https://vpn2.chunbai.com:8443 ",
            token: " secret-token ",
            period: "week",
            defaults: defaults,
            tokenStore: tokenStore
        )

        XCTAssertEqual(config.baseURL.absoluteString, "https://vpn2.chunbai.com:8443")
        XCTAssertEqual(config.bearerToken, "secret-token")
        XCTAssertEqual(defaults.string(forKey: "AIUsageAPIBaseURL"), "https://vpn2.chunbai.com:8443")
        XCTAssertNil(defaults.string(forKey: "AIUsageAPIToken"))
        XCTAssertEqual(tokenStore.savedToken, "secret-token")
    }

    func testLoadsSavedSettingsFromDefaultsAndTokenStore() throws {
        let defaults = try makeIsolatedDefaults()
        defaults.set("https://vpn2.chunbai.com:8443", forKey: "AIUsageAPIBaseURL")
        let tokenStore = InMemoryTokenStore(savedToken: "stored-token")

        let config = try XCTUnwrap(MobileSummaryRuntimeConfig.makeAPIConfig(
            period: "today",
            environment: [:],
            defaults: defaults,
            tokenStore: tokenStore
        ))

        XCTAssertEqual(config.baseURL.absoluteString, "https://vpn2.chunbai.com:8443")
        XCTAssertEqual(config.bearerToken, "stored-token")
        XCTAssertEqual(config.period, "today")
    }

    func testDoesNotReadPlainUserDefaultsToken() throws {
        let defaults = try makeIsolatedDefaults()
        defaults.set("https://vpn2.chunbai.com:8443", forKey: "AIUsageAPIBaseURL")
        defaults.set("plain-defaults-token", forKey: "AIUsageAPIToken")

        XCTAssertNil(MobileSummaryRuntimeConfig.makeAPIConfig(
            period: "week",
            environment: [:],
            defaults: defaults,
            tokenStore: InMemoryTokenStore()
        ))
    }

    func testRejectsSaveWithoutToken() throws {
        let defaults = try makeIsolatedDefaults()
        let tokenStore = InMemoryTokenStore()

        XCTAssertThrowsError(try MobileSummaryRuntimeConfig.saveSettings(
            baseURLString: "https://vpn2.chunbai.com:8443",
            token: " ",
            period: "week",
            defaults: defaults,
            tokenStore: tokenStore
        )) { error in
            XCTAssertEqual(error as? MobileRuntimeConfigurationError, .missingToken)
        }
        XCTAssertNil(defaults.string(forKey: "AIUsageAPIBaseURL"))
        XCTAssertNil(tokenStore.savedToken)
    }

    func testTokenStoreFailureDoesNotPartiallySaveServerURLOrClearLegacyToken() throws {
        let defaults = try makeIsolatedDefaults()
        defaults.set("https://vpn2.chunbai.com:8443", forKey: "AIUsageAPIBaseURL")
        defaults.set("legacy-token", forKey: "AIUsageAPIToken")
        let tokenStore = FailingTokenStore()

        XCTAssertThrowsError(try MobileSummaryRuntimeConfig.saveSettings(
            baseURLString: "https://vpn2.chunbai.com:8443/new-path",
            token: "new-token",
            period: "week",
            defaults: defaults,
            tokenStore: tokenStore
        ))

        XCTAssertEqual(defaults.string(forKey: "AIUsageAPIBaseURL"), "https://vpn2.chunbai.com:8443")
        XCTAssertEqual(defaults.string(forKey: "AIUsageAPIToken"), "legacy-token")
    }

    func testRejectsNonProductionServerUnlessDevelopmentOverrideIsExplicit() throws {
        let defaults = try makeIsolatedDefaults()
        defaults.set("http://127.0.0.1:8765", forKey: "AIUsageAPIBaseURL")
        let tokenStore = InMemoryTokenStore(savedToken: "local-token")

        XCTAssertNil(MobileSummaryRuntimeConfig.makeAPIConfig(
            period: "week",
            environment: [:],
            defaults: defaults,
            tokenStore: tokenStore
        ))

        let config = try XCTUnwrap(MobileSummaryRuntimeConfig.makeAPIConfig(
            period: "week",
            environment: ["AI_USAGE_ALLOW_NON_PROD_SERVER": "1"],
            defaults: defaults,
            tokenStore: tokenStore
        ))
        XCTAssertEqual(config.baseURL.absoluteString, "http://127.0.0.1:8765")
    }

    func testAcceptsExplicitSelfHostedHTTPSDomain() throws {
        let defaults = try makeIsolatedDefaults()
        let tokenStore = InMemoryTokenStore()

        let saved = try MobileSummaryRuntimeConfig.saveSettings(
            baseURLString: "https://usage.example.com",
            token: "self-host-token",
            period: "week",
            defaults: defaults,
            tokenStore: tokenStore
        )

        XCTAssertEqual(saved.baseURL.absoluteString, "https://usage.example.com")
        XCTAssertEqual(defaults.string(forKey: "AIUsageAPIBaseURL"), "https://usage.example.com")
        let loaded = try XCTUnwrap(MobileSummaryRuntimeConfig.makeAPIConfig(
            period: "week",
            environment: [:],
            defaults: defaults,
            tokenStore: tokenStore
        ))
        XCTAssertEqual(loaded.baseURL.absoluteString, "https://usage.example.com")
    }

    func testRejectsUnsafeSelfHostedServerURLs() throws {
        let rejectedURLs = [
            "http://usage.example.com",
            "http://localhost:8765",
            "https://localhost:8765",
            "http://127.0.0.1:8765",
            "https://127.0.0.1:8765",
            "https://192.168.1.10:8765",
            "https://192.168.001.010:8765",
            "https://10.0.0.2:8765",
            "https://172.16.0.2:8765",
            "https://1.2.3.4:8765",
            "https://01.02.03.04:8765",
            "https://999.999.999.999:8765"
        ]

        for url in rejectedURLs {
            let defaults = try makeIsolatedDefaults()
            let tokenStore = InMemoryTokenStore()
            XCTAssertThrowsError(try MobileSummaryRuntimeConfig.saveSettings(
                baseURLString: url,
                token: "token",
                period: "week",
                defaults: defaults,
                tokenStore: tokenStore
            ), url) { error in
                XCTAssertEqual(error as? MobileRuntimeConfigurationError, .nonProductionServer)
            }
            XCTAssertNil(defaults.string(forKey: "AIUsageAPIBaseURL"))
            XCTAssertNil(tokenStore.savedToken)
        }
    }

    func testRejectsUnsafeSavedRuntimeServerURLs() throws {
        let rejectedURLs = [
            "https://192.168.001.010:8765",
            "https://01.02.03.04:8765"
        ]

        for url in rejectedURLs {
            let defaults = try makeIsolatedDefaults()
            defaults.set(url, forKey: "AIUsageAPIBaseURL")
            let tokenStore = InMemoryTokenStore(savedToken: "token")

            XCTAssertNil(MobileSummaryRuntimeConfig.makeAPIConfig(
                period: "week",
                environment: [:],
                defaults: defaults,
                tokenStore: tokenStore
            ), url)
        }
    }

    private func makeIsolatedDefaults() throws -> UserDefaults {
        let suiteName = "MobileRuntimeConfigurationTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defaults.removePersistentDomain(forName: suiteName)
        return defaults
    }
}

private final class InMemoryTokenStore: MobileTokenStore {
    var savedToken: String?

    init(savedToken: String? = nil) {
        self.savedToken = savedToken
    }

    func readToken() -> String? {
        savedToken
    }

    func saveToken(_ token: String?) throws {
        savedToken = token
    }
}

private final class FailingTokenStore: MobileTokenStore {
    func readToken() -> String? {
        nil
    }

    func saveToken(_ token: String?) throws {
        throw NSError(domain: "FailingTokenStore", code: 1)
    }
}
