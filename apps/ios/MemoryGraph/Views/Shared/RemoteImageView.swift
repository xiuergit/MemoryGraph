import SwiftUI

struct RemoteImageView: View {
    let url: URL?
    var contentMode: ContentMode = .fill

    var body: some View {
        Group {
            if let url {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .empty:
                        ZStack {
                            Color.secondary.opacity(0.12)
                            ProgressView()
                        }
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: contentMode)
                    case .failure:
                        placeholder(systemName: "photo")
                    @unknown default:
                        placeholder(systemName: "photo")
                    }
                }
            } else {
                placeholder(systemName: "photo")
            }
        }
    }

    private func placeholder(systemName: String) -> some View {
        ZStack {
            Color.secondary.opacity(0.12)
            Image(systemName: systemName)
                .font(.title2)
                .foregroundStyle(.secondary)
        }
    }
}
