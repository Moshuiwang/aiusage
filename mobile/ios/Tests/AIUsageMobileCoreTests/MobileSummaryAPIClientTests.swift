import Foundation
import XCTest
@testable import AIUsageMobileCore

final class MobileSummaryAPIClientTests: XCTestCase {
    func testLoadsSummaryWithBearerAuthAndPeriodQuery() async throws {
        let fixtureURL = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        let fixtureData = try Data(contentsOf: fixtureURL)
        let transport = StubTransport(data: fixtureData, statusCode: 200)
        let client = MobileSummaryAPIClient(
            config: MobileSummaryAPIConfig(
                baseURL: try XCTUnwrap(URL(string: "http://127.0.0.1:8776")),
                bearerToken: "secret-token",
                period: "week"
            ),
            transport: transport
        )

        let summary = try await client.load()

        XCTAssertEqual(summary.period.id, "week")
        let request = try XCTUnwrap(transport.request)
        XCTAssertEqual(request.url?.path, "/api/mobile/summary")
        XCTAssertEqual(request.url?.query, "period=week")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer secret-token")
        XCTAssertEqual(request.cachePolicy, .reloadIgnoringLocalCacheData)
    }

    func testHistoricalRequestIncludesOffsetAndCurrentRequestCanBeExplicit() async throws {
        let fixtureURL = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        for offset in [-6, -2, -1, 0] {
            let transport = StubTransport(data: try Data(contentsOf: fixtureURL), statusCode: 200)
            let client = MobileSummaryAPIClient(config: MobileSummaryAPIConfig(
                baseURL: URL(string: "https://example.test")!, bearerToken: nil,
                period: "today", offset: offset), transport: transport)
            _ = try await client.load()
            XCTAssertEqual(transport.request?.url?.query, "period=today&offset=\(offset)")
        }
    }

    func testRejectsNonSuccessHTTPStatus() async throws {
        let transport = StubTransport(data: Data("{}".utf8), statusCode: 401)
        let client = MobileSummaryAPIClient(
            config: MobileSummaryAPIConfig(
                baseURL: try XCTUnwrap(URL(string: "http://127.0.0.1:8776")),
                bearerToken: nil,
                period: "today"
            ),
            transport: transport
        )

        do {
            _ = try await client.load()
            XCTFail("Expected statusCode failure")
        } catch MobileSummaryAPIError.statusCode(let statusCode) {
            XCTAssertEqual(statusCode, 401)
        }
    }
}

private final class StubTransport: MobileSummaryTransport {
    private let data: Data
    private let statusCode: Int
    private(set) var request: URLRequest?

    init(data: Data, statusCode: Int) {
        self.data = data
        self.statusCode = statusCode
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        self.request = request
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: statusCode,
            httpVersion: nil,
            headerFields: nil
        )!
        return (data, response)
    }
}
