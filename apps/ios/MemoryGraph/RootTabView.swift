import SwiftUI

struct RootTabView: View {
    @EnvironmentObject private var settings: AppSettings
    @State private var showSettings = false

    var body: some View {
        TabView {
            AskView()
                .tabItem {
                    Label("问一问", systemImage: "mic.circle.fill")
                }

            PeopleView()
                .tabItem {
                    Label("看谁", systemImage: "person.crop.circle.fill")
                }
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            ConnectionBanner(showSettings: $showSettings)
        }
        .sheet(isPresented: $showSettings) {
            NavigationStack {
                SettingsView()
            }
            .presentationDetents([.medium, .large])
        }
    }
}

#Preview {
    let settings = AppSettings()
    return RootTabView()
        .environmentObject(settings)
        .environmentObject(DeskAPIClient(settings: settings))
}
