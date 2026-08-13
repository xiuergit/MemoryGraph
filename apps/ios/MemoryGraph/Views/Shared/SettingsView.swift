import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var api: DeskAPIClient
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Form {
            Section {
                TextField("Mac 地址", text: $settings.host)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                TextField("端口", text: $settings.port)
                    .keyboardType(.numberPad)

                Button("填模拟器常用地址 127.0.0.1") {
                    settings.host = "127.0.0.1"
                }
            } header: {
                Text("家里的 Mac（Memory Desk）")
            } footer: {
                Text(
                    """
                    · 模拟器：可用 127.0.0.1（就是你现在看到的）。
                    · 真机 / 家里 iPad：必须填 Mac 的局域网 IP（如 192.168.x.x），不能用 127.0.0.1——那是设备自己。
                    · Mac 先跑：python tools/memory_desk/main.py --host 0.0.0.0 --auto-port
                    · 查 Mac IP：系统设置 → 网络，或终端执行 ipconfig getifaddr en0
                    · 手机与 Mac 同一 Wi‑Fi；默认端口 8766。
                    """
                )
            }

            Section {
                Toggle("儿童友好字号", isOn: $settings.childFriendly)
                Toggle("自动朗读答案", isOn: $settings.autoSpeakAnswer)
            } footer: {
                Text("语音识别和朗读都在本机完成，不会把声音传到网上。")
            }

            Section {
                Button("检测连接") {
                    Task {
                        await api.checkHealth()
                    }
                }
                if let reachable = api.isReachable {
                    Label(
                        reachable ? "可以连上" : "连不上",
                        systemImage: reachable ? "checkmark.circle.fill" : "exclamationmark.triangle.fill"
                    )
                    .foregroundStyle(reachable ? .green : .orange)
                }
                if let err = api.lastError, api.isReachable != true {
                    Text(err)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle("设置")
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("完成") {
                    Task {
                        await api.checkHealth()
                        dismiss()
                    }
                }
            }
        }
    }
}
