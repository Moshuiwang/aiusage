import Foundation

public struct MobileSummaryAPIConfig: Equatable, Sendable {
    public let baseURL: URL
    public let bearerToken: String?
    public let period: String

    public init(baseURL: URL, bearerToken: String?, period: String) {
        self.baseURL = baseURL
        self.bearerToken = bearerToken
        self.period = period
    }
}

public enum MobileSummaryAPIError: Error, Equatable {
    case invalidURL
    case invalidResponse
    case statusCode(Int)
}

public protocol MobileSummaryTransport {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
}

extension URLSession: MobileSummaryTransport {}

public struct MobileSummaryAPIClient {
    private let config: MobileSummaryAPIConfig
    private let transport: MobileSummaryTransport
    private let decoder: JSONDecoder

    public init(
        config: MobileSummaryAPIConfig,
        transport: MobileSummaryTransport = URLSession.shared,
        decoder: JSONDecoder = JSONDecoder()
    ) {
        self.config = config
        self.transport = transport
        self.decoder = decoder
    }

    public func load() async throws -> MobileSummary {
        let request = try makeRequest()
        let (data, response) = try await transport.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw MobileSummaryAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw MobileSummaryAPIError.statusCode(httpResponse.statusCode)
        }
        return try decoder.decode(MobileSummary.self, from: data)
    }

    private func makeRequest() throws -> URLRequest {
        let endpoint = config.baseURL.appendingPathComponent("api/mobile/summary")
        guard var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false) else {
            throw MobileSummaryAPIError.invalidURL
        }
        components.queryItems = [
            URLQueryItem(name: "period", value: config.period)
        ]
        guard let url = components.url else {
            throw MobileSummaryAPIError.invalidURL
        }

        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let bearerToken = config.bearerToken, !bearerToken.isEmpty {
            request.setValue("Bearer \(bearerToken)", forHTTPHeaderField: "Authorization")
        }
        return request
    }
}
