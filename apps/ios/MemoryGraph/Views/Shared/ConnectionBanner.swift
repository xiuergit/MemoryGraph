import SwiftUI

struct ConnectionBanner: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var api: DeskAPIClient
    @Binding var showSettings: Bool
    @Binding var selectedTab: RootTab

    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 12, height: 12)

                Text(statusText)
                    .font(settings.childFriendly
                          ? .system(size: 16, weight: .semibold, design: .rounded)
                          : .subheadline)
                    .foregroundStyle(KidPalette.ink.opacity(0.85))
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

            // 唯一导航：四个同一样式
            HStack(spacing: 8) {
                tabChip("问一问", tab: .ask)
                tabChip("看谁", tab: .people)
                tabChip("待上传", tab: .outbox)
                tabChip("故事", tab: .stories)
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .padding(.bottom, 10)
        .frame(maxWidth: .infinity)
        .background {
            Color.white
                .ignoresSafeArea(edges: .top)
        }
        .overlay(alignment: .bottom) {
            Divider()
        }
        .task {
            await api.checkHealth()
        }
    }

    private func tabChip(_ title: String, tab: RootTab) -> some View {
        let selected = selectedTab == tab
        return Button(title) {
            if tab == .outbox || tab == .stories {
                settings.parentMode = true
            }
            selectedTab = tab
        }
        .controlSize(.small)
        .lineLimit(1)
        .minimumScaleFactor(0.8)
        .frame(maxWidth: .infinity)
        .buttonStyle(.bordered)
        .tint(selected ? KidPalette.teal : .secondary)
        .fontWeight(selected ? .semibold : .regular)
    }
}

extension ConnectionBanner {
    fileprivate var statusColor: Color {
        switch api.isReachable {
        case true: return Color(red: 0.30, green: 0.75, blue: 0.40)
        case false: return Color.orange
        case nil: return .gray
        }
    }

    fileprivate var statusText: String {
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
