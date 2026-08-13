import Foundation

// MARK: - Ask

struct AskRequestBody: Encodable {
    let question: String
}

struct AskResponse: Decodable {
    let intent: String?
    let answer: String
    let usedLlm: Bool?
    let facts: AskFacts

    enum CodingKeys: String, CodingKey {
        case intent, answer, facts
        case usedLlm = "used_llm"
    }
}

/// facts 结构随意图变化；只解码客户端需要的证据字段。
struct AskFacts: Decodable {
    let photos: [PhotoItem]?
    let samplePhotos: [PhotoItem]?
    let photo: PhotoItem?
    let firstVisit: PhotoItem?
    let lastVisit: PhotoItem?
    let places: [PlaceItem]?

    enum CodingKeys: String, CodingKey {
        case photos, photo, places
        case samplePhotos = "sample_photos"
        case firstVisit = "first_visit"
        case lastVisit = "last_visit"
    }

    /// 与 Vue MemoryAsk 证据区对齐：photos / sample_photos / 单张 / 带 photo_id 的 places
    var evidencePhotos: [PhotoItem] {
        var seen = Set<String>()
        var out: [PhotoItem] = []

        func push(_ item: PhotoItem?) {
            guard let item, !item.photoId.isEmpty, !seen.contains(item.photoId) else { return }
            seen.insert(item.photoId)
            out.append(item)
        }

        photos?.forEach { push($0) }
        samplePhotos?.forEach { push($0) }
        push(photo)
        push(firstVisit)
        push(lastVisit)
        places?.forEach { push($0.asPhotoItem) }
        return out
    }
}

struct PlaceItem: Decodable {
    let photoId: String?
    let timestamp: String?
    let location: String?
    let scene: String?
    let sourcePath: String?

    enum CodingKeys: String, CodingKey {
        case timestamp, location, scene
        case photoId = "photo_id"
        case sourcePath = "source_path"
    }

    var asPhotoItem: PhotoItem? {
        guard let photoId, !photoId.isEmpty else { return nil }
        return PhotoItem(
            photoId: photoId,
            timestamp: timestamp ?? "",
            location: location ?? "",
            scene: scene ?? "",
            sourcePath: sourcePath ?? "",
            people: ""
        )
    }
}

// MARK: - Photos / People

struct PhotoItem: Decodable, Identifiable, Hashable {
    var id: String { photoId }

    let photoId: String
    let timestamp: String
    let location: String
    let scene: String
    let sourcePath: String
    let people: String

    enum CodingKeys: String, CodingKey {
        case timestamp, location, scene, people
        case photoId = "photo_id"
        case sourcePath = "source_path"
    }

    init(
        photoId: String,
        timestamp: String = "",
        location: String = "",
        scene: String = "",
        sourcePath: String = "",
        people: String = ""
    ) {
        self.photoId = photoId
        self.timestamp = timestamp
        self.location = location
        self.scene = scene
        self.sourcePath = sourcePath
        self.people = people
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        photoId = try c.decodeIfPresent(String.self, forKey: .photoId) ?? ""
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp) ?? ""
        location = try c.decodeIfPresent(String.self, forKey: .location) ?? ""
        scene = try c.decodeIfPresent(String.self, forKey: .scene) ?? ""
        sourcePath = try c.decodeIfPresent(String.self, forKey: .sourcePath) ?? ""
        // list API 可能返回字符串或其它形态；宽松处理
        if let s = try? c.decode(String.self, forKey: .people) {
            people = s
        } else {
            people = ""
        }
    }

    var subtitle: String {
        let loc = location.trimmingCharacters(in: .whitespacesAndNewlines)
        if !loc.isEmpty { return loc }
        let sc = scene.trimmingCharacters(in: .whitespacesAndNewlines)
        if !sc.isEmpty { return sc }
        return photoId
    }

    var shortTime: String {
        let t = timestamp.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.count >= 10 else { return t }
        return String(t.prefix(10))
    }

    /// YYYY-MM-DD；无有效时间则为空
    var calendarDay: String {
        let t = timestamp.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.count >= 10 else { return "" }
        let day = String(t.prefix(10))
        // 粗校验：2026-05-16
        guard day.count == 10, day[day.index(day.startIndex, offsetBy: 4)] == "-",
              day[day.index(day.startIndex, offsetBy: 7)] == "-" else { return "" }
        return day
    }

    /// people 字段拆出的人名（逗号 / 顿号）
    var peopleNames: [String] {
        people
            .split { $0 == "," || $0 == "，" || $0 == "、" || $0 == "/" }
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    /// 索引里只标了一个人（用于单人像兜底过滤）
    var isSoloPortrait: Bool {
        peopleNames.count <= 1
    }
}

struct MemoryListResponse: Decodable {
    let total: Int
    let page: Int
    let pageSize: Int
    let items: [PhotoItem]

    enum CodingKeys: String, CodingKey {
        case total, page, items
        case pageSize = "page_size"
    }
}

struct RegistryResponse: Decodable {
    let people: [PersonInfo]
}

struct PersonInfo: Decodable, Identifiable, Hashable {
    var id: String { personId }

    let personId: String
    let name: String
    let role: String?
    let birthDate: String?
    let photoCount: Int?

    enum CodingKeys: String, CodingKey {
        case name, role
        case personId = "person_id"
        case birthDate = "birth_date"
        case photoCount = "photo_count"
    }

    var displayName: String {
        let n = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return n.isEmpty ? personId : n
    }

    var countLabel: String {
        let n = photoCount ?? 0
        return "\(n) 张"
    }
}

struct YearsResponse: Decodable {
    let years: [String]?
}
