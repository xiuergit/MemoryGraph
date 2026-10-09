import SwiftUI

@main
struct MemoryGraphApp: App {
    @StateObject private var settings: AppSettings
    @StateObject private var api: DeskAPIClient
    @StateObject private var outboxStore: OutboxStore
    @StateObject private var outboxSync: OutboxSyncService

    init() {
        let settings = AppSettings()
        let api = DeskAPIClient(settings: settings)
        let store = OutboxStore()
        _settings = StateObject(wrappedValue: settings)
        _api = StateObject(wrappedValue: api)
        _outboxStore = StateObject(wrappedValue: store)
        _outboxSync = StateObject(
            wrappedValue: OutboxSyncService(store: store, api: api, settings: settings)
        )
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(settings)
                .environmentObject(api)
                .environmentObject(outboxStore)
                .environmentObject(outboxSync)
        }
    }
}
