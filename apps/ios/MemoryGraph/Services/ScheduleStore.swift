import Foundation

/// 每人一份日程，存在手机沙盒。面面（或家里的孩子）第一次打开时导入 PaperDays 课表。
@MainActor
final class ScheduleStore: ObservableObject {
    @Published private(set) var items: [ScheduleItem] = []
    @Published private(set) var diaries: [DiaryEntry] = []

    private var seededPersonIds: [String] = []
    private let fileManager = FileManager.default
    private let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }()
    private let decoder = JSONDecoder()

    private struct Manifest: Codable {
        var seededPersonIds: [String]
        var items: [ScheduleItem]
    }

    private var fileURL: URL {
        let docs = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first!
        return docs.appendingPathComponent("schedules.json")
    }

    private var diaryURL: URL {
        let docs = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first!
        return docs.appendingPathComponent("diaries.json")
    }

    init() {
        load()
        loadDiaries()
    }

    func items(for personId: String) -> [ScheduleItem] {
        items.filter { $0.personId == personId }
    }

    func engine(for personId: String) -> ScheduleEngine {
        ScheduleEngine(calendar: .paper, items: items(for: personId))
    }

    /// 打开某个人时调用。已经导入过的人，删光了也不会再自动灌课表。
    func ensureSeeded(_ person: PersonInfo) {
        let personId = person.personId
        guard !personId.isEmpty else { return }
        guard !seededPersonIds.contains(personId) else { return }
        seededPersonIds.append(personId)
        if ownsCatalog(person), !items.contains(where: { $0.personId == personId }) {
            let seeded = ScheduleCatalog.items.map { item in
                var copy = item
                copy.personId = personId
                return copy
            }
            items.append(contentsOf: seeded)
        }
        save()
    }

    func applyDayChange(
        itemId: String,
        day: Date,
        cancelled: Bool,
        start: TimeOfDay,
        end: TimeOfDay?
    ) {
        guard let idx = items.firstIndex(where: { $0.id == itemId }) else { return }
        let calendar = Calendar.paper
        let year = calendar.component(.year, from: day)
        let month = calendar.component(.month, from: day)
        let dayNumber = calendar.component(.day, from: day)
        items[idx].skipDates.removeAll { $0.year == year && $0.month == month && $0.day == dayNumber }
        items[idx].overrides.removeAll { $0.matches(year: year, month: month, day: dayNumber) }
        if cancelled {
            items[idx].skipDates.append(CalendarDay(year: year, month: month, day: dayNumber))
        } else if start != items[idx].start || end != items[idx].end {
            items[idx].overrides.append(
                DayOverride(
                    year: year,
                    month: month,
                    day: dayNumber,
                    cancelled: false,
                    start: start,
                    end: end,
                    title: nil
                )
            )
        }
        save()
    }

    func replace(_ item: ScheduleItem) {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        items[idx] = item
        save()
    }

    func add(_ item: ScheduleItem) {
        items.append(item)
        save()
    }

    func remove(itemId: String) {
        items.removeAll { $0.id == itemId }
        save()
    }

    func diaries(for personId: String, on day: Date) -> [DiaryEntry] {
        let stamp = Calendar.dayStamp(day)
        return diaries
            .filter { $0.personId == personId && $0.day == stamp }
            .sorted { $0.updatedAt > $1.updatedAt }
    }

    func hasDiary(for personId: String, on day: Date) -> Bool {
        !diaries(for: personId, on: day).isEmpty
    }

    @discardableResult
    func saveDiary(personId: String, day: Date, entryId: String?, body: String) -> DiaryEntry? {
        let text = body.trimmingCharacters(in: .whitespacesAndNewlines)
        let stamp = Calendar.dayStamp(day)
        if text.isEmpty {
            if let entryId {
                diaries.removeAll { $0.id == entryId }
                saveDiaries()
            }
            return nil
        }
        let now = ISO8601DateFormatter().string(from: Date())
        if let entryId, let idx = diaries.firstIndex(where: { $0.id == entryId }) {
            diaries[idx].body = text
            diaries[idx].updatedAt = now
            saveDiaries()
            return diaries[idx]
        }
        let entry = DiaryEntry(
            id: "dry_" + String(UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased().prefix(12)),
            personId: personId,
            day: stamp,
            body: text,
            updatedAt: now
        )
        diaries.insert(entry, at: 0)
        saveDiaries()
        return entry
    }

    private func ownsCatalog(_ person: PersonInfo) -> Bool {
        let name = person.displayName
        if name.contains("面面") || name.contains("宝宝") || person.personId == "baby" {
            return true
        }
        // 课表还没给过任何人时，给第一个孩子。
        if person.role == "child", !items.contains(where: { !$0.personId.isEmpty }) {
            return true
        }
        return false
    }

    private func load() {
        guard fileManager.fileExists(atPath: fileURL.path) else { return }
        do {
            let data = try Data(contentsOf: fileURL)
            let manifest = try decoder.decode(Manifest.self, from: data)
            seededPersonIds = manifest.seededPersonIds
            items = manifest.items
        } catch {
            items = []
            seededPersonIds = []
        }
    }

    private func save() {
        let manifest = Manifest(seededPersonIds: seededPersonIds, items: items)
        do {
            let data = try encoder.encode(manifest)
            try data.write(to: fileURL, options: .atomic)
        } catch {
            // 下次打开会再读旧文件；不打断正在改的界面。
        }
    }

    private struct DiaryFile: Codable {
        var entries: [DiaryEntry]
    }

    private func loadDiaries() {
        guard fileManager.fileExists(atPath: diaryURL.path) else { return }
        do {
            let data = try Data(contentsOf: diaryURL)
            diaries = try decoder.decode(DiaryFile.self, from: data).entries
        } catch {
            diaries = []
        }
    }

    private func saveDiaries() {
        do {
            let data = try encoder.encode(DiaryFile(entries: diaries))
            try data.write(to: diaryURL, options: .atomic)
        } catch {
            // 日记没写上时，界面里的字还在，下次再存。
        }
    }
}
