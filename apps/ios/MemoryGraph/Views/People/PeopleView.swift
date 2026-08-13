import SwiftUI

struct PeopleView: View {
    @EnvironmentObject private var api: DeskAPIClient
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    @StateObject private var model = PeopleViewModel()
    @State private var selected: PersonInfo?

    var body: some View {
        Group {
            if horizontalSizeClass == .regular {
                NavigationSplitView {
                    peopleList
                        .navigationTitle("看谁")
                } detail: {
                    if let selected {
                        NavigationStack {
                            PersonPhotosView(person: selected)
                        }
                    } else {
                        ContentUnavailableView(
                            "点左边的人",
                            systemImage: "hand.tap.fill",
                            description: Text("点名字就能看照片")
                        )
                    }
                }
            } else {
                NavigationStack {
                    peopleList
                        .navigationTitle("看谁")
                        .navigationDestination(item: $selected) { person in
                            PersonPhotosView(person: person)
                        }
                }
            }
        }
        .task {
            await model.load(using: api)
        }
    }

    @ViewBuilder
    private var peopleList: some View {
        Group {
            if model.isLoading && model.people.isEmpty {
                ProgressView("找家里人…")
            } else if let err = model.errorMessage, model.people.isEmpty {
                ContentUnavailableView(
                    "电脑还没好",
                    systemImage: "wifi.exclamationmark",
                    description: Text("叫大人看一下")
                )
            } else if model.people.isEmpty {
                ContentUnavailableView(
                    "还没有人",
                    systemImage: "person.slash",
                    description: Text("让大人先登记人脸库")
                )
            } else {
                List {
                    ForEach(model.people) { person in
                        Button {
                            selected = person
                        } label: {
                            PersonRow(person: person, large: true)
                        }
                        .listRowInsets(EdgeInsets(top: 10, leading: 16, bottom: 10, trailing: 16))
                        .listRowBackground(Color.white.opacity(0.7))
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .background(KidPalette.sky)
                .refreshable {
                    await model.load(using: api)
                }
            }
        }
    }
}

private struct PersonRow: View {
    let person: PersonInfo
    var large: Bool

    var body: some View {
        HStack(spacing: 16) {
            ZStack {
                Circle()
                    .fill(KidPalette.teal.opacity(0.2))
                    .frame(width: large ? 64 : 44, height: large ? 64 : 44)
                Text(String(person.displayName.prefix(1)))
                    .font(.system(size: large ? 28 : 18, weight: .bold, design: .rounded))
                    .foregroundStyle(KidPalette.teal)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(person.displayName)
                    .font(.system(size: large ? 26 : 17, weight: .bold, design: .rounded))
                    .foregroundStyle(KidPalette.ink)
                Text(person.countLabel)
                    .font(.system(size: large ? 16 : 13, weight: .medium, design: .rounded))
                    .foregroundStyle(.secondary)
            }

            Spacer()
            Image(systemName: "chevron.right")
                .font(.title3.weight(.bold))
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, large ? 10 : 4)
        .contentShape(Rectangle())
    }
}
