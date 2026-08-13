import SwiftUI

struct PersonPhotosView: View {
    @EnvironmentObject private var api: DeskAPIClient
    @EnvironmentObject private var settings: AppSettings

    let person: PersonInfo
    @StateObject private var model = PersonPhotosViewModel()
    @State private var detailPhoto: PhotoItem?

    var body: some View {
        Group {
            if model.isLoading && model.photos.isEmpty {
                ProgressView("在找 \(person.displayName) 的照片…")
            } else if let err = model.errorMessage, model.photos.isEmpty {
                ContentUnavailableView("加载失败", systemImage: "exclamationmark.triangle", description: Text(err))
            } else if model.photos.isEmpty {
                ContentUnavailableView(
                    "还没有照片",
                    systemImage: "photo",
                    description: Text("\(person.displayName) 在索引里暂时没有照片。")
                )
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("共 \(model.total) 张")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)

                        PhotoGridView(photos: model.photos) { photo in
                            detailPhoto = photo
                        }

                        if model.canLoadMore {
                            Button {
                                Task { await model.loadMore(api: api) }
                            } label: {
                                if model.isLoadingMore {
                                    ProgressView()
                                        .frame(maxWidth: .infinity)
                                } else {
                                    Text("再看一些")
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 8)
                                }
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.large)
                            .padding(.top, 8)
                        }
                    }
                    .padding()
                }
            }
        }
        .navigationTitle(person.displayName)
        .navigationBarTitleDisplayMode(settings.childFriendly ? .large : .inline)
        .navigationDestination(item: $detailPhoto) { photo in
            PhotoDetailView(photos: model.photos, initial: photo)
        }
        .task(id: person.id) {
            await model.load(person: person, api: api)
        }
    }
}
