import SwiftUI

/// 小朋友用：点一下开始说，再说完点一下提问（不要按住）。
struct KidTalkMicButton: View {
    @ObservedObject var recognizer: SpeechRecognizer
    var isThinking: Bool
    var enabled: Bool
    var onAsk: (String) -> Void

    @State private var pulse = false

    var body: some View {
        VStack(spacing: 18) {
            Text(headline)
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundStyle(headlineColor)
                .multilineTextAlignment(.center)
                .animation(.easeInOut(duration: 0.2), value: phase)

            Button(action: handleTap) {
                ZStack {
                    Circle()
                        .fill(micFill)
                        .frame(width: 168, height: 168)
                        .shadow(color: micFill.opacity(0.45), radius: pulse && recognizer.isRecording ? 28 : 14, y: 8)
                        .scaleEffect(pulse && recognizer.isRecording ? 1.06 : 1.0)

                    if isThinking {
                        ProgressView()
                            .controlSize(.large)
                            .tint(.white)
                    } else {
                        Image(systemName: recognizer.isRecording ? "ear.fill" : "mic.fill")
                            .font(.system(size: 64, weight: .bold))
                            .foregroundStyle(.white)
                            .symbolEffect(.pulse, isActive: recognizer.isRecording)
                    }
                }
            }
            .buttonStyle(.plain)
            .disabled(!enabled || isThinking)
            .opacity(enabled ? 1 : 0.4)
            .accessibilityLabel(accessibilityText)

            if recognizer.isRecording {
                Text(recognizer.transcript.isEmpty ? "大声说吧…" : recognizer.transcript)
                    .font(.system(size: 24, weight: .semibold, design: .rounded))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.primary)
                    .padding(.horizontal, 20)
                    .frame(minHeight: 60)
                    .transition(.opacity.combined(with: .scale(scale: 0.96)))
            }
        }
        .onChange(of: recognizer.isRecording) { _, recording in
            if recording {
                withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) {
                    pulse = true
                }
            } else {
                withAnimation(.spring) {
                    pulse = false
                }
            }
        }
    }

    private enum Phase {
        case blocked
        case idle
        case listening
        case thinking
    }

    private var phase: Phase {
        if isThinking { return .thinking }
        if !enabled { return .blocked }
        if recognizer.isRecording { return .listening }
        return .idle
    }

    private var headline: String {
        switch phase {
        case .blocked:
            if recognizer.authStatus == .denied {
                return "让大人打开麦克风"
            }
            return "先让大人打开电脑"
        case .idle:
            return "点圆钮，开始说话"
        case .listening:
            return "说完再点一下"
        case .thinking:
            return "我想想…"
        }
    }

    private var headlineColor: Color {
        switch phase {
        case .listening: return Color(red: 0.92, green: 0.35, blue: 0.28)
        case .thinking: return Color(red: 0.20, green: 0.55, blue: 0.70)
        case .blocked: return .secondary
        case .idle: return Color(red: 0.12, green: 0.45, blue: 0.58)
        }
    }

    private var micFill: Color {
        switch phase {
        case .listening:
            return Color(red: 0.95, green: 0.40, blue: 0.30)
        case .thinking:
            return Color(red: 0.25, green: 0.60, blue: 0.72)
        default:
            return Color(red: 0.18, green: 0.62, blue: 0.72)
        }
    }

    private var accessibilityText: String {
        switch phase {
        case .blocked: return "暂时不能说话"
        case .idle: return "点一下开始说话"
        case .listening: return "点一下结束并提问"
        case .thinking: return "正在想答案"
        }
    }

    private func handleTap() {
        guard enabled, !isThinking else { return }
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()

        if recognizer.isRecording {
            let text = recognizer.stop()
            onAsk(text)
        } else {
            recognizer.start()
        }
    }
}
