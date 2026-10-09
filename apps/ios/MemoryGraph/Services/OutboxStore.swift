import Foundation
import UniformTypeIdentifiers

/// 本地 Outbox 真源：Documents/Outbox/ + manifest.json
@MainActor
final class OutboxStore: ObservableObject {
    @Published private(set) var items: [OutboxItem] = []
    @Published private(set) var stories: [StoryDraft] = []
    @Published var isSyncing = false
    @Published var lastSyncMessage: String = ""

    private let fileManager = FileManager.default
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        return e
    }()
    private let decoder = JSONDecoder()

    private var rootURL: URL {
        let docs = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first!
        return docs.appendingPathComponent("Outbox", isDirectory: true)
    }

    private var manifestURL: URL {
        rootURL.appendingPathComponent("manifest.json")
    }

    init() {
        try? fileManager.createDirectory(at: rootURL, withIntermediateDirectories: true)
        load()
    }

    func mediaURL(for item: OutboxItem) -> URL {
        rootURL.appendingPathComponent(item.relativeMediaPath)
    }

    // MARK: - Persist

    private struct Manifest: Codable {
        var items: [OutboxItem]
        var stories: [StoryDraft]
    }

    func load() {
        guard fileManager.fileExists(atPath: manifestURL.path) else {
            items = []
            stories = []
            return
        }
        do {
            let data = try Data(contentsOf: manifestURL)
            let m = try decoder.decode(Manifest.self, from: data)
            items = m.items.sorted { $0.createdAt > $1.createdAt }
            stories = m.stories.sorted { $0.updatedAt > $1.updatedAt }
        } catch {
            lastSyncMessage = "读取 Outbox 失败：\(error.localizedDescription)"
        }
    }

    private func save() {
        try? fileManager.createDirectory(at: rootURL, withIntermediateDirectories: true)
        let m = Manifest(items: items, stories: stories)
        do {
            let data = try encoder.encode(m)
            try data.write(to: manifestURL, options: .atomic)
        } catch {
            lastSyncMessage = "保存 Outbox 失败：\(error.localizedDescription)"
        }
    }

    // MARK: - Media

    /// 从相册 Data 拷贝进沙盒（不删系统相册）。
    @discardableResult
    func addMedia(
        data: Data,
        fileName: String,
        contentType: UTType?,
        capturedAt: String = ""
    ) throws -> OutboxItem {
        let localId = "loc_" + UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(12).lowercased()
        let dir = rootURL.appendingPathComponent(String(localId), isDirectory: true)
        try fileManager.createDirectory(at: dir, withIntermediateDirectories: true)

        let ext = preferredExtension(fileName: fileName, type: contentType)
        let safeName = "media.\(ext)"
        let dest = dir.appendingPathComponent(safeName)
        try data.write(to: dest, options: .atomic)

        let rel = "\(localId)/\(safeName)"
        let item = OutboxItem(
            localId: String(localId),
            relativeMediaPath: rel,
            fileName: fileName.isEmpty ? safeName : fileName,
            capturedAt: capturedAt
        )
        items.insert(item, at: 0)
        save()
        return item
    }

    func updateNote(localId: String, note: String) {
        guard let idx = items.firstIndex(where: { $0.localId == localId }) else { return }
        // 未改字就保存：不要把「已同步」打回 pending（否则误显示待写旁白）
        guard items[idx].userNote != note else { return }
        items[idx].userNote = note
        items[idx].describeDone = false
        if items[idx].status == .synced || !items[idx].photoId.isEmpty {
            items[idx].status = .pending
            items[idx].mutationIdDescribe = UUID().uuidString
        }
        save()
    }

    func removeItem(localId: String) {
        guard let idx = items.firstIndex(where: { $0.localId == localId }) else { return }
        let item = items[idx]
        let dir = rootURL.appendingPathComponent(item.localId, isDirectory: true)
        try? fileManager.removeItem(at: dir)
        items.remove(at: idx)
        // 故事里摘掉 pending 引用
        for i in stories.indices {
            stories[i].pendingLocalIds.removeAll { $0 == localId }
        }
        save()
    }

    func upsertItem(_ item: OutboxItem) {
        if let idx = items.firstIndex(where: { $0.localId == item.localId }) {
            items[idx] = item
        } else {
            items.insert(item, at: 0)
        }
        save()
    }

    // MARK: - Stories

    func upsertStory(_ draft: StoryDraft) {
        var d = draft
        d.updatedAt = ISO8601DateFormatter().string(from: Date())
        if d.status == .synced {
            d.status = .pending
            d.mutationId = UUID().uuidString
        }
        if let idx = stories.firstIndex(where: { $0.storyId == d.storyId }) {
            stories[idx] = d
        } else {
            stories.insert(d, at: 0)
        }
        save()
    }

    func removeStory(storyId: String) {
        stories.removeAll { $0.storyId == storyId }
        save()
    }

    func markStory(_ draft: StoryDraft) {
        if let idx = stories.firstIndex(where: { $0.storyId == draft.storyId }) {
            stories[idx] = draft
            save()
        }
    }

    /// 把已回执的 local→photo 灌进故事 links；未解析的留在 pendingLocalIds。
    func resolveStoryLinks(using itemsSnapshot: [OutboxItem]) {
        let map = Dictionary(uniqueKeysWithValues: itemsSnapshot.compactMap { item -> (String, String)? in
            guard !item.photoId.isEmpty else { return nil }
            return (item.localId, item.photoId)
        })
        for i in stories.indices {
            var pending: [String] = []
            var linked = stories[i].linkedPhotoIds
            var changed = false
            for loc in stories[i].pendingLocalIds {
                if let pid = map[loc] {
                    if !linked.contains(pid) {
                        linked.append(pid)
                        changed = true
                    }
                } else {
                    pending.append(loc)
                }
            }
            if pending.count != stories[i].pendingLocalIds.count {
                changed = true
            }
            stories[i].pendingLocalIds = pending
            stories[i].linkedPhotoIds = linked
            if changed {
                stories[i].status = .pending
                stories[i].mutationId = UUID().uuidString
            }
        }
        save()
    }

    // MARK: - Helpers

    private func preferredExtension(fileName: String, type: UTType?) -> String {
        let fromName = (fileName as NSString).pathExtension.lowercased()
        if !fromName.isEmpty { return fromName }
        if type == .heic || type == UTType("public.heic") { return "heic" }
        if type == .png { return "png" }
        return "jpg"
    }
}
