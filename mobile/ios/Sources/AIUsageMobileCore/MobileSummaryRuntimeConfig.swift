import Foundation

public protocol MobileTokenStore {
    func readToken() -> String?
    func saveToken(_ token: String?) throws
}

public struct MobileRuntimeSettingsForm: Equatable {
    public let baseURLString: String
    public let token: String

    public init(baseURLString: String, token: String) {
        self.baseURLString = baseURLString
        self.token = token
    }
}

public enum MobileRuntimeConfigurationError: Error, Equatable {
    case invalidBaseURL
    case missingToken
    case nonProductionServer
}

public enum MobileSummaryRuntimeConfig {
    public static let productionBaseURLString = "https://aiusage.chunbai.com"

    public static func initialPeriod(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        defaults: UserDefaults = .standard
    ) -> String {
        environment["AI_USAGE_PERIOD"] ?? defaults.string(forKey: "AIUsagePeriod") ?? "week"
    }

    public static func settingsForm(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        defaults: UserDefaults = .standard,
        bundle: Bundle = .main,
        tokenStore: MobileTokenStore?
    ) -> MobileRuntimeSettingsForm {
        let baseURLString = runtimeBaseURLString(environment: environment, defaults: defaults, bundle: bundle)
            ?? productionBaseURLString
        let baseURL = normalizedURL(baseURLString)
        return MobileRuntimeSettingsForm(
            baseURLString: baseURLString,
            token: runtimeToken(
                tokenStore: tokenStore,
                bundle: bundle,
                prefersBundleToken: baseURL.map(isProductionServer) ?? false
            ) ?? ""
        )
    }

    public static func makeAPIConfig(
        period: String,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        defaults: UserDefaults = .standard,
        bundle: Bundle = .main,
        tokenStore: MobileTokenStore?
    ) -> MobileSummaryAPIConfig? {
        let rawBaseURL = runtimeBaseURLString(environment: environment, defaults: defaults, bundle: bundle)
        guard let rawBaseURL,
              let baseURL = normalizedURL(rawBaseURL)
        else {
            return nil
        }
        guard isTrustedServer(baseURL) || environment["AI_USAGE_ALLOW_NON_PROD_SERVER"] == "1" else {
            return nil
        }

        guard let token = runtimeToken(
            tokenStore: tokenStore,
            bundle: bundle,
            prefersBundleToken: isProductionServer(baseURL)
        ) else {
            return nil
        }

        return MobileSummaryAPIConfig(
            baseURL: baseURL,
            bearerToken: token,
            period: period
        )
    }

    public static func saveSettings(
        baseURLString: String,
        token: String?,
        period: String,
        defaults: UserDefaults = .standard,
        tokenStore: MobileTokenStore,
        allowNonProduction: Bool = false
    ) throws -> MobileSummaryAPIConfig {
        guard let baseURL = normalizedURL(baseURLString) else {
            throw MobileRuntimeConfigurationError.invalidBaseURL
        }
        guard allowNonProduction || isTrustedServer(baseURL) else {
            throw MobileRuntimeConfigurationError.nonProductionServer
        }

        guard let normalizedToken = normalizedRuntimeValue(token) else {
            throw MobileRuntimeConfigurationError.missingToken
        }
        try tokenStore.saveToken(normalizedToken)
        defaults.set(baseURL.absoluteString, forKey: "AIUsageAPIBaseURL")
        defaults.removeObject(forKey: "AIUsageAPIToken")

        return MobileSummaryAPIConfig(
            baseURL: baseURL,
            bearerToken: normalizedToken,
            period: period
        )
    }

    public static func isProductionServer(_ url: URL) -> Bool {
        url.scheme == "https"
            && url.host?.lowercased() == "aiusage.chunbai.com"
            && url.port == nil
    }

    public static func isTrustedServer(_ url: URL) -> Bool {
        isProductionServer(url) || isSelfHostedHTTPSDomain(url)
    }

    private static func isSelfHostedHTTPSDomain(_ url: URL) -> Bool {
        guard url.scheme == "https",
              let host = url.host?.lowercased(),
              host.contains("."),
              !isLocalhost(host),
              !isIPAddress(host)
        else {
            return false
        }
        return true
    }

    private static func isLocalhost(_ host: String) -> Bool {
        host == "localhost" || host.hasSuffix(".localhost") || host.hasSuffix(".local")
    }

    private static func isIPAddress(_ host: String) -> Bool {
        let parts = host.split(separator: ".")
        guard parts.count == 4 else {
            return false
        }
        return parts.allSatisfy { part in
            !part.isEmpty && part.unicodeScalars.allSatisfy { scalar in
                (48...57).contains(scalar.value)
            }
        }
    }

    private static func runtimeToken(
        tokenStore: MobileTokenStore?,
        bundle: Bundle,
        prefersBundleToken: Bool
    ) -> String? {
        let bundleToken = normalizedRuntimeValue(bundle.object(forInfoDictionaryKey: "AIUsageAPIToken") as? String)
        if prefersBundleToken, let bundleToken {
            return bundleToken
        }
        if let token = normalizedRuntimeValue(tokenStore?.readToken()) {
            return token
        }
        guard prefersBundleToken else {
            return nil
        }
        return bundleToken
    }

    private static func runtimeBaseURLString(
        environment: [String: String],
        defaults: UserDefaults,
        bundle: Bundle
    ) -> String? {
        if let environmentBaseURL = normalizedRuntimeValue(environment["AI_USAGE_API_BASE_URL"]) {
            return environmentBaseURL
        }
        if let bundleBaseURL = normalizedRuntimeValue(bundle.object(forInfoDictionaryKey: "AIUsageAPIBaseURL") as? String),
           normalizedURL(bundleBaseURL).map(isProductionServer) == true {
            return bundleBaseURL
        }
        return runtimeValue(
            environmentKey: "AI_USAGE_API_BASE_URL",
            defaultsKey: "AIUsageAPIBaseURL",
            bundleKey: "AIUsageAPIBaseURL",
            fallback: productionBaseURLString,
            environment: environment,
            defaults: defaults,
            bundle: bundle
        )
    }

    private static func runtimeValue(
        environmentKey: String,
        defaultsKey: String,
        bundleKey: String,
        fallback: String?,
        environment: [String: String],
        defaults: UserDefaults,
        bundle: Bundle
    ) -> String? {
        for candidate in [
            environment[environmentKey],
            defaults.string(forKey: defaultsKey),
            bundle.object(forInfoDictionaryKey: bundleKey) as? String,
            fallback
        ] {
            if let value = normalizedRuntimeValue(candidate) {
                return value
            }
        }
        return nil
    }

    private static func normalizedURL(_ value: String) -> URL? {
        guard let normalized = normalizedRuntimeValue(value),
              let url = URL(string: normalized),
              url.scheme != nil,
              url.host != nil
        else {
            return nil
        }
        return url
    }

    private static func normalizedRuntimeValue(_ value: String?) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty || trimmed.hasPrefix("$(") {
            return nil
        }
        return trimmed
    }
}
