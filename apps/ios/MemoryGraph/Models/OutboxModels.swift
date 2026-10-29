import Foundation

// MARK: - Outbox media item（手机沙盒一条待同步图）

enum OutboxItemStatus: String, Codable, CaseIterable {
    case pending
    case syncing
    case synced
    case failed
    case conflict
}

struct OutboxItem: Identifiable, Codable, Equatable {
    var id: String { localId }
    var localId: String
    /// 相对 Outbox 根目录，如 `{localId}/media.jpg`
    var relativeMediaPath: String
    var fileName: String
    var userNote: String
    var status: OutboxItemStatus
    var photoId: String
    var mutationIdIngest: String
    var mutationIdDescribe: String
    var createdAt: String
    var capturedAt: String
    var lastMessage: String
    var contentHash: String

    var needsIngest: Bool {
        photoId.isEmpty && (status == .pending || status == .failed)
    }

    var needsDescribe: Bool {
        !photoId.isEmpty
            && !userNote.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (status == .pending || status == .failed || status == .synced)
            // synced 但旁白可能改过：用 noteDirty 更准；简化：有 note 且未标记 describeDone
            && !describeDone
    }

    /// 旁白已成功推到 Mac
    var describeDone: Bool

    /// 图已回执，且旁白已推（或无旁白）
    var isFullySynced: Bool {
        status == .synced
            && (userNote.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || describeDone)
    }

    init(
        localId: String,
        relativeMediaPath: String,
        fileName: String,
        userNote: String = "",
        status: OutboxItemStatus = .pending,
        photoId: String = "",
        mutationIdIngest: String = UUID().uuidString,
        mutationIdDescribe: String = UUID().uuidString,
        createdAt: String = ISO8601DateFormatter().string(from: Date()),
        capturedAt: String = "",
        lastMessage: String = "",
        contentHash: String = "",
        describeDone: Bool = false
    ) {
        self.localId = localId
        self.relativeMediaPath = relativeMediaPath
        self.fileName = fileName
        self.userNote = userNote
        self.status = status
        self.photoId = photoId
        self.mutationIdIngest = mutationIdIngest
        self.mutationIdDescribe = mutationIdDescribe
        self.createdAt = createdAt
        self.capturedAt = capturedAt
        self.lastMessage = lastMessage
        self.contentHash = contentHash
        self.describeDone = describeDone
    }
}

// MARK: - Story draft

enum StoryDraftStatus: String, Codable {
    case pending
    case syncing
    case synced
    case failed
    case conflict
}

struct StoryDraft: Identifiable, Codable, Equatable {
    var id: String { storyId }
    /// 稳定 id，如 sty_ + uuid
    var storyId: String
    var title: String
    var body: String
    /// 尚未 ingest 回执的本地图；同步时不得写入 Mac links
    var pendingLocalIds: [String]
    /// 已落地 photo_id
    var linkedPhotoIds: [String]
    var status: StoryDraftStatus
    var mutationId: String
    var createdAt: String
    var updatedAt: String
    var lastMessage: String

    static func makeNewStoryId() -> String {
        let hex = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        return "sty_" + String(hex.prefix(16))
    }

    init(
        storyId: String = StoryDraft.makeNewStoryId(),
        title: String = "",
        body: String = "",
        pendingLocalIds: [String] = [],
        linkedPhotoIds: [String] = [],
        status: StoryDraftStatus = .pending,
        mutationId: String = UUID().uuidString,
        createdAt: String = ISO8601DateFormatter().string(from: Date()),
        updatedAt: String = ISO8601DateFormatter().string(from: Date()),
        lastMessage: String = ""
    ) {
        self.storyId = storyId
        self.title = title
        self.body = body
        self.pendingLocalIds = pendingLocalIds
        self.linkedPhotoIds = linkedPhotoIds
        self.status = status
        self.mutationId = mutationId
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.lastMessage = lastMessage
    }
}

// MARK: - Desk receipts

struct IngestReceipt: Decodable {
    let status: String
    let localId: String
    let photoId: String
    let relativePath: String?
    let contentHash: String?
    let mutationId: String?
    let message: String?

    enum CodingKeys: String, CodingKey {
        case status, message
        case localId = "local_id"
        case photoId = "photo_id"
        case relativePath = "relative_path"
        case contentHash = "content_hash"
        case mutationId = "mutation_id"
    }
}

struct DescribeReceipt: Decodable {
    let status: String
    let photoId: String
    let userNote: String?
    let mutationId: String?
    let message: String?

    enum CodingKeys: String, CodingKey {
        case status, message
        case photoId = "photo_id"
        case userNote = "user_note"
        case mutationId = "mutation_id"
    }
}

struct StoryUpsertReceipt: Decodable {
    let status: String
    let storyId: String
    let created: Bool?
    let mutationId: String?
    let message: String?
    let story: StoryPayload?

    enum CodingKeys: String, CodingKey {
        case status, created, message, story
        case storyId = "story_id"
        case mutationId = "mutation_id"
    }
}

struct StoryPayload: Codable {
    var storyId: String?
    var title: String?
    var body: String?
    var links: [StoryLinkPayload]?

    enum CodingKeys: String, CodingKey {
        case title, body, links
        case storyId = "story_id"
    }
}

struct StoryLinkPayload: Codable {
    var linkType: String
    var linkId: String
    var sortOrder: Int

    enum CodingKeys: String, CodingKey {
        case linkType = "link_type"
        case linkId = "link_id"
        case sortOrder = "sort_order"
    }
}

struct StoryUpsertBody: Encodable {
    let storyId: String
    let title: String
    let body: String
    let links: [StoryLinkPayload]
    let mutationId: String
    let deviceId: String

    enum CodingKeys: String, CodingKey {
        case title, body, links
        case storyId = "story_id"
        case mutationId = "mutation_id"
        case deviceId = "device_id"
    }
}

struct MobilePlanPayload: Codable {
    var schedules: [ScheduleItem]
    var diaries: [DiaryEntry]
}

struct MobilePlanReceipt: Decodable {
    let status: String
    let schedules: Int?
    let diaries: Int?
}

struct DescribeBody: Encodable {
    let photoId: String
    let userNote: String
    let mutationId: String
    let deviceId: String

    enum CodingKeys: String, CodingKey {
        case photoId = "photo_id"
        case userNote = "user_note"
        case mutationId = "mutation_id"
        case deviceId = "device_id"
    }
}
