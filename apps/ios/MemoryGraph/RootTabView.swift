import SwiftUI

enum RootTab: Hashable {
    case ask
    case people
    case outbox
    case stories
}

struct RootTabView: View {
    @EnvironmentObject private var settings: AppSettings
    @State private var showSettings = false
    @State private var selectedTab: RootTab = .ask

    var body: some View {
        VStack(spacing: 0) {
            ConnectionBanner(
                showSettings: $showSettings,
                selectedTab: $selectedTab
            )

            // 不用系统 TabView：避免顶栏芯片 + 底栏/顶栏再出一套
            Group {
                switch selectedTab {
                case .ask:
                    AskView()
                case .people:
                    PeopleView()
                case .outbox:
                    OutboxView()
                case .stories:
                    StoriesView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .preferredColorScheme(.light)
        .sheet(isPresented: $showSettings) {
            NavigationStack {
                SettingsView()
            }
            .presentationDetents([.large, .medium])
            .presentationDragIndicator(.visible)
        }
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
}
