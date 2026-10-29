import SwiftUI

struct AskView: View {
    @EnvironmentObject private var api: DeskAPIClient
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    @StateObject private var model = AskViewModel()
    @StateObject private var recognizer = SpeechRecognizer()
    @StateObject private var speaker = AnswerSpeaker()
    @State private var detailPhoto: PhotoItem?
    @State private var showGrownUpInput = false

    private let quickColors: [Color] = [
        Color(red: 0.98, green: 0.72, blue: 0.28), // 黄
        Color(red: 0.40, green: 0.78, blue: 0.55), // 绿
        Color(red: 0.95, green: 0.55, blue: 0.40), // 橙
        Color(red: 0.45, green: 0.70, blue: 0.92), // 蓝
        Color(red: 0.92, green: 0.62, blue: 0.78), // 粉
        Color(red: 0.55, green: 0.82, blue: 0.78), // 青绿
        Color(red: 0.85, green: 0.68, blue: 0.42), // 驼
        Color(red: 0.70, green: 0.75, blue: 0.95), // 浅蓝紫（很淡，避免整页紫风）
    ]

    var body: some View {
        NavigationStack {
            Group {
                if horizontalSizeClass == .regular {
                    ipadLayout
                } else {
                    phoneLayout
                }
            }
            .background(KidPalette.sky.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(item: $detailPhoto) { photo in
                PhotoDetailView(photos: model.displayPhotos, initial: photo)
            }
            .task {
                await recognizer.prepare()
                await model.loadDefaultPortraits(using: api, force: true)
            }
            .onChange(of: model.answerToken) { _, _ in
                guard settings.autoSpeakAnswer, !model.answer.isEmpty else { return }
                speaker.speak(model.answer)
            }
            .onDisappear {
                speaker.stop()
                if recognizer.isRecording {
                    recognizer.cancel()
                }
            }
        }
    }

    private var phoneLayout: some View {
        ScrollView {
            VStack(spacing: 28) {
                micSection
                quickAskSection
                answerSection
                photosSection
                grownUpSection
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
            .padding(.bottom, 28)
        }
        .scrollDismissesKeyboard(.interactively)
    }

    private var ipadLayout: some View {
        HStack(alignment: .top, spacing: 0) {
            ScrollView {
                VStack(spacing: 28) {
                    micSection
                    quickAskSection
                    answerSection
                    grownUpSection
                }
                .padding(24)
            }
            .frame(maxWidth: 480)
            .frame(maxHeight: .infinity)

            Divider()

            VStack(alignment: .leading, spacing: 0) {
                photosSection
                    .padding(24)
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background(Color.white.opacity(0.35))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var micSection: some View {
        VStack(spacing: 12) {
            KidTalkMicButton(
                recognizer: recognizer,
                isThinking: model.isLoading,
                enabled: !model.isLoading && api.isReachable != false
            ) { text in
                Task {
                    speaker.stop()
                    await model.submitVoice(text, api: api)
                }
            }

            if let speechErr = recognizer.errorMessage, !recognizer.isRecording, !model.isLoading {
                Text(kidFriendlySpeechError(speechErr))
                    .font(.system(size: 16, weight: .medium, design: .rounded))
                    .foregroundStyle(Color.orange)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 8)
    }

    private var quickAskSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("点一句话问问")
                .font(.system(size: 20, weight: .bold, design: .rounded))
                .foregroundStyle(KidPalette.ink)

            LazyVGrid(
                columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)],
                spacing: 12
            ) {
                ForEach(Array(SampleQuestions.all.enumerated()), id: \.element.id) { index, item in
                    Button {
                        speaker.stop()
                        if recognizer.isRecording {
                            recognizer.cancel()
                        }
                        model.useChip(item.question, api: api)
                    } label: {
                        VStack(spacing: 10) {
                            Image(systemName: item.symbol)
                                .font(.system(size: 28, weight: .bold))
                            Text(item.title)
                                .font(.system(size: 18, weight: .bold, design: .rounded))
                                .multilineTextAlignment(.center)
                                .minimumScaleFactor(0.8)
                                .lineLimit(2)
                        }
                        .foregroundStyle(KidPalette.ink)
                        .frame(maxWidth: .infinity, minHeight: 100)
                        .padding(12)
                        .background(
                            RoundedRectangle(cornerRadius: 22, style: .continuous)
                                .fill(quickColors[index % quickColors.count].opacity(0.85))
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(model.isLoading || recognizer.isRecording)
                }
            }
        }
    }

    @ViewBuilder
    private var answerSection: some View {
        if let err = model.errorMessage {
            Text(kidFriendlyAskError(err))
                .font(.system(size: 22, weight: .semibold, design: .rounded))
                .foregroundStyle(KidPalette.ink)
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .fill(Color.orange.opacity(0.2))
                )
        } else if !model.answer.isEmpty {
            VStack(alignment: .leading, spacing: 16) {
                Text("告诉你哦")
                    .font(.system(size: 18, weight: .bold, design: .rounded))
                    .foregroundStyle(KidPalette.teal)

                Text(model.answer)
                    .font(.system(size: 26, weight: .semibold, design: .rounded))
                    .foregroundStyle(KidPalette.ink)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if !model.followUps.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("还可以问")
                            .font(.system(size: 16, weight: .bold, design: .rounded))
                            .foregroundStyle(KidPalette.teal)
                        FlowFollowUpChips(chips: model.followUps) { chip in
                            speaker.stop()
                            if recognizer.isRecording {
                                recognizer.cancel()
                            }
                            model.useFollowUp(chip, api: api)
                        }
                        .disabled(model.isLoading || recognizer.isRecording)
                    }
                }

                Button {
                    speaker.toggle(model.answer)
                } label: {
                    Label(
                        speaker.isSpeaking ? "别说了" : "再听一遍",
                        systemImage: speaker.isSpeaking ? "stop.fill" : "speaker.wave.2.fill"
                    )
                    .font(.system(size: 20, weight: .bold, design: .rounded))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 16)
                }
                .buttonStyle(.borderedProminent)
                .tint(KidPalette.teal)
                .controlSize(.large)
            }
            .padding(20)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(Color.white.opacity(0.92))
                    .shadow(color: .black.opacity(0.06), radius: 10, y: 4)
            )
        }
    }

    @ViewBuilder
    private var photosSection: some View {
        let photos = model.displayPhotos
        if !photos.isEmpty || model.isLoadingPortraits {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Text(model.photosTitle)
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                        .foregroundStyle(KidPalette.ink)
                    if model.showingDefaultPortraits {
                        Text("每天一张")
                            .font(.system(size: 14, weight: .semibold, design: .rounded))
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                }

                if model.isLoadingPortraits && photos.isEmpty {
                    ProgressView("找照片…")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 40)
                } else {
                    PhotoStripTwoRow(photos: photos, cardSize: horizontalSizeClass == .regular ? 168 : 148) { photo in
                        speaker.stop()
                        detailPhoto = photo
                    }
                }
            }
        }
    }

    private var grownUpSection: some View {
        DisclosureGroup(isExpanded: $showGrownUpInput) {
            VStack(alignment: .leading, spacing: 12) {
                TextField("打字提问", text: $model.question, axis: .vertical)
                    .lineLimit(2 ... 4)
                    .textFieldStyle(.roundedBorder)
                    .font(.body)

                Button {
                    Task {
                        speaker.stop()
                        await model.submit(using: api)
                    }
                } label: {
                    Text("发送")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.isLoading || recognizer.isRecording)
            }
            .padding(.top, 8)
        } label: {
            Text("让大人打字")
                .font(.system(size: 15, weight: .semibold, design: .rounded))
                .foregroundStyle(.secondary)
        }
        .padding(.top, 8)
    }

    private func kidFriendlySpeechError(_ raw: String) -> String {
        if raw.contains("权限") || raw.contains("麦克风") {
            return "让大人打开麦克风权限哦"
        }
        return "现在说不了，再试一次，或点下面的句子"
    }

    private func kidFriendlyAskError(_ raw: String) -> String {
        if raw.contains("没听清") {
            return "没听清，再点圆钮说一次吧"
        }
        if raw.contains("连") || raw.contains("服务器") || raw.contains("电脑") || raw.contains("地址") {
            return "电脑好像还没准备好，叫大人看一下"
        }
        return "这次没问成，再试一次吧"
    }
}

enum KidPalette {
    static let sky = Color(red: 0.90, green: 0.96, blue: 0.98)
    static let teal = Color(red: 0.15, green: 0.55, blue: 0.62)
    static let ink = Color(red: 0.16, green: 0.22, blue: 0.28)
}

/// 简单横向换行芯片（继续问）
private struct FlowFollowUpChips: View {
    let chips: [String]
    let onTap: (String) -> Void

    var body: some View {
        FlexibleChipWrap(spacing: 8) {
            ForEach(chips, id: \.self) { chip in
                Button {
                    onTap(chip)
                } label: {
                    Text(chip)
                        .font(.system(size: 16, weight: .semibold, design: .rounded))
                        .foregroundStyle(KidPalette.ink)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(
                            Capsule(style: .continuous)
                                .fill(KidPalette.teal.opacity(0.18))
                        )
                }
                .buttonStyle(.plain)
            }
        }
    }
}

/// 轻量换行布局，避免依赖额外包。
private struct FlexibleChipWrap: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var totalHeight: CGFloat = 0
        var totalWidth: CGFloat = 0
        for sub in subviews {
            let size = sub.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                y += rowHeight + spacing
                totalHeight = y
                x = 0
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            totalWidth = max(totalWidth, x - spacing)
            totalHeight = max(totalHeight, y + rowHeight)
        }
        return CGSize(width: totalWidth, height: totalHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for sub in subviews {
            let size = sub.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX, x > bounds.minX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            sub.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}
