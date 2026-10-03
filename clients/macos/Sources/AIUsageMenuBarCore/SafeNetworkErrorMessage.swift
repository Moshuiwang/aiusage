import Foundation

/// UI messages are selected from a fixed vocabulary, never from system diagnostics.
public enum SafeNetworkErrorMessage {
    public static func message(_ error: Error) -> String {
        let systemError = error as NSError
        guard systemError.domain == NSURLErrorDomain else { return "暂时无法刷新，请稍后重试" }
        switch URLError.Code(rawValue: systemError.code) {
        case .secureConnectionFailed, .serverCertificateHasBadDate, .serverCertificateUntrusted,
             .serverCertificateHasUnknownRoot, .serverCertificateNotYetValid, .clientCertificateRejected,
             .clientCertificateRequired:
            return "安全连接失败，请检查网络或代理设置"
        case .notConnectedToInternet, .networkConnectionLost, .cannotFindHost, .cannotConnectToHost, .dnsLookupFailed:
            return "网络暂时不可用，请稍后重试"
        case .timedOut:
            return "连接超时，请稍后重试"
        default:
            return "暂时无法刷新，请稍后重试"
        }
    }
}
