import Combine
import Foundation

enum DeskAPIError: LocalizedError {
    case notConfigured
    case invalidURL
    case httpStatus(Int, String)
    case decoding(Error)
    case transport(Error)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "还没填家里电脑的地址"
        case .invalidURL:
            return "地址格式不对"
        case .httpStatus(let code, let body):
            if body.isEmpty { return "服务器返回 \(code)" }
            return "服务器返回 \(code)：\(body)"
        case .decoding:
            return "返回数据读不懂"
        case .transport(let err):
            return err.localizedDescription
        }
    }
}

@MainActor
final class DeskAPIClient: ObservableObject {
    @Published private(set) var isReachable: Bool?
    @Published private(set) var lastError: String?

    private let settings: AppSettings
    private let session: URLSession

    init(settings: AppSettings, session: URLSession = .shared) {
        self.settings = settings
        self.session = session
    }

    // MARK: - Connectivity

    func checkHealth() async {
        do {
            // Desk 暂无专用 /api/health，用轻量 years 探测
            _ = try await getYears()
            isReachable = true
            lastError = nil
        } catch {
            isReachable = false
            lastError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    // MARK: - Ask

    func ask(question: String) async throws -> AskResponse {
        let trimmed = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw DeskAPIError.httpStatus(400, "问题不能为空")
        }
        var request = try makeRequest(path: "/api/ask", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(AskRequestBody(question: trimmed))
        return try await send(request)
    }

    // MARK: - People / Photos

    func fetchRegistry() async throws -> [PersonInfo] {
        let response: RegistryResponse = try await send(try makeRequest(path: "/api/face/registry"))
        return response.people
    }

    func fetchPhotos(
        person: String,
        page: Int = 1,
        pageSize: Int = 40,
        peopleCount: Int? = nil
    ) async throws -> MemoryListResponse {
        var items: [URLQueryItem] = [
            URLQueryItem(name: "page", value: String(page)),
            URLQueryItem(name: "page_size", value: String(pageSize)),
            URLQueryItem(name: "sort", value: "desc"),
        ]
        let p = person.trimmingCharacters(in: .whitespacesAndNewlines)
        if !p.isEmpty {
            items.append(URLQueryItem(name: "person", value: p))
        }
        if let peopleCount {
            items.append(URLQueryItem(name: "people_count", value: String(peopleCount)))
        }
        return try await send(try makeRequest(path: "/api/memory/list", query: items))
    }

    /// 默认逛图：某人最近单人照，按天去重（一天一张，不要合照）
    func fetchSoloPortraits(person: String = "面面", limit: Int = 24) async throws -> [PhotoItem] {
        // 多取一些：按天折叠后才能凑够 limit 天
        let response = try await fetchPhotos(
            person: person,
            page: 1,
            pageSize: max(limit * 15, 200),
            peopleCount: 1
        )
        var seenDays = Set<String>()
        var out: [PhotoItem] = []
        for photo in response.items {
            guard !photo.sourcePath.isEmpty, photo.isSoloPortrait else { continue }
            let day = photo.calendarDay
            // 无时间的不进「一天一张」默认墙，避免挤掉有日期的近照
            guard !day.isEmpty else { continue }
            if seenDays.contains(day) { continue }
            seenDays.insert(day)
            out.append(photo)
            if out.count >= limit { break }
        }
        return out
    }

    func getYears() async throws -> [String] {
        let response: YearsResponse = try await send(try makeRequest(path: "/api/memory/years"))
        return response.years ?? []
    }

    func previewURL(sourcePath: String, size: Int = 320) -> URL? {
        guard !sourcePath.isEmpty, let base = settings.baseURL else { return nil }
        var components = URLComponents(
            url: base.appendingPathComponent("api/preview"),
            resolvingAgainstBaseURL: false
        )
        components?.queryItems = [
            URLQueryItem(name: "path", value: sourcePath),
            URLQueryItem(name: "size", value: String(size)),
        ]
        return components?.url
    }

    // MARK: - Internals

    private func makeRequest(
        path: String,
        method: String = "GET",
        query: [URLQueryItem] = []
    ) throws -> URLRequest {
        guard let base = settings.baseURL else { throw DeskAPIError.notConfigured }
        var comps = URLComponents()
        comps.scheme = base.scheme ?? "http"
        comps.host = base.host
        comps.port = base.port
        comps.path = path.hasPrefix("/") ? path : "/" + path
        if !query.isEmpty {
            comps.queryItems = query
        }
        guard let url = comps.url else { throw DeskAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 60
        return request
    }

    private func send<T: Decodable>(_ request: URLRequest) async throws -> T {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw DeskAPIError.transport(error)
        }
        guard let http = response as? HTTPURLResponse else {
            throw DeskAPIError.httpStatus(-1, "无 HTTP 响应")
        }
        guard (200 ..< 300).contains(http.statusCode) else {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw DeskAPIError.httpStatus(http.statusCode, String(body.prefix(200)))
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw DeskAPIError.decoding(error)
        }
    }
}
