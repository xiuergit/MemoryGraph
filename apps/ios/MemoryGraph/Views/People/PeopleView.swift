import SwiftUI

struct PeopleView: View {
    @EnvironmentObject private var api: DeskAPIClient
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    @StateObject private var model = PeopleViewModel()
    @State private var selected: PersonInfo?

    private var primary: PersonInfo? { model.people.primaryChild }

    private var others: [PersonInfo] {
        guard let primary else { return [] }
        return model.people.filter { $0.personId != primary.personId }
    }

    var body: some View {
        Group {
            if horizontalSizeClass == .regular {
                NavigationSplitView {
                    peopleList
                        .navigationBarTitleDisplayMode(.inline)
                } detail: {
                    if let person = selected ?? primary {
                        NavigationStack {
                            PersonPhotosView(person: person, showsSchedule: person.personId == primary?.personId)
                        }
                    } else {
                        loadingOrEmpty
                    }
                }
            } else {
                NavigationStack {
                    phoneRoot
                }
            }
        }
        .task {
            await model.load(using: api)
            if selected == nil {
                selected = model.people.primaryChild
            }
        }
    }

    @ViewBuilder
    private var phoneRoot: some View {
        if model.isLoading && model.people.isEmpty {
            ProgressView("找家里人…")
        } else if model.errorMessage != nil, model.people.isEmpty {
            ContentUnavailableView(
                "电脑还没好",
                systemImage: "wifi.exclamationmark",
                description: Text("叫大人看一下")
            )
        } else if let primary {
            PersonPhotosView(person: primary, showsSchedule: true)
                .toolbar {
                    if !others.isEmpty {
                        ToolbarItem(placement: .topBarTrailing) {
                            NavigationLink {
                                OtherPeopleList(people: others)
                            } label: {
                                Text("其他人")
                                    .font(.subheadline)
                            }
                        }
                    }
                }
        } else {
            loadingOrEmpty
                .navigationTitle("看谁")
                .navigationBarTitleDisplayMode(.inline)
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
                    if let primary {
                        Section {
                            personButton(primary, large: true)
                        }
                        if !others.isEmpty {
                            Section("其他人") {
                                ForEach(others) { person in
                                    personButton(person, large: false)
                                }
                            }
                        }
                    } else {
                        ForEach(model.people) { person in
                            personButton(person, large: true)
                        }
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

    private var loadingOrEmpty: some View {
        Group {
            if model.isLoading && model.people.isEmpty {
                ProgressView("找家里人…")
            } else if let err = model.errorMessage, model.people.isEmpty {
                ContentUnavailableView(
                    "电脑还没好",
                    systemImage: "wifi.exclamationmark",
                    description: Text(err)
                )
            } else {
                ContentUnavailableView(
                    "还没有人",
                    systemImage: "person.slash",
                    description: Text("让大人先登记人脸库")
                )
            }
        }
    }

    private func personButton(_ person: PersonInfo, large: Bool) -> some View {
        Button {
            selected = person
        } label: {
            PersonRow(person: person, large: large)
        }
        .listRowInsets(EdgeInsets(top: 10, leading: 16, bottom: 10, trailing: 16))
        .listRowBackground(Color.white.opacity(0.7))
    }
}

private struct OtherPeopleList: View {
    let people: [PersonInfo]

    var body: some View {
        List(people) { person in
            NavigationLink {
                PersonPhotosView(person: person, showsSchedule: false)
            } label: {
                PersonRow(person: person, large: false)
            }
        }
        .navigationTitle("其他人")
        .navigationBarTitleDisplayMode(.inline)
    }
}

extension Array where Element == PersonInfo {
    /// 看谁默认打开的那个人：面面，否则家里的孩子。
    var primaryChild: PersonInfo? {
        if let named = first(where: { $0.displayName.contains("面面") }) {
            return named
        }
        if let named = first(where: { $0.displayName.contains("宝宝") || $0.personId == "baby" }) {
            return named
        }
        let children = filter { $0.role == "child" }
        return children.max { ($0.photoCount ?? 0) < ($1.photoCount ?? 0) }
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
