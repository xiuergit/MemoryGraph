import Combine
import Foundation

/// 本地设置：Mac Desk 地址等。不含密钥。
@MainActor
final class AppSettings: ObservableObject {
    @Published var host: String {
        didSet { UserDefaults.standard.set(host, forKey: Keys.host) }
    }

    @Published var port: String {
        didSet { UserDefaults.standard.set(port, forKey: Keys.port) }
    }

    /// 儿童模式：更大字号、默认人物（P1 扩展）
    @Published var childFriendly: Bool {
        didSet { UserDefaults.standard.set(childFriendly, forKey: Keys.childFriendly) }
    }

    /// 问答成功后自动朗读答案
    @Published var autoSpeakAnswer: Bool {
        didSet { UserDefaults.standard.set(autoSpeakAnswer, forKey: Keys.autoSpeakAnswer) }
    }

    /// 家长模式：显示 Outbox / 故事 Tab（选图上传、写旁白）
    @Published var parentMode: Bool {
        didSet { UserDefaults.standard.set(parentMode, forKey: Keys.parentMode) }
    }

    private enum Keys {
        static let host = "desk.host"
        static let port = "desk.port"
        static let childFriendly = "ui.childFriendly"
        static let autoSpeakAnswer = "ui.autoSpeakAnswer"
        static let parentMode = "ui.parentMode"
    }

    init() {
        let defaults = UserDefaults.standard
        host = defaults.string(forKey: Keys.host) ?? "127.0.0.1"
        port = defaults.string(forKey: Keys.port) ?? "8766"
        childFriendly = defaults.object(forKey: Keys.childFriendly) as? Bool ?? true
        autoSpeakAnswer = defaults.object(forKey: Keys.autoSpeakAnswer) as? Bool ?? true
        // 默认打开：iPad/iPhone 都能直接看到「待上传」「故事」；要藏可在设置里关
        parentMode = defaults.object(forKey: Keys.parentMode) as? Bool ?? true
    }

    var baseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedPort = port.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty, !trimmedPort.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):\(trimmedPort)")
    }

    var displayEndpoint: String {
        "\(host):\(port)"
    }
}
