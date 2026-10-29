import PhotosUI
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// PhotosPicker 可靠取图字节（系统相册不删）。
struct RawImageData: Transferable {
    let data: Data

    static var transferRepresentation: some TransferRepresentation {
        DataRepresentation(importedContentType: .image) { data in
            RawImageData(data: data)
        }
    }
}

struct OutboxView: View {
    @EnvironmentObject private var store: OutboxStore
    @EnvironmentObject private var sync: OutboxSyncService
    @EnvironmentObject private var api: DeskAPIClient

    @State private var pickerItems: [PhotosPickerItem] = []
    @State private var importing = false
    @State private var importError: String?
    @State private var selected: OutboxItem?

    private var pendingItems: [OutboxItem] {
        store.items.filter { !$0.isFullySynced }
    }

    private var syncedItems: [OutboxItem] {
        store.items.filter(\.isFullySynced)
    }

    var body: some View {
        List {
                Section {
                    PhotosPicker(
                        selection: $pickerItems,
                        maxSelectionCount: 20,
                        matching: .images
                    ) {
                        Label("从相册选图（拷贝进 App）", systemImage: "photo.on.rectangle.angled")
                    }
                    .disabled(importing)

                    Button {
                        Task { await sync.syncAll() }
                    } label: {
                        Label(
                            store.isSyncing ? "同步中…" : "回家同步到 Mac",
                            systemImage: "arrow.triangle.2.circlepath"
                        )
                    }
                    .disabled(store.isSyncing || pendingItems.isEmpty)

                    if !store.lastSyncMessage.isEmpty {
                        Text(store.lastSyncMessage)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                } footer: {
                    Text("不删系统相册。选图后可写旁白，回家连上 Desk 再点同步：原图 → 旁白 → 故事。")
                }

                Section {
                    if pendingItems.isEmpty {
                        Text(store.items.isEmpty ? "还没有图。先从相册选几张。" : "没有待同步的了。")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(pendingItems) { item in
                            outboxRowButton(item)
                        }
                    }
                } header: {
                    Text("待同步 \(pendingItems.count)")
                }

                if !syncedItems.isEmpty {
                    Section {
                        ForEach(syncedItems) { item in
                            outboxRowButton(item)
                        }
                    } header: {
                        Text("已同步 \(syncedItems.count)")
                    } footer: {
                        Text("已到 Mac 的图仍留在本机队列，方便改旁白；不需要可左滑删除。")
                    }
                }
            }
            .listStyle(.insetGrouped)
            .scrollContentBackground(.hidden)
            .background(Color(uiColor: .systemGroupedBackground).ignoresSafeArea())
            .preferredColorScheme(.light)
            .navigationTitle("待上传")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(Color(uiColor: .systemGroupedBackground), for: .navigationBar)
            .toolbarColorScheme(.light, for: .navigationBar)
            .overlay {
                if importing {
                    ProgressView("拷贝中…")
                        .padding()
                        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
                }
            }
            .onChange(of: pickerItems) { _, newItems in
                guard !newItems.isEmpty else { return }
                Task { await importPhotos(newItems) }
            }
            .sheet(item: $selected) { item in
                NavigationStack {
                    OutboxItemEditor(item: item)
                }
                .preferredColorScheme(.light)
            }
            .alert("导入失败", isPresented: Binding(
                get: { importError != nil },
                set: { if !$0 { importError = nil } }
            )) {
                Button("好", role: .cancel) {}
            } message: {
                Text(importError ?? "")
            }
    }

    @ViewBuilder
    private func outboxRowButton(_ item: OutboxItem) -> some View {
        Button {
            selected = item
        } label: {
            OutboxRow(item: item, thumbURL: store.mediaURL(for: item))
        }
        .buttonStyle(.plain)
        .listRowBackground(Color(uiColor: .secondarySystemGroupedBackground))
        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
            Button(role: .destructive) {
                store.removeItem(localId: item.localId)
            } label: {
                Label("删除", systemImage: "trash")
            }
        }
    }

    private func importPhotos(_ pickerItems: [PhotosPickerItem]) async {
        importing = true
        defer {
            importing = false
            self.pickerItems = []
        }
        for item in pickerItems {
            do {
                let loaded = try await item.loadTransferable(type: RawImageData.self)
                guard let loaded else { continue }
                let name = item.itemIdentifier ?? "photo.jpg"
                _ = try store.addMedia(
                    data: loaded.data,
                    fileName: name,
                    contentType: item.supportedContentTypes.first
                )
            } catch {
                importError = error.localizedDescription
            }
        }
    }
}

private struct OutboxRow: View {
    let item: OutboxItem
    let thumbURL: URL

    var body: some View {
        HStack(spacing: 12) {
            LocalThumb(url: thumbURL)
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: 8))

            VStack(alignment: .leading, spacing: 4) {
                Text(item.fileName)
                    .lineLimit(1)
                Text(statusLabel)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if !item.userNote.isEmpty {
                    Text(item.userNote)
                        .font(.caption)
                        .lineLimit(2)
                }
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
    }

    private var statusLabel: String {
        let hasNote = !item.userNote.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        switch item.status {
        case .pending:
            if item.photoId.isEmpty {
                return hasNote ? "待上传（已写旁白）" : "待上传"
            }
            // 图已回执：按旁白是否已推区分
            if !hasNote { return "已上传 · 可写旁白" }
            return item.describeDone ? "待同步" : "待同步旁白"
        case .syncing: return "同步中"
        case .synced:
            if item.photoId.isEmpty { return "已同步" }
            if hasNote, !item.describeDone { return "已上传 · 旁白未推" }
            return hasNote ? "已同步 · 含旁白" : "已同步"
        case .failed: return "失败：\(item.lastMessage)"
        case .conflict: return "冲突：\(item.lastMessage)"
        }
    }
}

struct LocalThumb: View {
    let url: URL
    var fill: Bool = true

    var body: some View {
        Group {
            if let ui = UIImage(contentsOfFile: url.path) {
                Image(uiImage: ui)
                    .resizable()
                    .aspectRatio(contentMode: fill ? .fill : .fit)
            } else {
                Color.secondary.opacity(0.15)
            }
        }
    }
}

struct OutboxItemEditor: View {
    @EnvironmentObject private var store: OutboxStore
    @Environment(\.dismiss) private var dismiss

    let item: OutboxItem
    @State private var note: String = ""
    @StateObject private var recognizer = SpeechRecognizer()

    var body: some View {
        Form {
            Section {
                LocalThumb(url: store.mediaURL(for: item), fill: false)
                    .frame(maxHeight: 280)
                    .frame(maxWidth: .infinity)
                    .listRowInsets(EdgeInsets())
            }

            Section {
                TextField("写一句这张图的话…", text: $note, axis: .vertical)
                    .lineLimit(3 ... 8)

                if recognizer.isRecording {
                    Text(recognizer.transcript.isEmpty ? "正在听…" : recognizer.transcript)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Button {
                    toggleDictation()
                } label: {
                    Label(
                        recognizer.isRecording ? "说完了，写入旁白" : "语音输入",
                        systemImage: recognizer.isRecording ? "waveform" : "mic.fill"
                    )
                }
                .tint(recognizer.isRecording ? .red : .accentColor)

                if let err = recognizer.errorMessage, !err.isEmpty {
                    Text(err)
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
            } header: {
                Text("旁白")
            } footer: {
                Text("点「语音输入」说话，再说完点一次写入；也可继续手打改字。")
            }

            Section {
                LabeledContent("本地 id", value: item.localId)
                if !item.photoId.isEmpty {
                    LabeledContent("photo_id", value: item.photoId)
                }
                LabeledContent("状态", value: item.status.rawValue)
                if !item.lastMessage.isEmpty {
                    Text(item.lastMessage)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(Color(uiColor: .systemGroupedBackground).ignoresSafeArea())
        .preferredColorScheme(.light)
        .navigationTitle("编辑旁白")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(Color(uiColor: .systemGroupedBackground), for: .navigationBar)
        .toolbarColorScheme(.light, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("关闭") {
                    if recognizer.isRecording { recognizer.cancel() }
                    dismiss()
                }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("保存") {
                    if recognizer.isRecording {
                        appendDictation(recognizer.stop())
                    }
                    store.updateNote(localId: item.localId, note: note)
                    dismiss()
                }
            }
        }
        .onAppear {
            note = item.userNote
            Task { await recognizer.prepare() }
        }
        .onDisappear {
            if recognizer.isRecording { recognizer.cancel() }
        }
    }

    private func toggleDictation() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        if recognizer.isRecording {
            appendDictation(recognizer.stop())
        } else {
            recognizer.start(taskHint: .dictation)
        }
    }

    private func appendDictation(_ spoken: String) {
        let text = spoken.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let trimmed = note.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            note = text
        } else if trimmed.hasSuffix("。") || trimmed.hasSuffix("！") || trimmed.hasSuffix("？")
            || trimmed.hasSuffix(".") || trimmed.hasSuffix("!") || trimmed.hasSuffix("?")
        {
            note = trimmed + text
        } else {
            note = trimmed + "，" + text
        }
    }
}
