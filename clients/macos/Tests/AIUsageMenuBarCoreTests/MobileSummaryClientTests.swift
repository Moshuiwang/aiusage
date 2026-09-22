import Foundation
import XCTest
@testable import AIUsageMenuBarCore

final class MobileSummaryClientTests: XCTestCase {
    func testClientRequestsSelectedPeriodWithBearerToken() async throws {
        let data = try fixtureData()
        let transport = RecordingTransport(data: data, statusCode: 200)
        let client = MobileSummaryClient(
            config: MobileSummaryClientConfig(
                baseURL: try XCTUnwrap(URL(string: "https://aiusage.chunbai.com")),
                bearerToken: "test-token",
                period: "month"
            ),
            transport: transport
        )

        let summary = try await client.load()

        XCTAssertEqual(summary.period.id, "week")
        XCTAssertEqual(
            transport.requests.first?.url?.absoluteString,
            "https://aiusage.chunbai.com/api/mobile/summary?period=month&offset=0"
        )
        XCTAssertEqual(
            transport.requests.first?.value(forHTTPHeaderField: "Authorization"),
            "Bearer test-token"
        )
        XCTAssertEqual(transport.requests.first?.value(forHTTPHeaderField: "Accept"), "application/json")
    }

    func testEveryHistoricalPeriodSendsItsNegativeOffset() async throws {
        for period in ["today", "week", "month"] {
            let transport = RecordingTransport(data: try fixtureData(), statusCode: 200)
            let client = MobileSummaryClient(config: MobileSummaryClientConfig(
                baseURL: try XCTUnwrap(URL(string: "https://example.test")), bearerToken: nil, period: period, offset: -2
            ), transport: transport)
            _ = try await client.load()
            XCTAssertEqual(transport.requests.count, 1)
            XCTAssertEqual(transport.requests.first?.url?.query, "period=\(period)&offset=-2")
        }
    }

    func testClientRejectsUnauthorizedResponse() async throws {
        let transport = RecordingTransport(data: Data("{}".utf8), statusCode: 401)
        let client = MobileSummaryClient(
            config: MobileSummaryClientConfig(
                baseURL: try XCTUnwrap(URL(string: "https://aiusage.chunbai.com")),
                bearerToken: nil,
                period: "today"
            ),
            transport: transport
        )

        do {
            _ = try await client.load()
            XCTFail("Expected unauthorized response to fail")
        } catch MobileSummaryClientError.statusCode(let code) {
            XCTAssertEqual(code, 401)
        }
    }

    func testClientRetriesTransientTransportFailure() async throws {
        let data = try fixtureData()
        let transport = FlakyTransport(
            data: data,
            firstError: URLError(.networkConnectionLost)
        )
        let client = MobileSummaryClient(
            config: MobileSummaryClientConfig(
                baseURL: try XCTUnwrap(URL(string: "https://aiusage.chunbai.com")),
                bearerToken: nil,
                period: "today"
            ),
            transport: transport
        )

        let summary = try await client.load()

        XCTAssertEqual(summary.period.id, "week")
        XCTAssertEqual(transport.requests.count, 2)
    }

    private func fixtureData() throws -> Data {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        return try Data(contentsOf: url)
    }
}

private final class RecordingTransport: MobileSummaryTransport {
    private let data: Data
    private let statusCode: Int
    private(set) var requests: [URLRequest] = []

    init(data: Data, statusCode: Int) {
        self.data = data
        self.statusCode = statusCode
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        requests.append(request)
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: statusCode,
            httpVersion: nil,
            headerFields: nil
        )!
        return (data, response)
    }
}

private final class FlakyTransport: MobileSummaryTransport {
    private let data: Data
    private let firstError: Error
    private(set) var requests: [URLRequest] = []

    init(data: Data, firstError: Error) {
        self.data = data
        self.firstError = firstError
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        requests.append(request)
        if requests.count == 1 {
            throw firstError
        }
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: 200,
            httpVersion: nil,
            headerFields: nil
        )!
        return (data, response)
    }
}
