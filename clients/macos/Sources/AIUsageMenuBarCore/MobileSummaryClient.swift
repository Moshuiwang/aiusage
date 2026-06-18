import Foundation

public struct MobileSummaryClientConfig: Equatable, Sendable {
    public let baseURL: URL
    public let bearerToken: String?
    public let period: String

    public init(baseURL: URL, bearerToken: String?, period: String) {
        self.baseURL = baseURL
        self.bearerToken = bearerToken
        self.period = period
    }
}

public enum MobileSummaryClientError: Error, Equatable {
    case invalidURL
    case invalidResponse
    case statusCode(Int)
}

public protocol MobileSummaryTransport {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
}

extension URLSession: MobileSummaryTransport {}

public struct MobileSummaryClient {
    private let config: MobileSummaryClientConfig
    private let transport: MobileSummaryTransport
    private let decoder: JSONDecoder
    private let retryAttempts: Int

    public init(
        config: MobileSummaryClientConfig,
        transport: MobileSummaryTransport = URLSession.shared,
        decoder: JSONDecoder = JSONDecoder(),
        retryAttempts: Int = 3
    ) {
        self.config = config
        self.transport = transport
        self.decoder = decoder
        self.retryAttempts = max(1, retryAttempts)
    }

    public func load() async throws -> MobileSummary {
        var lastURLError: URLError?
        for _ in 0..<retryAttempts {
            do {
                return try await loadOnce()
            } catch let error as URLError {
                lastURLError = error
            }
        }
        if let lastURLError {
            throw lastURLError
        }
        throw MobileSummaryClientError.invalidResponse
    }

    private func loadOnce() async throws -> MobileSummary {
        let request = try makeRequest()
        let (data, response) = try await transport.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw MobileSummaryClientError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw MobileSummaryClientError.statusCode(httpResponse.statusCode)
        }
        return try decoder.decode(MobileSummary.self, from: data)
    }

    private func makeRequest() throws -> URLRequest {
        let endpoint = config.baseURL.appendingPathComponent("api/mobile/summary")
        guard var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false) else {
            throw MobileSummaryClientError.invalidURL
        }
        components.queryItems = [URLQueryItem(name: "period", value: config.period)]
        guard let url = components.url else {
            throw MobileSummaryClientError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token = config.bearerToken, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }
}
