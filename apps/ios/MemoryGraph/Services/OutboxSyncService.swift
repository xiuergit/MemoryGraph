import Foundation
import UIKit

/// 回家同步：ingest → describe → story.upsert（links 仅已落地 photo_id）。
@MainActor
final class OutboxSyncService: ObservableObject {
    private let store: OutboxStore
    private let api: DeskAPIClient
    private let settings: AppSettings

    init(store: OutboxStore, api: DeskAPIClient, settings: AppSettings) {
        self.store = store
        self.api = api
        self.settings = settings
    }

    var deviceId: String {
        UIDevice.current.userInterfaceIdiom == .pad ? "ipad" : "iphone"
    }

    func syncAll() async {
        guard !store.isSyncing else { return }
        store.isSyncing = true
        store.lastSyncMessage = "同步中…"
        defer { store.isSyncing = false }

        await api.checkHealth()
        guard api.isReachable == true else {
            store.lastSyncMessage = "连不上 Mac Desk，请检查设置里的地址"
            return
        }

        var ok = 0
        var fail = 0

        // 1) media: ingest then describe
        for item in store.items where item.status != .conflict {
            do {
                try await syncMedia(item)
                ok += 1
            } catch {
                fail += 1
                // 用库里最新条目（可能已有 photoId），避免 ingest 成功、describe 失败后丢回执
                var failed = store.items.first(where: { $0.localId == item.localId }) ?? item
                failed.status = .failed
                failed.lastMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                store.upsertItem(failed)
            }
        }

        store.resolveStoryLinks(using: store.items)

        // 2) stories（仅 pending/failed；resolve 后新挂图会回到 pending）
        for draft in store.stories where draft.status == .pending || draft.status == .failed {
            let title = draft.title.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !title.isEmpty else { continue }
            do {
                try await syncStory(draft)
                ok += 1
            } catch {
                fail += 1
                var failed = draft
                failed.status = .failed
                failed.lastMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                store.markStory(failed)
            }
        }

        if fail == 0 {
            store.lastSyncMessage = ok == 0 ? "没有待同步项" : "同步完成（\(ok)）"
        } else {
            store.lastSyncMessage = "完成 \(ok)，失败 \(fail)"
        }
    }

    private func syncMedia(_ item: OutboxItem) async throws {
        var current = item
        let note = current.userNote.trimmingCharacters(in: .whitespacesAndNewlines)

        // 已有 photo_id 且旁白已推（或无旁白）→ 跳过
        if !current.photoId.isEmpty, note.isEmpty || current.describeDone {
            if current.status != .synced {
                current.status = .synced
                if current.lastMessage.isEmpty { current.lastMessage = "已同步" }
                store.upsertItem(current)
            }
            return
        }

        current.status = .syncing
        current.lastMessage = "上传中…"
        store.upsertItem(current)

        let fileURL = store.mediaURL(for: current)
        guard FileManager.default.fileExists(atPath: fileURL.path) else {
            throw DeskAPIError.httpStatus(400, "本地文件不存在")
        }

        if current.photoId.isEmpty {
            let receipt = try await api.ingestMedia(
                fileURL: fileURL,
                localId: current.localId,
                mutationId: current.mutationIdIngest,
                deviceId: deviceId,
                capturedAt: current.capturedAt
            )
            let st = receipt.status.lowercased()
            if st == "conflict" {
                current.status = .conflict
                current.lastMessage = receipt.message ?? "冲突"
                current.photoId = receipt.photoId
                store.upsertItem(current)
                return
            }
            guard st == "accepted" || st == "duplicate" else {
                throw DeskAPIError.httpStatus(400, receipt.message ?? receipt.status)
            }
            current.photoId = receipt.photoId
            current.contentHash = receipt.contentHash ?? ""
            current.lastMessage = receipt.message ?? st
            // 先落回执，describe 失败也能保留 photo_id
            store.upsertItem(current)
        }

        if !note.isEmpty, !current.describeDone {
            current.lastMessage = "写旁白…"
            store.upsertItem(current)
            let d = try await api.describeMedia(
                photoId: current.photoId,
                userNote: note,
                mutationId: current.mutationIdDescribe,
                deviceId: deviceId
            )
            let st = d.status.lowercased()
            if st == "conflict" {
                current.status = .conflict
                current.lastMessage = d.message ?? "旁白冲突"
                store.upsertItem(current)
                return
            }
            guard st == "accepted" else {
                throw DeskAPIError.httpStatus(400, d.message ?? d.status)
            }
            current.describeDone = true
            current.lastMessage = d.message ?? "旁白已写"
        }

        current.status = .synced
        if current.lastMessage.isEmpty {
            current.lastMessage = "已同步"
        }
        store.upsertItem(current)
    }

    private func syncStory(_ draft: StoryDraft) async throws {
        var current = draft
        current.status = .syncing
        current.lastMessage = "上传故事…"
        store.markStory(current)

        // 再次解析 pending → photo
        store.resolveStoryLinks(using: store.items)
        if let fresh = store.stories.first(where: { $0.storyId == draft.storyId }) {
            current = fresh
            current.status = .syncing
        }

        let links: [StoryLinkPayload] = current.linkedPhotoIds.enumerated().map { idx, pid in
            StoryLinkPayload(linkType: "photo", linkId: pid, sortOrder: idx)
        }
        // 合同：禁止把未解析 local_id 写入 links（pending 留在手机）

        let receipt = try await api.upsertStory(
            storyId: current.storyId,
            title: current.title,
            body: current.body,
            links: links,
            mutationId: current.mutationId,
            deviceId: deviceId
        )
        let st = receipt.status.lowercased()
        if st == "conflict" {
            current.status = .conflict
            current.lastMessage = receipt.message ?? "故事冲突"
            store.markStory(current)
            return
        }
        guard st == "accepted" else {
            throw DeskAPIError.httpStatus(400, receipt.message ?? receipt.status)
        }
        current.status = .synced
        current.lastMessage = receipt.message
            ?? (current.pendingLocalIds.isEmpty
                ? "故事已同步"
                : "故事已同步（还有 \(current.pendingLocalIds.count) 张图待回执后再挂）")
        store.markStory(current)
    }
}
