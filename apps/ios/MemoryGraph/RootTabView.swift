import SwiftUI

enum RootTab: Hashable {
    case ask
    case people
}

struct RootTabView: View {
    @EnvironmentObject private var api: DeskAPIClient
    @State private var showAdult = false
    @State private var selectedTab: RootTab = .ask

    var body: some View {
        VStack(spacing: 0) {
            KidTopBar(showAdult: $showAdult)

            Group {
                switch selectedTab {
                case .ask:
                    AskView()
                case .people:
                    PeopleView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            KidTabBar(selectedTab: $selectedTab)
        }
        .preferredColorScheme(.light)
        .sheet(isPresented: $showAdult) {
            NavigationStack {
                AdultHomeView()
            }
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        }
        .task {
            await api.checkHealth()
        }
    }
}

private struct KidTopBar: View {
    @EnvironmentObject private var api: DeskAPIClient
    @Binding var showAdult: Bool

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(statusColor)
                .frame(width: 8, height: 8)

            if api.isReachable != true {
                Text(statusText)
                    .font(.subheadline)
                    .foregroundStyle(KidPalette.ink.opacity(0.75))
                    .lineLimit(1)
            }

            Spacer(minLength: 8)

            Button("大人") {
                showAdult = true
            }
            .buttonStyle(.borderless)
            .font(.system(size: 16, weight: .semibold, design: .rounded))
            .foregroundStyle(KidPalette.teal)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background {
            Color.white.ignoresSafeArea(edges: .top)
        }
        .overlay(alignment: .bottom) { Divider() }
    }

    private var statusColor: Color {
        switch api.isReachable {
        case true: return Color(red: 0.30, green: 0.75, blue: 0.40)
        case false: return Color.orange
        case nil: return .gray
        }
    }

    private var statusText: String {
        switch api.isReachable {
        case false: return "叫大人打开电脑"
        case nil: return "正在找电脑…"
        case true: return ""
        }
    }
}

private struct KidTabBar: View {
    @Binding var selectedTab: RootTab

    var body: some View {
        HStack(spacing: 0) {
            tab("问一问", .ask)
            tab("看谁", .people)
        }
        .padding(.top, 6)
        .padding(.bottom, 4)
        .background {
            Color.white.ignoresSafeArea(edges: .bottom)
        }
        .overlay(alignment: .top) { Divider() }
    }

    private func tab(_ title: String, _ tab: RootTab) -> some View {
        let selected = selectedTab == tab
        return Button {
            selectedTab = tab
        } label: {
            VStack(spacing: 6) {
                Text(title)
                    .font(.system(size: 17, weight: selected ? .bold : .regular, design: .rounded))
                Capsule()
                    .fill(selected ? KidPalette.teal : Color.clear)
                    .frame(width: 28, height: 3)
            }
            .foregroundStyle(selected ? KidPalette.teal : Color.secondary)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 4)
        }
        .buttonStyle(.plain)
    }
}

private struct AdultHomeView: View {
    @EnvironmentObject private var api: DeskAPIClient
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        List {
            Section {
                NavigationLink {
                    OutboxView()
                } label: {
                    Label("待上传", systemImage: "square.and.arrow.up")
                }
                NavigationLink {
                    StoriesView()
                } label: {
                    Label("故事", systemImage: "text.book.closed")
                }
            } footer: {
                Text("选图、写旁白、写故事，回家再同步到 Mac。不删系统相册。")
            }

            Section {
                LabeledContent("电脑", value: connectionLabel)
                NavigationLink {
                    SettingsView()
                } label: {
                    Label("设置", systemImage: "gearshape")
                }
            }
        }
        .navigationTitle("大人")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("完成") { dismiss() }
            }
        }
    }

    private var connectionLabel: String {
        if api.isReachable == true {
            return "已连上 \(settings.displayEndpoint)"
        }
        if api.isReachable == false {
            return "没连上"
        }
        return "正在找…"
    }
}

#Preview {
    let settings = AppSettings()
    let api = DeskAPIClient(settings: settings)
    let store = OutboxStore()
    return RootTabView()
        .environmentObject(settings)
        .environmentObject(api)
        .environmentObject(store)
        .environmentObject(OutboxSyncService(store: store, api: api, settings: settings))
        .environmentObject(ScheduleStore())
}
