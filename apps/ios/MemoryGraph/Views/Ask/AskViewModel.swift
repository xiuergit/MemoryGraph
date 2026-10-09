import Foundation

@MainActor
final class AskViewModel: ObservableObject {
    @Published var question: String = ""
    @Published var answer: String = ""
    @Published var evidence: [PhotoItem] = []
    @Published var followUps: [String] = []
    /// 无问答证据时展示：面面最近单人像
    @Published var defaultPortraits: [PhotoItem] = []
    @Published var isLoading = false
    @Published var isLoadingPortraits = false
    @Published var errorMessage: String?

    /// 每次成功拿到新答案时递增，供 UI 触发朗读。
    @Published private(set) var answerToken: Int = 0

    /// 上一轮 context，供「继续问」芯片带上。
    private var lastContext: AskTurnContext?

    static let defaultKidName = "面面"

    /// 右边「看照片」实际展示的列表
    var displayPhotos: [PhotoItem] {
        evidence.isEmpty ? defaultPortraits : evidence
    }

    var photosTitle: String {
        if evidence.isEmpty {
            return defaultPortraits.isEmpty ? "看照片" : "\(Self.defaultKidName)最近"
        }
        return "看照片"
    }

    var showingDefaultPortraits: Bool {
        evidence.isEmpty && !defaultPortraits.isEmpty
    }

    func useChip(_ text: String, api: DeskAPIClient) {
        question = text
        Task { await submit(using: api, withContext: false) }
    }

    func useFollowUp(_ text: String, api: DeskAPIClient) {
        question = text
        Task { await submit(using: api, withContext: true) }
    }

    func submitVoice(_ text: String, api: DeskAPIClient) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            errorMessage = "没听清，再点圆钮说一次吧"
            return
        }
        question = trimmed
        await submit(using: api, withContext: false)
    }

    func submit(using api: DeskAPIClient, withContext: Bool = false) async {
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else {
            errorMessage = "先说一句想问的话"
            return
        }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let ctx = withContext ? lastContext : nil
            let result = try await api.ask(question: q, context: ctx)
            answer = result.answer
            evidence = result.facts.mergedEvidencePhotos(from: result.evidence)
            followUps = result.followUps ?? []
            lastContext = result.context
            answerToken += 1
            if evidence.isEmpty {
                await loadDefaultPortraits(using: api)
            }
        } catch {
            answer = ""
            evidence = []
            followUps = []
            errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    func loadDefaultPortraits(using api: DeskAPIClient, force: Bool = false) async {
        if !force, !defaultPortraits.isEmpty { return }
        isLoadingPortraits = true
        defer { isLoadingPortraits = false }
        do {
            defaultPortraits = try await api.fetchSoloPortraits(
                person: Self.defaultKidName,
                limit: 24
            )
        } catch {
            if force {
                defaultPortraits = []
            }
        }
    }
}
