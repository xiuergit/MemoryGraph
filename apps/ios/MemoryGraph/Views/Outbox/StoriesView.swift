import SwiftUI

struct StoriesView: View {
    @EnvironmentObject private var store: OutboxStore
    @EnvironmentObject private var sync: OutboxSyncService

    @State private var editing: StoryDraft?

    var body: some View {
        List {
                Section {
                    Button {
                        editing = StoryDraft()
                    } label: {
                        Label("新建故事（可无图）", systemImage: "plus.circle.fill")
                    }

                    Button {
                        Task { await sync.syncAll() }
                    } label: {
                        Label(
                            store.isSyncing ? "同步中…" : "同步故事到 Mac",
                            systemImage: "arrow.triangle.2.circlepath"
                        )
                    }
                    .disabled(store.isSyncing)

                    if !store.lastSyncMessage.isEmpty {
                        Text(store.lastSyncMessage)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                } footer: {
                    Text("无图可先写；配图请挂 Outbox 里的本地图，回执成 photo_id 后再写入 Mac。不要把未解析 local_id 直接当长期链接。")
                }

                Section("草稿 \(store.stories.count)") {
                    if store.stories.isEmpty {
                        Text("还没有故事。")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(store.stories) { story in
                        Button {
                            editing = story
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(story.title.isEmpty ? "（无标题）" : story.title)
                                    .foregroundStyle(.primary)
                                Text(storyStatus(story))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                if !story.body.isEmpty {
                                    Text(story.body)
                                        .font(.caption)
                                        .lineLimit(2)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                store.removeStory(storyId: story.storyId)
                            } label: {
                                Label("删除", systemImage: "trash")
                            }
                        }
                    }
                }
            }
            .navigationTitle("故事")
            .navigationBarTitleDisplayMode(.inline)
            .sheet(item: $editing) { story in
                NavigationStack {
                    StoryEditorView(draft: story)
                }
                .preferredColorScheme(.light)
            }
    }

    private func storyStatus(_ s: StoryDraft) -> String {
        let pend = s.pendingLocalIds.count
        let linked = s.linkedPhotoIds.count
        let base: String
        switch s.status {
        case .pending: base = "待同步"
        case .syncing: base = "同步中"
        case .synced: base = "已同步"
        case .failed: base = "失败"
        case .conflict: base = "冲突"
        }
        return "\(base) · 已挂 \(linked) 张 · 待回执 \(pend)"
    }
}

struct StoryEditorView: View {
    @EnvironmentObject private var store: OutboxStore
    @Environment(\.dismiss) private var dismiss

    private let source: StoryDraft
    @State private var draft: StoryDraft
    @State private var didLoad = false

    init(draft: StoryDraft) {
        source = draft
        _draft = State(initialValue: draft)
    }

    var body: some View {
        Form {
            Section("标题") {
                TextField("故事标题", text: $draft.title)
            }
            Section("正文") {
                TextField("写故事…", text: $draft.body, axis: .vertical)
                    .lineLimit(5 ... 16)
            }
            Section {
                Text("挂 Outbox 图（同步后才变成 photo_id）")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                ForEach(store.items) { item in
                    Toggle(isOn: bindingFor(item.localId)) {
                        VStack(alignment: .leading) {
                            Text(item.fileName)
                            if !item.photoId.isEmpty {
                                Text("已落地 \(item.photoId)")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            } else {
                                Text("待上传 · \(item.localId)")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                if store.items.isEmpty {
                    Text("Outbox 还没有图，可先保存无图故事。")
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("配图")
            }

            if !draft.lastMessage.isEmpty {
                Section("上次同步") {
                    Text(draft.lastMessage)
                        .font(.footnote)
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(Color(uiColor: .systemGroupedBackground).ignoresSafeArea())
        .preferredColorScheme(.light)
        .navigationTitle(draft.title.isEmpty ? "新故事" : "编辑故事")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(Color(uiColor: .systemGroupedBackground), for: .navigationBar)
        .toolbarColorScheme(.light, for: .navigationBar)
        .onAppear {
            guard !didLoad else { return }
            didLoad = true
            draft = source
        }
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("取消") { dismiss() }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("保存") {
                    let title = draft.title.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !title.isEmpty else { return }
                    draft.title = title
                    store.upsertStory(draft)
                    dismiss()
                }
                .disabled(draft.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }

    private func bindingFor(_ localId: String) -> Binding<Bool> {
        Binding(
            get: {
                draft.pendingLocalIds.contains(localId)
                    || store.items.first(where: { $0.localId == localId }).map { item in
                        !item.photoId.isEmpty && draft.linkedPhotoIds.contains(item.photoId)
                    } ?? false
            },
            set: { on in
                if on {
                    if let item = store.items.first(where: { $0.localId == localId }), !item.photoId.isEmpty {
                        if !draft.linkedPhotoIds.contains(item.photoId) {
                            draft.linkedPhotoIds.append(item.photoId)
                        }
                        draft.pendingLocalIds.removeAll { $0 == localId }
                    } else if !draft.pendingLocalIds.contains(localId) {
                        draft.pendingLocalIds.append(localId)
                    }
                } else {
                    draft.pendingLocalIds.removeAll { $0 == localId }
                    if let item = store.items.first(where: { $0.localId == localId }) {
                        draft.linkedPhotoIds.removeAll { $0 == item.photoId }
                    }
                }
            }
        )
    }
}
