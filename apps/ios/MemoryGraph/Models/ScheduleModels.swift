import Foundation

struct TimeOfDay: Codable, Equatable, Hashable, Sendable {
    var hour: Int
    var minute: Int

    var label: String {
        String(format: "%02d:%02d", hour, minute)
    }
}

struct CalendarDay: Codable, Equatable, Hashable, Sendable {
    var year: Int
    var month: Int
    var day: Int
}

/// 某一天的例外：不上，或只改这一天的时间。
struct DayOverride: Codable, Equatable, Hashable, Sendable {
    var year: Int
    var month: Int
    var day: Int
    var cancelled: Bool
    var start: TimeOfDay?
    var end: TimeOfDay?
    var title: String?

    func matches(year: Int, month: Int, day: Int) -> Bool {
        self.year == year && self.month == month && self.day == day
    }
}

enum ScheduleRecurrence: Codable, Equatable, Hashable, Sendable {
    case weekly(weekdays: [Int])
    case once(year: Int, month: Int, day: Int)
    case dates([CalendarDay])
    case range(year: Int, startMonth: Int, startDay: Int, endMonth: Int, endDay: Int)
}

struct ScheduleItem: Identifiable, Codable, Equatable, Sendable {
    static let kindergartenID = "kindergarten"

    var id: String
    var personId: String = ""
    var title: String
    var calendarTitle: String
    var start: TimeOfDay
    var end: TimeOfDay?
    var recurrence: ScheduleRecurrence
    var isHoliday: Bool = false
    var isWorkday: Bool = false
    var allDay: Bool = false
    var marksEndOnLastDate: Bool = false
    var skipDates: [CalendarDay] = []
    var overrides: [DayOverride] = []

    var isKindergarten: Bool { id == Self.kindergartenID }
    var isSwim: Bool { id.hasPrefix("swim") }

    var timeLabel: String {
        if isHoliday { return "放假" }
        if isWorkday { return "调休" }
        if allDay { return "全天" }
        if let end {
            return "\(start.label)–\(end.label)"
        }
        return start.label
    }

    var rangeLabel: String? {
        guard case .range(_, let startMonth, let startDay, let endMonth, let endDay) = recurrence else {
            return nil
        }
        if startMonth == endMonth {
            return "\(startMonth)月\(startDay)日–\(endDay)日"
        }
        return "\(startMonth)月\(startDay)日–\(endMonth)月\(endDay)日"
    }

    /// 这一天落在重复规则上（含已请假的那天）。
    func covers(year: Int, month: Int, day: Int, weekday: Int) -> Bool {
        switch recurrence {
        case .weekly(let weekdays):
            return weekdays.contains(weekday)
        case .once(let y, let m, let d):
            return y == year && m == month && d == day
        case .dates(let dates):
            return dates.contains { $0.year == year && $0.month == month && $0.day == day }
        case .range(let y, let startMonth, let startDay, let endMonth, let endDay):
            guard y == year else { return false }
            let value = month * 100 + day
            return value >= startMonth * 100 + startDay && value <= endMonth * 100 + endDay
        }
    }

    func isCancelled(year: Int, month: Int, day: Int) -> Bool {
        if skipDates.contains(where: { $0.year == year && $0.month == month && $0.day == day }) {
            return true
        }
        return overrides.contains { $0.cancelled && $0.matches(year: year, month: month, day: day) }
    }

    func override(year: Int, month: Int, day: Int) -> DayOverride? {
        overrides.first { !$0.cancelled && $0.matches(year: year, month: month, day: day) }
    }

    func isLastSession(year: Int, month: Int, day: Int) -> Bool {
        guard marksEndOnLastDate else { return false }
        guard case .dates(let dates) = recurrence, let last = dates.last else { return false }
        return last.year == year && last.month == month && last.day == day
    }

    func displayTitle(year: Int, month: Int, day: Int) -> String {
        if let custom = override(year: year, month: month, day: day)?.title, !custom.isEmpty {
            return custom
        }
        return isLastSession(year: year, month: month, day: day) ? "\(title)（结束）" : title
    }

    func displayCalendarTitle(year: Int, month: Int, day: Int) -> String {
        isLastSession(year: year, month: month, day: day) ? "\(calendarTitle)（结束）" : calendarTitle
    }

    func timeLabel(year: Int, month: Int, day: Int) -> String {
        if isHoliday { return "放假" }
        if isWorkday { return "调休" }
        if allDay { return "全天" }
        if isCancelled(year: year, month: month, day: day) { return "不上" }
        let startTime = override(year: year, month: month, day: day)?.start ?? start
        let endTime = override(year: year, month: month, day: day)?.end ?? end
        if let endTime {
            return "\(startTime.label)–\(endTime.label)"
        }
        return startTime.label
    }
}

struct Occurrence: Identifiable, Equatable, Sendable {
    var id: String
    var item: ScheduleItem
    var day: Date
    var startDate: Date
    var endDate: Date?
    var title: String
    var calendarTitle: String
    var marksEnd: Bool
    var cancelled: Bool
    var adjusted: Bool

    var timeLabel: String {
        let calendar = Calendar.paper
        return item.timeLabel(
            year: calendar.component(.year, from: day),
            month: calendar.component(.month, from: day),
            day: calendar.component(.day, from: day)
        )
    }
}

struct DayGroup: Identifiable, Equatable, Sendable {
    var id: Date { day }
    var day: Date
    var occurrences: [Occurrence]
}

struct ScheduleEngine: Sendable {
    var calendar: Calendar
    var items: [ScheduleItem]

    func occurrences(on day: Date) -> [Occurrence] {
        let dayStart = calendar.startOfDay(for: day)
        let weekday = calendar.component(.weekday, from: dayStart)
        let year = calendar.component(.year, from: dayStart)
        let month = calendar.component(.month, from: dayStart)
        let dayNumber = calendar.component(.day, from: dayStart)

        return items.compactMap { item in
            guard item.covers(year: year, month: month, day: dayNumber, weekday: weekday) else { return nil }
            return occurrence(item, on: dayStart)
        }
        .filter { item in
            if hasHoliday(year: year, month: month, day: dayNumber) {
                return !item.item.isKindergarten && !item.item.isSwim
            }
            return true
        }
        .sorted { lhs, rhs in
            if lhs.cancelled != rhs.cancelled {
                return !lhs.cancelled && rhs.cancelled
            }
            if lhs.item.isHoliday != rhs.item.isHoliday {
                return lhs.item.isHoliday && !rhs.item.isHoliday
            }
            if lhs.item.isWorkday != rhs.item.isWorkday {
                return lhs.item.isWorkday && !rhs.item.isWorkday
            }
            return lhs.startDate < rhs.startDate
        }
    }

    /// 月历格子用：不把每天的幼儿园铺满格子。
    func classOccurrences(on day: Date) -> [Occurrence] {
        occurrences(on: day).filter { !$0.item.isKindergarten && !$0.cancelled }
    }

    func groups(from start: Date, count: Int) -> [DayGroup] {
        (0..<count).compactMap { offset in
            guard let day = calendar.date(byAdding: .day, value: offset, to: calendar.startOfDay(for: start)) else {
                return nil
            }
            return DayGroup(day: day, occurrences: occurrences(on: day))
        }
    }

    func upcomingOnce(from start: Date, withinDays: Int = 90) -> [Occurrence] {
        let today = calendar.startOfDay(for: start)
        guard let end = calendar.date(byAdding: .day, value: withinDays, to: today) else { return [] }
        return items.compactMap { item -> Occurrence? in
            switch item.recurrence {
            case .once(let year, let month, let day):
                guard let dayStart = calendar.paperDate(year: year, month: month, day: day) else { return nil }
                guard dayStart >= today, dayStart < end else { return nil }
                return occurrence(item, on: dayStart)
            case .range(let year, let startMonth, let startDay, let endMonth, let endDay):
                guard item.isHoliday else { return nil }
                guard let rangeStart = calendar.paperDate(year: year, month: startMonth, day: startDay),
                      let rangeEnd = calendar.paperDate(year: year, month: endMonth, day: endDay) else { return nil }
                guard rangeEnd >= today, rangeStart < end else { return nil }
                return occurrence(item, on: max(today, rangeStart))
            case .weekly, .dates:
                return nil
            }
        }
        .filter { !$0.cancelled }
        .sorted { $0.startDate < $1.startDate }
    }

    func weeklyOverview() -> [(weekday: Int, title: String, occurrences: [ScheduleItem])] {
        Calendar.paperWeekOrder.map { weekday in
            let matches = items.filter { item in
                if case .weekly(let weekdays) = item.recurrence {
                    return weekdays.contains(weekday)
                }
                return false
            }
            .sorted { lhs, rhs in
                if lhs.start.hour != rhs.start.hour { return lhs.start.hour < rhs.start.hour }
                return lhs.start.minute < rhs.start.minute
            }
            return (weekday, Calendar.shortWeekdayName(weekday), matches)
        }
    }

    private func occurrence(_ item: ScheduleItem, on dayStart: Date) -> Occurrence {
        let year = calendar.component(.year, from: dayStart)
        let month = calendar.component(.month, from: dayStart)
        let day = calendar.component(.day, from: dayStart)
        let change = item.override(year: year, month: month, day: day)
        let startTime = change?.start ?? item.start
        let endTime = change?.end ?? item.end
        let startDate = calendar.date(
            bySettingHour: startTime.hour,
            minute: startTime.minute,
            second: 0,
            of: dayStart
        ) ?? dayStart
        let endDate = endTime.flatMap {
            calendar.date(bySettingHour: $0.hour, minute: $0.minute, second: 0, of: dayStart)
        }
        let stamp = Calendar.dayStamp(dayStart, calendar: calendar)
        let cancelled = item.isCancelled(year: year, month: month, day: day)
        return Occurrence(
            id: "\(item.id)-\(stamp)",
            item: item,
            day: dayStart,
            startDate: startDate,
            endDate: endDate,
            title: item.displayTitle(year: year, month: month, day: day),
            calendarTitle: item.displayCalendarTitle(year: year, month: month, day: day),
            marksEnd: item.isLastSession(year: year, month: month, day: day),
            cancelled: cancelled,
            adjusted: change != nil
        )
    }

    private func hasHoliday(year: Int, month: Int, day: Int) -> Bool {
        items.contains { item in
            item.isHoliday && item.covers(year: year, month: month, day: day, weekday: 0)
        }
    }
}

extension Calendar {
    static let paper: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.locale = Locale(identifier: "zh_CN")
        calendar.timeZone = .current
        calendar.firstWeekday = 2
        return calendar
    }()

    static let paperWeekOrder = [2, 3, 4, 5, 6, 7, 1]

    static func shortWeekdayName(_ weekday: Int) -> String {
        let names = [1: "周日", 2: "周一", 3: "周二", 4: "周三", 5: "周四", 6: "周五", 7: "周六"]
        return names[weekday] ?? ""
    }

    static func dayStamp(_ date: Date, calendar: Calendar = .paper) -> String {
        let y = calendar.component(.year, from: date)
        let m = calendar.component(.month, from: date)
        let d = calendar.component(.day, from: date)
        return String(format: "%04d-%02d-%02d", y, m, d)
    }

    func paperDateLabel(_ date: Date) -> String {
        let weekday = Self.shortWeekdayName(component(.weekday, from: date))
        let month = component(.month, from: date)
        let day = component(.day, from: date)
        return "\(weekday) \(month)月\(day)日"
    }

    func paperShortDateLabel(_ date: Date) -> String {
        "\(component(.month, from: date))月\(component(.day, from: date))日"
    }

    func paperMonthLabel(_ date: Date) -> String {
        "\(component(.year, from: date))年\(component(.month, from: date))月"
    }

    func paperDate(year: Int, month: Int, day: Int) -> Date? {
        var parts = DateComponents()
        parts.year = year
        parts.month = month
        parts.day = day
        return self.date(from: parts).map { startOfDay(for: $0) }
    }

    func startOfMonth(for date: Date) -> Date {
        let parts = dateComponents([.year, .month], from: date)
        return self.date(from: parts) ?? startOfDay(for: date)
    }

    func monthGrid(for month: Date) -> [Date?] {
        let start = startOfMonth(for: month)
        let weekday = component(.weekday, from: start)
        let leading = (weekday - firstWeekday + 7) % 7
        let dayCount = range(of: .day, in: .month, for: start)?.count ?? 0
        var cells: [Date?] = Array(repeating: nil, count: leading)
        for day in 1...dayCount {
            var parts = dateComponents([.year, .month], from: start)
            parts.day = day
            cells.append(self.date(from: parts))
        }
        while cells.count % 7 != 0 {
            cells.append(nil)
        }
        return cells
    }
}

struct DiaryEntry: Identifiable, Codable, Equatable, Sendable {
    var id: String
    var personId: String
    /// 日历日，YYYY-MM-DD
    var day: String
    var body: String
    var updatedAt: String
}

func t(_ hour: Int, _ minute: Int) -> TimeOfDay {
    TimeOfDay(hour: hour, minute: minute)
}

func d(_ year: Int, _ month: Int, _ day: Int) -> CalendarDay {
    CalendarDay(year: year, month: month, day: day)
}
