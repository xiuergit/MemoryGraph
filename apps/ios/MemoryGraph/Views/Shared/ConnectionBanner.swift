import SwiftUI

struct ConnectionBanner: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var api: DeskAPIClient
    @Binding var showSettings: Bool

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(statusColor)
                .frame(width: 12, height: 12)

            Text(statusText)
                .font(settings.childFriendly
                      ? .system(size: 16, weight: .semibold, design: .rounded)
                      : .subheadline)
                .foregroundStyle(settings.childFriendly ? KidPalette.ink : .secondary)
                .lineLimit(2)

            Spacer(minLength: 8)

            if !settings.childFriendly {
                Button {
                    Task { await api.checkHealth() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("重新检测连接")
            }

            Button(settings.childFriendly ? "大人" : "设置") {
                showSettings = true
            }
            .buttonStyle(.bordered)
            .controlSize(settings.childFriendly ? .regular : .small)
            .font(settings.childFriendly ? .system(size: 16, weight: .bold, design: .rounded) : .body)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, settings.childFriendly ? 10 : 8)
        .background(settings.childFriendly ? Color.white.opacity(0.72) : Color.clear)
        .background(.ultraThinMaterial)
        .task {
            await api.checkHealth()
        }
    }

    private var statusColor: Color {
        switch api.isReachable {
        case true: return Color(red: 0.30, green: 0.75, blue: 0.40)
        case false: return Color.orange
        case nil: return .gray
        }
    }

    private var statusText: String {
        if settings.childFriendly {
            switch api.isReachable {
            case true: return "电脑准备好啦"
            case false: return "叫大人打开电脑"
            case nil: return "正在找电脑…"
            }
        }

        let endpoint = settings.displayEndpoint
        let loopbackHint = settings.host.trimmingCharacters(in: .whitespacesAndNewlines) == "127.0.0.1"
            ? " · 真机请改局域网 IP"
            : ""
        if api.isReachable == true {
            return "已连接 \(endpoint)\(loopbackHint)"
        }
        if let err = api.lastError, !err.isEmpty {
            return "未连上 · \(err)"
        }
        return "连接 \(endpoint)…"
    }
}
