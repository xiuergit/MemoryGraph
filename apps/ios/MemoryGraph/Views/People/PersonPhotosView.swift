import SwiftUI

struct PersonPhotosView: View {
    @EnvironmentObject private var api: DeskAPIClient

    let person: PersonInfo
    var showsSchedule: Bool = true
    @StateObject private var model = PersonPhotosViewModel()
    @State private var detailPhoto: PhotoItem?
    @State private var section: PersonPageSection = .photos

    var body: some View {
        VStack(spacing: 0) {
            if showsSchedule {
                Picker("内容", selection: $section) {
                    Text("照片").tag(PersonPageSection.photos)
                    Text("日程").tag(PersonPageSection.agenda)
                    Text("月历").tag(PersonPageSection.month)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 12)
                .padding(.vertical, 4)
            }

            switch section {
            case .photos:
                photosBody
            case .agenda:
                if showsSchedule {
                    PersonAgendaView(person: person)
                } else {
                    photosBody
                }
            case .month:
                if showsSchedule {
                    PersonMonthView(person: person)
                } else {
                    photosBody
                }
            }
        }
        .navigationTitle(person.displayName)
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $detailPhoto) { photo in
            PhotoDetailView(photos: model.photos, initial: photo)
        }
        .task(id: person.id) {
            await model.load(person: person, api: api)
        }
    }

    @ViewBuilder
    private var photosBody: some View {
        if model.isLoading && model.photos.isEmpty {
            ProgressView("在找 \(person.displayName) 的照片…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
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
}

private enum PersonPageSection: Hashable {
    case photos
    case agenda
    case month
}
