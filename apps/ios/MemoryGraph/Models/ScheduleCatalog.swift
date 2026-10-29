import Foundation

/// 面面现有课表。第一次打开这个孩子时导入手机，之后以本地修改为准。
enum ScheduleCatalog {
    static let items: [ScheduleItem] = [
        ScheduleItem(
            id: "kindergarten",
            title: "幼儿园",
            calendarTitle: "幼儿园",
            start: t(7, 50),
            end: t(16, 10),
            recurrence: .weekly(weekdays: [2, 3, 4, 5, 6])
        ),
        ScheduleItem(
            id: "swim-weekday",
            title: "游泳课",
            calendarTitle: "游泳",
            start: t(17, 30),
            end: t(18, 30),
            recurrence: .weekly(weekdays: [3, 5])
        ),
        ScheduleItem(
            id: "drawing",
            title: "画画课",
            calendarTitle: "画画",
            start: t(19, 00),
            end: t(20, 30),
            recurrence: .dates([
                d(2026, 8, 28),
                d(2026, 9, 4),
                d(2026, 9, 11),
                d(2026, 9, 18),
                d(2026, 9, 23),
                d(2026, 10, 9),
                d(2026, 10, 16),
                d(2026, 10, 23),
                d(2026, 10, 30),
                d(2026, 11, 6),
                d(2026, 11, 13),
                d(2026, 11, 20),
                d(2026, 11, 27),
                d(2026, 12, 4),
                d(2026, 12, 11),
                d(2026, 12, 18),
                d(2026, 12, 25),
                d(2026, 12, 30),
                d(2027, 1, 8),
                d(2027, 1, 15),
                d(2027, 1, 22),
            ])
        ),
        ScheduleItem(
            id: "swim-saturday",
            title: "游泳课",
            calendarTitle: "游泳",
            start: t(14, 15),
            end: t(15, 15),
            recurrence: .weekly(weekdays: [7]),
            skipDates: [d(2026, 10, 10)]
        ),
        ScheduleItem(
            id: "swim-2026-10-10",
            title: "游泳课",
            calendarTitle: "游泳",
            start: t(17, 30),
            end: t(18, 30),
            recurrence: .once(year: 2026, month: 10, day: 10)
        ),
        ScheduleItem(
            id: "dance",
            title: "跳舞课",
            calendarTitle: "跳舞",
            start: t(16, 40),
            end: t(17, 40),
            recurrence: .dates([
                d(2026, 8, 29),
                d(2026, 9, 5),
                d(2026, 9, 12),
                d(2026, 9, 19),
                d(2026, 9, 26),
                d(2026, 10, 6),
                d(2026, 10, 17),
                d(2026, 10, 24),
                d(2026, 10, 31),
                d(2026, 11, 7),
                d(2026, 11, 14),
                d(2026, 11, 21),
                d(2026, 11, 28),
                d(2026, 12, 5),
                d(2026, 12, 12),
                d(2026, 12, 19),
                d(2026, 12, 26),
                d(2027, 1, 2),
                d(2027, 1, 9),
                d(2027, 1, 16),
                d(2027, 1, 23),
            ])
        ),
        ScheduleItem(
            id: "dance-recital-2027",
            title: "期末汇报",
            calendarTitle: "汇报",
            start: t(16, 40),
            end: t(17, 40),
            recurrence: .dates([
                d(2027, 1, 28),
                d(2027, 1, 29),
            ])
        ),
        ScheduleItem(
            id: "calligraphy",
            title: "硬笔书法课",
            calendarTitle: "书法",
            start: t(10, 45),
            end: t(11, 45),
            recurrence: .dates([
                CalendarDay(year: 2026, month: 9, day: 6),
                CalendarDay(year: 2026, month: 9, day: 13),
                CalendarDay(year: 2026, month: 10, day: 11),
                CalendarDay(year: 2026, month: 10, day: 18),
                CalendarDay(year: 2026, month: 10, day: 25),
                CalendarDay(year: 2026, month: 11, day: 1),
                CalendarDay(year: 2026, month: 11, day: 8),
                CalendarDay(year: 2026, month: 11, day: 15),
                CalendarDay(year: 2026, month: 11, day: 22),
                CalendarDay(year: 2026, month: 11, day: 29),
                CalendarDay(year: 2026, month: 12, day: 6),
                CalendarDay(year: 2026, month: 12, day: 13),
                CalendarDay(year: 2026, month: 12, day: 20),
                CalendarDay(year: 2026, month: 12, day: 27),
            ]),
            marksEndOnLastDate: true
        ),
        ScheduleItem(
            id: "performance",
            title: "表演课",
            calendarTitle: "表演",
            start: t(15, 20),
            end: t(16, 40),
            recurrence: .dates([
                d(2026, 8, 30),
                d(2026, 9, 6),
                d(2026, 9, 13),
                d(2026, 9, 27),
                d(2026, 10, 7),
                d(2026, 10, 11),
                d(2026, 10, 18),
                d(2026, 10, 25),
                d(2026, 11, 1),
                d(2026, 11, 8),
                d(2026, 11, 15),
                d(2026, 11, 22),
                d(2026, 11, 29),
                d(2026, 12, 6),
                d(2026, 12, 13),
                d(2026, 12, 20),
                d(2026, 12, 27),
            ]),
            marksEndOnLastDate: true
        ),
        ScheduleItem(
            id: "performance-recital-2027",
            title: "汇报演出",
            calendarTitle: "演出",
            start: t(15, 20),
            end: t(16, 40),
            recurrence: .dates([
                d(2027, 1, 8),
                d(2027, 1, 9),
                d(2027, 1, 10),
            ])
        ),
        ScheduleItem(
            id: "go-1840",
            title: "围棋课",
            calendarTitle: "围棋",
            start: t(18, 40),
            end: t(19, 10),
            recurrence: .dates([
                d(2026, 10, 28),
                d(2026, 11, 4),
            ])
        ),
        ScheduleItem(
            id: "go-2026-10-31",
            title: "围棋课",
            calendarTitle: "围棋",
            start: t(10, 40),
            end: t(11, 10),
            recurrence: .once(year: 2026, month: 10, day: 31)
        ),
        ScheduleItem(
            id: "go-2026-11-03",
            title: "围棋课",
            calendarTitle: "围棋",
            start: t(19, 30),
            end: t(20, 30),
            recurrence: .once(year: 2026, month: 11, day: 3)
        ),
        ScheduleItem(
            id: "go-2026-11-07",
            title: "围棋课",
            calendarTitle: "围棋",
            start: t(19, 20),
            end: t(19, 50),
            recurrence: .once(year: 2026, month: 11, day: 7)
        ),
        ScheduleItem(
            id: "spartan-2026-09-25",
            title: "斯巴达比赛",
            calendarTitle: "斯巴达",
            start: t(13, 00),
            end: nil,
            recurrence: .once(year: 2026, month: 9, day: 25)
        ),
        ScheduleItem(
            id: "mid-autumn-2026",
            title: "中秋",
            calendarTitle: "中秋",
            start: t(0, 0),
            end: nil,
            recurrence: .range(year: 2026, startMonth: 9, startDay: 25, endMonth: 9, endDay: 27),
            isHoliday: true
        ),
        ScheduleItem(
            id: "national-day-2026",
            title: "国庆",
            calendarTitle: "国庆",
            start: t(0, 0),
            end: nil,
            recurrence: .range(year: 2026, startMonth: 10, startDay: 1, endMonth: 10, endDay: 7),
            isHoliday: true
        ),
        ScheduleItem(
            id: "nd-2026-10-01",
            title: "朋友来我家📚",
            calendarTitle: "朋友",
            start: t(0, 0),
            end: nil,
            recurrence: .once(year: 2026, month: 10, day: 1),
            allDay: true
        ),
        ScheduleItem(
            id: "art-photo-2026-11-14",
            title: "拍艺术照",
            calendarTitle: "艺术照",
            start: t(9, 00),
            end: nil,
            recurrence: .once(year: 2026, month: 11, day: 14)
        ),
        ScheduleItem(
            id: "new-year-2027",
            title: "元旦",
            calendarTitle: "元旦",
            start: t(0, 0),
            end: nil,
            recurrence: .range(year: 2027, startMonth: 1, startDay: 1, endMonth: 1, endDay: 1),
            isHoliday: true
        ),
        ScheduleItem(
            id: "chuxi-2027",
            title: "除夕",
            calendarTitle: "除夕",
            start: t(0, 0),
            end: nil,
            recurrence: .once(year: 2027, month: 2, day: 5),
            isHoliday: true
        ),
        ScheduleItem(
            id: "birthday-guojin-2026",
            title: "郭瑾生日",
            calendarTitle: "郭瑾",
            start: t(0, 0),
            end: nil,
            recurrence: .once(year: 2026, month: 11, day: 28),
            allDay: true
        ),
        ScheduleItem(
            id: "birthday-semmy-2027",
            title: "Semmy Semmy 生日",
            calendarTitle: "Semmy",
            start: t(0, 0),
            end: nil,
            recurrence: .once(year: 2027, month: 1, day: 12),
            allDay: true
        ),
        ScheduleItem(
            id: "birthday-chuchu-2027",
            title: "初初生日",
            calendarTitle: "初初",
            start: t(0, 0),
            end: nil,
            recurrence: .once(year: 2027, month: 1, day: 29),
            allDay: true
        ),
        ScheduleItem(
            id: "birthday-baobu-2027",
            title: "抱补生日",
            calendarTitle: "抱补",
            start: t(0, 0),
            end: nil,
            recurrence: .once(year: 2027, month: 3, day: 8),
            allDay: true
        ),
        ScheduleItem(
            id: "birthday-luoluo-2027",
            title: "洛洛生日",
            calendarTitle: "洛洛",
            start: t(0, 0),
            end: nil,
            recurrence: .once(year: 2027, month: 5, day: 11),
            allDay: true
        ),
        ScheduleItem(
            id: "makeup-work-2026",
            title: "上班",
            calendarTitle: "上班",
            start: t(0, 0),
            end: nil,
            recurrence: .dates([
                d(2026, 9, 20),
                d(2026, 10, 10),
            ]),
            isWorkday: true
        ),
    ]
}
