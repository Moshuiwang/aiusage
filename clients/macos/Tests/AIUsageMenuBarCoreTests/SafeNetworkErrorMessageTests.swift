import Foundation
import XCTest
@testable import AIUsageMenuBarCore

final class SafeNetworkErrorMessageTests: XCTestCase {
    func testTLSErrorNeverDisplaysSystemStackOrRequestDetails() {
        let error = NSError(domain: NSURLErrorDomain, code: URLError.secureConnectionFailed.rawValue,
            userInfo: [NSLocalizedDescriptionKey: "TLS secret-detail UserInfo={utun4 token=private}"])
        let message = SafeNetworkErrorMessage.message(error)
        XCTAssertEqual(message, "安全连接失败，请检查网络或代理设置")
        XCTAssertFalse(message.contains("secret-detail"))
        XCTAssertFalse(message.contains("UserInfo"))
    }
    func testOfflineTimeoutAndUnknownErrorsAreShortAndSafe() {
        XCTAssertEqual(SafeNetworkErrorMessage.message(URLError(.notConnectedToInternet)), "网络暂时不可用，请稍后重试")
        XCTAssertEqual(SafeNetworkErrorMessage.message(URLError(.timedOut)), "连接超时，请稍后重试")
        XCTAssertEqual(SafeNetworkErrorMessage.message(NSError(domain: "private-domain", code: 42,
            userInfo: [NSLocalizedDescriptionKey: "private diagnostic"])), "暂时无法刷新，请稍后重试")
    }
}
