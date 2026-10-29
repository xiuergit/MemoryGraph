import SwiftUI

private enum SchedulePaper {
    static let page = Color(red: 0.97, green: 0.95, blue: 0.91)
    static let ink = Color(red: 0.17, green: 0.15, blue: 0.13)
    static let muted = Color(red: 0.45, green: 0.41, blue: 0.37)
    static let rule = Color(red: 0.84, green: 0.80, blue: 0.73)
    static let today = Color(red: 0.70, green: 0.27, blue: 0.22)
    static let card = Color(red: 0.992, green: 0.986, blue: 0.975)
}

struct ScheduleEditRequest: Identifiable {
    var itemId: String
    var day: Date
    var focusSeries: Bool
    var id: String { "\(itemId)-\(Calendar.dayStamp(day))-\(focusSeries)" }
}

struct DiaryEditRequest: Identifiable {
    var entryId: String?
    var day: Date
    var token = UUID().uuidString
    var id: String { entryId ?? token }
}

struct PersonAgendaView: View {
    let person: PersonInfo

    @EnvironmentObject private var store: ScheduleStore
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.scenePhase) private var scenePhase

    @State private var now = Date()
    @State private var editing: ScheduleEditRequest?
    @State private var diaryEditing: DiaryEditRequest?

    private var calendar: Calendar { .paper }
    private var engine: ScheduleEngine { store.engine(for: person.personId) }

    var body: some View {
        let laterGroups = Array(engine.groups(from: now, count: 8).dropFirst())
        let onceItems = engine.upcomingOnce(from: now)
        let weekdays = engine.weeklyOverview()

        ScrollView {
            LazyVStack(alignment: .leading, spacing: 16) {
                todaySection
                sectionHeader("接下来", subtitle: "后 7 天")
                ForEach(laterGroups) { group in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(calendar.paperDateLabel(group.day))
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(SchedulePaper.ink)
                        occurrenceList(group.occurrences, emphasized: false, empty: "无安排")
                        diaryNotes(on: group.day)
                    }
                }

                if !onceItems.isEmpty {
                    sectionHeader("近期单独", subtitle: "不每周重复")
                        .padding(.top, 12)
                    occurrenceList(onceItems, emphasized: true, empty: "")
                }

                sectionHeader("每周固定", subtitle: "改一项会改以后的每周")
                    .padding(.top, 12)
                ForEach(weekdays, id: \.weekday) { day in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(day.title)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(SchedulePaper.ink)
                        if day.occurrences.isEmpty {
                            Text("无")
                                .font(.subheadline)
                                .foregroundStyle(SchedulePaper.muted)
                        } else {
                            ForEach(day.occurrences) { item in
                                hitRow(time: item.timeLabel, title: item.title, emphasized: false, cancelled: false, note: nil) {
                                    editing = ScheduleEditRequest(itemId: item.id, day: now, focusSeries: true)
                                }
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)
            .padding(.bottom, 40)
        }
        .background(SchedulePaper.page.ignoresSafeArea())
        .toolbar {
            if settings.parentMode {
                ToolbarItem(placement: .primaryAction) {
                    Button("写日记") {
                        diaryEditing = DiaryEditRequest(day: now)
                    }
                }
            }
        }
        .onAppear { store.ensureSeeded(person) }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            let current = Date()
            if !calendar.isDate(now, inSameDayAs: current) {
                now = current
            }
        }
        .sheet(item: $editing) { request in
            NavigationStack {
                ScheduleEditorView(request: request)
            }
            .preferredColorScheme(.light)
        }
        .sheet(item: $diaryEditing) { request in
            NavigationStack {
                DiaryEditorView(personId: person.personId, request: request)
            }
            .preferredColorScheme(.light)
        }
    }

    private var todaySection: some View {
        let items = engine.groups(from: now, count: 1).first?.occurrences ?? []
        return VStack(alignment: .leading, spacing: 12) {
            sectionHeader("今天", subtitle: calendar.paperDateLabel(now))
            occurrenceList(items, emphasized: true, empty: "今天没有安排")
            diaryNotes(on: now)
        }
        .padding(.bottom, 12)
    }

    private func occurrenceList(_ items: [Occurrence], emphasized: Bool, empty: String) -> some View {
        VStack(spacing: 8) {
            if items.isEmpty {
                if !empty.isEmpty {
                    Text(empty)
                        .font(.body)
                        .foregroundStyle(SchedulePaper.muted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(14)
                        .background(SchedulePaper.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            } else {
                ForEach(items) { item in
                    hitRow(
                        time: item.timeLabel,
                        title: item.title,
                        emphasized: emphasized,
                        cancelled: item.cancelled,
                        note: item.adjusted ? "这天改过时间" : nil
                    ) {
                        editing = ScheduleEditRequest(itemId: item.item.id, day: item.day, focusSeries: false)
                    }
                }
            }
        }
    }

    private func diaryNotes(on day: Date) -> some View {
        DiaryNotes(
            entries: store.diaries(for: person.personId, on: day),
            canEdit: settings.parentMode
        ) { entry in
            diaryEditing = DiaryEditRequest(entryId: entry.id, day: day)
        }
    }

    private func hitRow(
        time: String,
        title: String,
        emphasized: Bool,
        cancelled: Bool,
        note: String?,
        action: @escaping () -> Void
    ) -> some View {
        let row = ScheduleHitRow(time: time, title: title, emphasized: emphasized, cancelled: cancelled, note: note)
        return Group {
            if settings.parentMode {
                Button(action: action) { row }
                    .buttonStyle(.plain)
            } else {
                row
            }
        }
    }
}

struct PersonMonthView: View {
    let person: PersonInfo

    @EnvironmentObject private var store: ScheduleStore
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.scenePhase) private var scenePhase

    @State private var now = Date()
    @State private var visibleMonth = Date()
    @State private var selectedDay = Date()
    @State private var editing: ScheduleEditRequest?
    @State private var diaryEditing: DiaryEditRequest?

    private var calendar: Calendar { .paper }
    private var engine: ScheduleEngine { store.engine(for: person.personId) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                monthHeader
                weekdayHeader
                monthGrid
                selectedDaySection
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)
            .padding(.bottom, 40)
        }
        .background(SchedulePaper.page.ignoresSafeArea())
        .toolbar {
            if settings.parentMode {
                ToolbarItem(placement: .primaryAction) {
                    Button("写日记") {
                        diaryEditing = DiaryEditRequest(day: selectedDay)
                    }
                }
            }
        }
        .onAppear { store.ensureSeeded(person) }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            let current = Date()
            guard !calendar.isDate(now, inSameDayAs: current) else { return }
            let wasToday = calendar.isDate(selectedDay, inSameDayAs: now)
            now = current
            if wasToday {
                visibleMonth = current
                selectedDay = current
            }
        }
        .sheet(item: $editing) { request in
            NavigationStack {
                ScheduleEditorView(request: request)
            }
            .preferredColorScheme(.light)
        }
        .sheet(item: $diaryEditing) { request in
            NavigationStack {
                DiaryEditorView(personId: person.personId, request: request)
            }
            .preferredColorScheme(.light)
        }
    }

    private var monthHeader: some View {
        HStack {
            Button { shiftMonth(-1) } label: {
                Image(systemName: "chevron.left")
                    .font(.body.weight(.semibold))
                    .frame(width: 36, height: 36)
            }
            Spacer()
            VStack(spacing: 2) {
                Text(calendar.paperMonthLabel(visibleMonth))
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(SchedulePaper.ink)
                Button("回到今天") { jumpToToday() }
                    .font(.caption.weight(.semibold))
                    .disabled(calendar.isDate(selectedDay, inSameDayAs: now)
                              && calendar.isDate(visibleMonth, equalTo: now, toGranularity: .month))
            }
            Spacer()
            Button { shiftMonth(1) } label: {
                Image(systemName: "chevron.right")
                    .font(.body.weight(.semibold))
                    .frame(width: 36, height: 36)
            }
        }
        .foregroundStyle(SchedulePaper.ink)
    }

    private var weekdayHeader: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 0), count: 7), spacing: 0) {
            ForEach(["一", "二", "三", "四", "五", "六", "日"], id: \.self) { name in
                Text(name)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(SchedulePaper.muted)
                    .frame(maxWidth: .infinity)
                    .padding(.bottom, 8)
            }
        }
    }

    private var monthGrid: some View {
        let cells = calendar.monthGrid(for: visibleMonth)
        return LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 7), spacing: 6) {
            ForEach(Array(cells.enumerated()), id: \.offset) { _, day in
                let classes = day.map { engine.classOccurrences(on: $0) } ?? []
                ScheduleDayCell(
                    day: day,
                    isToday: day.map { calendar.isDate($0, inSameDayAs: now) } ?? false,
                    isSelected: day.map { calendar.isDate($0, inSameDayAs: selectedDay) } ?? false,
                    classes: classes,
                    hasDiary: day.map { store.hasDiary(for: person.personId, on: $0) } ?? false
                ) {
                    if let day { selectedDay = day }
                }
            }
        }
        .padding(4)
        .background(SchedulePaper.page, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private var selectedDaySection: some View {
        let items = engine.occurrences(on: selectedDay)
        let isToday = calendar.isDate(selectedDay, inSameDayAs: now)
        return VStack(alignment: .leading, spacing: 12) {
            sectionHeader(
                isToday ? "这一天" : calendar.paperDateLabel(selectedDay),
                subtitle: isToday ? calendar.paperDateLabel(selectedDay) : "含幼儿园。格子里只标课。"
            )
            if items.isEmpty {
                Text("这天没有安排")
                    .font(.body)
                    .foregroundStyle(SchedulePaper.muted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
                    .background(SchedulePaper.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            } else {
                VStack(spacing: 8) {
                    ForEach(items) { item in
                        let row = ScheduleHitRow(
                            time: item.timeLabel,
                            title: item.title,
                            emphasized: isToday,
                            cancelled: item.cancelled,
                            note: item.adjusted ? "这天改过时间" : nil
                        )
                        if settings.parentMode {
                            Button {
                                editing = ScheduleEditRequest(itemId: item.item.id, day: item.day, focusSeries: false)
                            } label: { row }
                            .buttonStyle(.plain)
                        } else {
                            row
                        }
                    }
                }
            }
            DiaryNotes(
                entries: store.diaries(for: person.personId, on: selectedDay),
                canEdit: settings.parentMode
            ) { entry in
                diaryEditing = DiaryEditRequest(entryId: entry.id, day: selectedDay)
            }
        }
    }

    private func shiftMonth(_ value: Int) {
        guard let next = calendar.date(byAdding: .month, value: value, to: calendar.startOfMonth(for: visibleMonth)) else {
            return
        }
        visibleMonth = next
        if calendar.isDate(next, equalTo: now, toGranularity: .month) {
            selectedDay = now
        } else {
            selectedDay = calendar.startOfMonth(for: next)
        }
    }

    private func jumpToToday() {
        now = Date()
        visibleMonth = now
        selectedDay = now
    }
}

private struct DiaryNotes: View {
    var entries: [DiaryEntry]
    var canEdit: Bool
    var onEdit: (DiaryEntry) -> Void

    var body: some View {
        if !entries.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("日记")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(SchedulePaper.muted)
                ForEach(entries) { entry in
                    let card = Text(entry.body)
                        .font(.body)
                        .foregroundStyle(SchedulePaper.ink)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(14)
                        .background(SchedulePaper.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    if canEdit {
                        Button { onEdit(entry) } label: { card }
                            .buttonStyle(.plain)
                    } else {
                        card
                    }
                }
            }
        }
    }
}

private struct DiaryEditorView: View {
    var personId: String
    var request: DiaryEditRequest

    @EnvironmentObject private var store: ScheduleStore
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""

    var body: some View {
        Form {
            Section {
                TextField("今天的事…", text: $text, axis: .vertical)
                    .lineLimit(6 ... 16)
            } footer: {
                Text("可以写不上课的原因、今天和谁玩了、特别的事。空着保存会删掉这篇。")
            }
        }
        .navigationTitle(Calendar.paper.paperDateLabel(request.day))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("取消") { dismiss() }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("保存") {
                    store.saveDiary(
                        personId: personId,
                        day: request.day,
                        entryId: request.entryId,
                        body: text
                    )
                    dismiss()
                }
            }
        }
        .onAppear {
            if let entryId = request.entryId,
               let entry = store.diaries.first(where: { $0.id == entryId }) {
                text = entry.body
            }
        }
    }
}

private struct ScheduleHitRow: View {
    var time: String
    var title: String
    var emphasized: Bool
    var cancelled: Bool
    var note: String?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            Text(time)
                .font(.body.monospacedDigit())
                .foregroundStyle(cancelled ? SchedulePaper.muted : (emphasized ? SchedulePaper.today : SchedulePaper.muted))
                .frame(minWidth: 92, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(emphasized ? .body.weight(.semibold) : .body)
                    .foregroundStyle(cancelled ? SchedulePaper.muted : SchedulePaper.ink)
                    .strikethrough(cancelled)
                if let note, !note.isEmpty {
                    Text(note)
                        .font(.caption)
                        .foregroundStyle(SchedulePaper.muted)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(SchedulePaper.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

private struct ScheduleDayCell: View {
    var day: Date?
    var isToday: Bool
    var isSelected: Bool
    var classes: [Occurrence]
    var hasDiary: Bool = false
    var onSelect: () -> Void

    private var number: String {
        guard let day else { return "" }
        return "\(Calendar.paper.component(.day, from: day))"
    }

    var body: some View {
        Button(action: onSelect) {
            VStack(alignment: .leading, spacing: 2) {
                Text(number)
                    .font(.caption.weight(isSelected || isToday ? .semibold : .regular))
                    .foregroundStyle(numberColor)
                    .frame(maxWidth: .infinity)
                VStack(alignment: .leading, spacing: 1) {
                    ForEach(classes.prefix(4)) { item in
                        Text(item.calendarTitle)
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(classColor(item))
                            .lineLimit(1)
                            .minimumScaleFactor(0.65)
                    }
                }
                .frame(maxWidth: .infinity, minHeight: 42, alignment: .topLeading)
                if hasDiary {
                    Circle()
                        .fill(isSelected ? Color.white : SchedulePaper.today)
                        .frame(width: 5, height: 5)
                        .frame(maxWidth: .infinity)
                }
            }
            .padding(.horizontal, 3)
            .padding(.vertical, 5)
            .frame(maxWidth: .infinity, minHeight: 76, alignment: .top)
            .background {
                if day != nil {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(cellFill)
                }
            }
            .overlay {
                if day != nil && !isSelected {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(isToday ? SchedulePaper.today : SchedulePaper.rule, lineWidth: isToday ? 1.5 : 1)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(day == nil)
        .opacity(day == nil ? 0 : 1)
    }

    private var numberColor: Color {
        if isSelected { return .white }
        if isToday { return SchedulePaper.today }
        return SchedulePaper.ink
    }

    private var cellFill: Color {
        if isSelected { return SchedulePaper.today }
        return SchedulePaper.card
    }

    private func classColor(_ item: Occurrence) -> Color {
        if isSelected { return .white.opacity(0.95) }
        if item.item.isHoliday || item.marksEnd { return SchedulePaper.today }
        if case .once = item.item.recurrence { return SchedulePaper.today }
        return SchedulePaper.ink.opacity(0.82)
    }
}

private func sectionHeader(_ title: String, subtitle: String) -> some View {
    VStack(alignment: .leading, spacing: 4) {
        Text(title)
            .font(.title2.weight(.semibold))
            .foregroundStyle(SchedulePaper.ink)
        Text(subtitle)
            .font(.subheadline)
            .foregroundStyle(SchedulePaper.muted)
        Rectangle()
            .fill(SchedulePaper.rule)
            .frame(height: 1)
            .padding(.top, 4)
    }
}

private enum SeriesKind: String, CaseIterable, Identifiable {
    case weekly = "每周"
    case dates = "指定日期"
    case once = "只此一天"
    case range = "一段日期"
    var id: String { rawValue }
}

struct ScheduleEditorView: View {
    let request: ScheduleEditRequest

    @EnvironmentObject private var store: ScheduleStore
    @Environment(\.dismiss) private var dismiss

    @State private var focusSeries: Bool
    @State private var draft: ScheduleItem
    @State private var cancelled: Bool
    @State private var dayStart: Date
    @State private var dayEnd: Date
    @State private var hasEnd: Bool
    @State private var kind: SeriesKind
    @State private var confirmDelete = false
    @State private var pendingDate = Date()

    init(request: ScheduleEditRequest) {
        self.request = request
        _focusSeries = State(initialValue: request.focusSeries)
        let calendar = Calendar.paper
        let fallback = ScheduleItem(
            id: request.itemId,
            title: "",
            calendarTitle: "",
            start: t(15, 0),
            end: t(16, 0),
            recurrence: .once(
                year: calendar.component(.year, from: request.day),
                month: calendar.component(.month, from: request.day),
                day: calendar.component(.day, from: request.day)
            )
        )
        _draft = State(initialValue: fallback)
        _cancelled = State(initialValue: false)
        _dayStart = State(initialValue: request.day)
        _dayEnd = State(initialValue: request.day)
        _hasEnd = State(initialValue: true)
        _kind = State(initialValue: .once)
        _pendingDate = State(initialValue: request.day)
    }

    var body: some View {
        Form {
            Picker("改哪里", selection: $focusSeries) {
                Text("只改这一天").tag(false)
                Text("改这项以后").tag(true)
            }
            .pickerStyle(.segmented)
            .listRowBackground(Color.clear)

            if focusSeries {
                seriesForm
            } else {
                dayForm
            }
        }
        .navigationTitle(focusSeries ? "这项安排" : Calendar.paper.paperDateLabel(request.day))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("取消") { dismiss() }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("保存") { save() }
                    .disabled(draft.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && focusSeries)
            }
        }
        .onAppear(perform: load)
        .confirmationDialog("删除这项安排？", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("删除", role: .destructive) {
                store.remove(itemId: draft.id)
                dismiss()
            }
            Button("取消", role: .cancel) {}
        }
    }

    private var dayForm: some View {
        Group {
            Section {
                Toggle("这天不上", isOn: $cancelled)
                if !cancelled && !draft.allDay && !draft.isHoliday {
                    DatePicker("开始", selection: $dayStart, displayedComponents: .hourAndMinute)
                    Toggle("有结束时间", isOn: $hasEnd)
                    if hasEnd {
                        DatePicker("结束", selection: $dayEnd, displayedComponents: .hourAndMinute)
                    }
                }
            } footer: {
                Text("只动这一天。每周几、其他日期不变。")
            }
        }
    }

    @ViewBuilder
    private var seriesForm: some View {
        Section("名称") {
            TextField("标题", text: $draft.title)
            TextField("月历上的短名", text: $draft.calendarTitle)
        }
        Section("时间") {
            Toggle("放假", isOn: $draft.isHoliday)
            Toggle("调休上班", isOn: $draft.isWorkday)
            Toggle("全天", isOn: $draft.allDay)
            if !draft.allDay && !draft.isHoliday {
                DatePicker("开始", selection: seriesStart, displayedComponents: .hourAndMinute)
                Toggle("有结束时间", isOn: seriesHasEnd)
                if draft.end != nil {
                    DatePicker("结束", selection: seriesEnd, displayedComponents: .hourAndMinute)
                }
            }
        }
        Section("重复") {
            Picker("方式", selection: $kind) {
                ForEach(SeriesKind.allCases) { item in
                    Text(item.rawValue).tag(item)
                }
            }
            .onChange(of: kind) { _, newKind in
                applyKind(newKind)
            }
            recurrenceFields
        }
        if !draft.skipDates.isEmpty || !draft.overrides.isEmpty {
            Section("已经单独改过的日子") {
                ForEach(draft.skipDates, id: \.self) { day in
                    Button("恢复 \(day.month)月\(day.day)日（这天不上）") {
                        draft.skipDates.removeAll { $0 == day }
                    }
                }
                ForEach(draft.overrides, id: \.self) { change in
                    Button("恢复 \(change.month)月\(change.day)日的时间") {
                        draft.overrides.removeAll { $0 == change }
                    }
                }
            }
        }
        Section {
            Button("删除这项", role: .destructive) { confirmDelete = true }
        }
    }

    @ViewBuilder
    private var recurrenceFields: some View {
        switch draft.recurrence {
        case .weekly(let weekdays):
            weekdayToggles(weekdays)
        case .once:
            DatePicker("日期", selection: onceDate, displayedComponents: .date)
        case .dates(let dates):
            ForEach(dates, id: \.self) { day in
                HStack {
                    Text("\(day.year)年\(day.month)月\(day.day)日")
                    Spacer()
                    Button("去掉") { removeDate(day) }
                        .font(.caption)
                }
            }
            DatePicker("加上一天", selection: $pendingDate, displayedComponents: .date)
            Button("加到列表") { addPendingDate() }
            Toggle("最后一天标结束", isOn: $draft.marksEndOnLastDate)
        case .range:
            DatePicker("开始", selection: rangeStart, displayedComponents: .date)
            DatePicker("结束", selection: rangeEnd, displayedComponents: .date)
        }
    }

    private func weekdayToggles(_ selected: [Int]) -> some View {
        let names = [2: "一", 3: "二", 4: "三", 5: "四", 6: "五", 7: "六", 1: "日"]
        return HStack {
            ForEach(Calendar.paperWeekOrder, id: \.self) { weekday in
                let on = selected.contains(weekday)
                Button(names[weekday] ?? "") {
                    toggleWeekday(weekday)
                }
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
                .background(on ? SchedulePaper.today.opacity(0.18) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private var seriesStart: Binding<Date> {
        Binding(
            get: { draft.start.date(on: request.day) },
            set: { draft.start = TimeOfDay(date: $0) }
        )
    }

    private var seriesEnd: Binding<Date> {
        Binding(
            get: { (draft.end ?? draft.start).date(on: request.day) },
            set: { draft.end = TimeOfDay(date: $0) }
        )
    }

    private var seriesHasEnd: Binding<Bool> {
        Binding(
            get: { draft.end != nil },
            set: { on in
                draft.end = on ? (draft.end ?? TimeOfDay(hour: min(draft.start.hour + 1, 23), minute: draft.start.minute)) : nil
            }
        )
    }

    private var onceDate: Binding<Date> {
        Binding(
            get: {
                if case .once(let year, let month, let day) = draft.recurrence {
                    return Calendar.paper.paperDate(year: year, month: month, day: day) ?? request.day
                }
                return request.day
            },
            set: { date in
                let calendar = Calendar.paper
                draft.recurrence = .once(
                    year: calendar.component(.year, from: date),
                    month: calendar.component(.month, from: date),
                    day: calendar.component(.day, from: date)
                )
            }
        )
    }

    private var rangeStart: Binding<Date> {
        Binding(
            get: { rangeDate(start: true) },
            set: { date in setRange(start: date, end: nil) }
        )
    }

    private var rangeEnd: Binding<Date> {
        Binding(
            get: { rangeDate(start: false) },
            set: { date in setRange(start: nil, end: date) }
        )
    }

    private func load() {
        guard let item = store.items.first(where: { $0.id == request.itemId }) else { return }
        draft = item
        kind = SeriesKind(item.recurrence)
        let calendar = Calendar.paper
        let year = calendar.component(.year, from: request.day)
        let month = calendar.component(.month, from: request.day)
        let day = calendar.component(.day, from: request.day)
        cancelled = item.isCancelled(year: year, month: month, day: day)
        let start = item.override(year: year, month: month, day: day)?.start ?? item.start
        let end = item.override(year: year, month: month, day: day)?.end ?? item.end
        dayStart = start.date(on: request.day)
        hasEnd = end != nil
        dayEnd = (end ?? start).date(on: request.day)
    }

    private func save() {
        if focusSeries {
            let title = draft.title.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !title.isEmpty else { return }
            draft.title = title
            if draft.calendarTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                draft.calendarTitle = title
            }
            store.replace(draft)
        } else {
            store.applyDayChange(
                itemId: request.itemId,
                day: request.day,
                cancelled: cancelled,
                start: TimeOfDay(date: dayStart),
                end: hasEnd ? TimeOfDay(date: dayEnd) : nil
            )
        }
        dismiss()
    }

    private func applyKind(_ newKind: SeriesKind) {
        if SeriesKind(draft.recurrence) == newKind { return }
        let calendar = Calendar.paper
        let year = calendar.component(.year, from: request.day)
        let month = calendar.component(.month, from: request.day)
        let day = calendar.component(.day, from: request.day)
        let weekday = calendar.component(.weekday, from: request.day)
        switch newKind {
        case .weekly:
            draft.recurrence = .weekly(weekdays: [weekday])
        case .dates:
            draft.recurrence = .dates([CalendarDay(year: year, month: month, day: day)])
        case .once:
            draft.recurrence = .once(year: year, month: month, day: day)
        case .range:
            draft.recurrence = .range(year: year, startMonth: month, startDay: day, endMonth: month, endDay: day)
        }
    }

    private func toggleWeekday(_ weekday: Int) {
        guard case .weekly(var days) = draft.recurrence else { return }
        if days.contains(weekday) {
            days.removeAll { $0 == weekday }
        } else {
            days.append(weekday)
        }
        let order = Calendar.paperWeekOrder
        days.sort { lhs, rhs in
            (order.firstIndex(of: lhs) ?? 0) < (order.firstIndex(of: rhs) ?? 0)
        }
        draft.recurrence = .weekly(weekdays: days)
    }

    private func addPendingDate() {
        guard case .dates(var dates) = draft.recurrence else { return }
        let calendar = Calendar.paper
        let day = CalendarDay(
            year: calendar.component(.year, from: pendingDate),
            month: calendar.component(.month, from: pendingDate),
            day: calendar.component(.day, from: pendingDate)
        )
        if !dates.contains(day) {
            dates.append(day)
        }
        dates.sort { ($0.year, $0.month, $0.day) < ($1.year, $1.month, $1.day) }
        draft.recurrence = .dates(dates)
    }

    private func removeDate(_ day: CalendarDay) {
        guard case .dates(var dates) = draft.recurrence else { return }
        dates.removeAll { $0 == day }
        draft.recurrence = .dates(dates)
    }

    private func rangeDate(start: Bool) -> Date {
        guard case .range(let year, let startMonth, let startDay, let endMonth, let endDay) = draft.recurrence else {
            return request.day
        }
        if start {
            return Calendar.paper.paperDate(year: year, month: startMonth, day: startDay) ?? request.day
        }
        return Calendar.paper.paperDate(year: year, month: endMonth, day: endDay) ?? request.day
    }

    private func setRange(start: Date?, end: Date?) {
        guard case .range(let year, let startMonth, let startDay, let endMonth, let endDay) = draft.recurrence else { return }
        let calendar = Calendar.paper
        var sy = year
        var sm = startMonth
        var sd = startDay
        var em = endMonth
        var ed = endDay
        if let start {
            sy = calendar.component(.year, from: start)
            sm = calendar.component(.month, from: start)
            sd = calendar.component(.day, from: start)
        }
        if let end {
            em = calendar.component(.month, from: end)
            ed = calendar.component(.day, from: end)
            if calendar.component(.year, from: end) != sy {
                sy = calendar.component(.year, from: end)
            }
        }
        if sm * 100 + sd > em * 100 + ed {
            swap(&sm, &em)
            swap(&sd, &ed)
        }
        draft.recurrence = .range(year: sy, startMonth: sm, startDay: sd, endMonth: em, endDay: ed)
    }
}

private extension SeriesKind {
    init(_ recurrence: ScheduleRecurrence) {
        switch recurrence {
        case .weekly: self = .weekly
        case .dates: self = .dates
        case .once: self = .once
        case .range: self = .range
        }
    }
}

private extension TimeOfDay {
    init(date: Date, calendar: Calendar = .paper) {
        self.init(
            hour: calendar.component(.hour, from: date),
            minute: calendar.component(.minute, from: date)
        )
    }

    func date(on day: Date, calendar: Calendar = .paper) -> Date {
        calendar.date(bySettingHour: hour, minute: minute, second: 0, of: day) ?? day
    }
}
