import SwiftUI

@main
struct MemoryGraphApp: App {
    @StateObject private var settings: AppSettings
    @StateObject private var api: DeskAPIClient

    init() {
        let settings = AppSettings()
        _settings = StateObject(wrappedValue: settings)
        _api = StateObject(wrappedValue: DeskAPIClient(settings: settings))
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(settings)
                .environmentObject(api)
        }
    }
}
