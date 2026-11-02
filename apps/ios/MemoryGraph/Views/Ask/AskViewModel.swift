import Foundation

@MainActor
final class AskViewModel: ObservableObject {
    @Published var question: String = ""
    @Published var answer: String = ""
    @Published var evidence: [PhotoItem] = []
    @Published var followUps: [String] = []
    /// 无问答证据且无往年今天时：面面最近单人像
    @Published var defaultPortraits: [PhotoItem] = []
    /// 往年今天回忆卡（有则优先于最近像）
    @Published var onThisDayYears: [OnThisDayYear] = []
    @Published var isLoading = false
    @Published var isLoadingPortraits = false
    @Published var errorMessage: String?

    /// 每次成功拿到新答案时递增，供 UI 触发朗读。
    @Published private(set) var answerToken: Int = 0

    /// 上一轮 context，供「继续问」芯片带上。
    private var lastContext: AskTurnContext?

    static let defaultKidName = "面面"

    /// 右边「看照片」实际展示的列表（详情页翻页用）
    var displayPhotos: [PhotoItem] {
        if !evidence.isEmpty { return evidence }
        if !onThisDayYears.isEmpty {
            return onThisDayYears.flatMap(\.photos).filter { !$0.sourcePath.isEmpty }
        }
        return defaultPortraits
    }

    var photosTitle: String {
        if !evidence.isEmpty { return "看照片" }
        if !onThisDayYears.isEmpty { return "往年的今天" }
        if !defaultPortraits.isEmpty { return "\(Self.defaultKidName)最近" }
        return "看照片"
    }

    var showingOnThisDay: Bool {
        evidence.isEmpty && !onThisDayYears.isEmpty
    }

    var showingDefaultPortraits: Bool {
        evidence.isEmpty && onThisDayYears.isEmpty && !defaultPortraits.isEmpty
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
                await loadDefaultBrowse(using: api)
            }
        } catch {
            answer = ""
            evidence = []
            followUps = []
            errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    /// 默认逛图：优先往年今天，否则面面最近单人像。
    func loadDefaultBrowse(using api: DeskAPIClient, force: Bool = false) async {
        if !force, !onThisDayYears.isEmpty || !defaultPortraits.isEmpty { return }
        isLoadingPortraits = true
        defer { isLoadingPortraits = false }

        do {
            let response = try await api.fetchOnThisDay(person: Self.defaultKidName)
            let years = response.years.filter { year in
                !year.headline.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    && year.photos.contains { !$0.sourcePath.isEmpty }
            }
            if !years.isEmpty {
                onThisDayYears = years
                defaultPortraits = []
                return
            }
        } catch {
            // 往年今天失败时继续尝试最近像
        }

        onThisDayYears = []
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

    /// 兼容旧调用名
    func loadDefaultPortraits(using api: DeskAPIClient, force: Bool = false) async {
        await loadDefaultBrowse(using: api, force: force)
    }
}
