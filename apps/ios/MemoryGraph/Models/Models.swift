import Foundation

// MARK: - Ask

struct AskRequestBody: Encodable {
    let question: String
    let context: AskTurnContext?

    init(question: String, context: AskTurnContext? = nil) {
        self.question = question
        self.context = context
    }

    enum CodingKeys: String, CodingKey {
        case question, context
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(question, forKey: .question)
        if let context {
            try c.encode(context, forKey: .context)
        }
    }
}

struct AskResponse: Decodable {
    let intent: String?
    let answer: String
    let usedLlm: Bool?
    let facts: AskFacts
    let evidence: AskEvidence?
    let followUps: [String]?
    let context: AskTurnContext?

    enum CodingKeys: String, CodingKey {
        case intent, answer, facts, evidence, context
        case usedLlm = "used_llm"
        case followUps = "follow_ups"
    }
}

/// 统一证据合同：media / events / stories → 可追溯 JSON / 原片。
struct AskEvidence: Decodable {
    let media: [EvidenceMediaItem]?
    let events: [EvidenceEventItem]?
    let stories: [EvidenceStoryItem]?
    let counts: AskEvidenceCounts?

    struct EvidenceMediaItem: Decodable {
        let id: String?
        let mediaType: String?
        let timestamp: String?
        let location: String?
        let scene: String?
        let sourcePath: String?

        enum CodingKeys: String, CodingKey {
            case id, timestamp, location, scene
            case mediaType = "media_type"
            case sourcePath = "source_path"
        }

        var asPhotoItem: PhotoItem? {
            guard let id, !id.isEmpty else { return nil }
            return PhotoItem(
                photoId: id,
                timestamp: timestamp ?? "",
                location: location ?? "",
                scene: scene ?? "",
                sourcePath: sourcePath ?? "",
                people: "",
                mediaType: mediaType ?? "photo"
            )
        }
    }

    struct EvidenceEventItem: Decodable {
        let id: String?
        let day: String?
        let location: String?
        let photoCount: Int?

        enum CodingKeys: String, CodingKey {
            case id, day, location
            case photoCount = "photo_count"
        }
    }

    struct EvidenceStoryItem: Decodable {
        let id: String?
        let title: String?
    }

    struct AskEvidenceCounts: Decodable {
        let media: Int?
        let events: Int?
        let stories: Int?
        let byMediaType: [String: Int]?

        enum CodingKeys: String, CodingKey {
            case media, events, stories
            case byMediaType = "by_media_type"
        }
    }
}

/// 上一轮问答上下文（轻量追问）；字段随服务端扩展，未知键忽略。
struct AskTurnContext: Codable, Hashable {
    var lastIntent: String?
    var intent: String?
    var person: String?
    var periodLabel: String?
    var dayFrom: String?
    var dayTo: String?
    var year: String?
    var season: String?
    var holiday: String?
    var lastAnswer: String?
    var lastParams: [String: AskJSONValue]?
    var basisSummary: [String: AskJSONValue]?

    enum CodingKeys: String, CodingKey {
        case person, intent, year, season, holiday
        case lastIntent = "last_intent"
        case periodLabel = "period_label"
        case dayFrom = "day_from"
        case dayTo = "day_to"
        case lastAnswer = "last_answer"
        case lastParams = "last_params"
        case basisSummary = "basis_summary"
    }
}

/// 宽松 JSON 值，便于透传 context 字典。
enum AskJSONValue: Codable, Hashable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: AskJSONValue])
    case array([AskJSONValue])
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .null
        } else if let v = try? c.decode(Bool.self) {
            self = .bool(v)
        } else if let v = try? c.decode(Double.self) {
            self = .number(v)
        } else if let v = try? c.decode(String.self) {
            self = .string(v)
        } else if let v = try? c.decode([String: AskJSONValue].self) {
            self = .object(v)
        } else if let v = try? c.decode([AskJSONValue].self) {
            self = .array(v)
        } else {
            self = .null
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
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

    /// 与 Vue MemoryAsk 证据区对齐：优先 evidence.media，否则拼 facts
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

    /// 合并顶层 evidence（若有）与 facts 证据。
    func mergedEvidencePhotos(from evidence: AskEvidence?) -> [PhotoItem] {
        if let media = evidence?.media, !media.isEmpty {
            var seen = Set<String>()
            var out: [PhotoItem] = []
            for m in media {
                guard let item = m.asPhotoItem, !seen.contains(item.photoId) else { continue }
                seen.insert(item.photoId)
                out.append(item)
            }
            if !out.isEmpty { return out }
        }
        return evidencePhotos
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
            people: "",
            mediaType: "photo"
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
    let mediaType: String

    enum CodingKeys: String, CodingKey {
        case timestamp, location, scene, people
        case photoId = "photo_id"
        case sourcePath = "source_path"
        case mediaType = "media_type"
    }

    init(
        photoId: String,
        timestamp: String = "",
        location: String = "",
        scene: String = "",
        sourcePath: String = "",
        people: String = "",
        mediaType: String = "photo"
    ) {
        self.photoId = photoId
        self.timestamp = timestamp
        self.location = location
        self.scene = scene
        self.sourcePath = sourcePath
        self.people = people
        self.mediaType = mediaType
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        photoId = try c.decodeIfPresent(String.self, forKey: .photoId) ?? ""
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp) ?? ""
        location = try c.decodeIfPresent(String.self, forKey: .location) ?? ""
        scene = try c.decodeIfPresent(String.self, forKey: .scene) ?? ""
        sourcePath = try c.decodeIfPresent(String.self, forKey: .sourcePath) ?? ""
        mediaType = try c.decodeIfPresent(String.self, forKey: .mediaType) ?? "photo"
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
