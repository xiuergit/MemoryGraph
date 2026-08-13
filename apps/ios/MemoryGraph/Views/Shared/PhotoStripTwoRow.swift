import SwiftUI

/// 两行向右滚动的大图条（小朋友逛照片）。
struct PhotoStripTwoRow: View {
    @EnvironmentObject private var api: DeskAPIClient

    let photos: [PhotoItem]
    var cardSize: CGFloat = 156
    var onSelect: (PhotoItem) -> Void

    private let rows = [
        GridItem(.fixed(200), spacing: 12),
        GridItem(.fixed(200), spacing: 12),
    ]

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            LazyHGrid(rows: rows, spacing: 12) {
                ForEach(photos) { photo in
                    Button {
                        onSelect(photo)
                    } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            RemoteImageView(url: api.previewURL(sourcePath: photo.sourcePath, size: 400))
                                .frame(width: cardSize, height: cardSize)
                                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))

                            Text(photo.shortTime.isEmpty ? "照片" : photo.shortTime)
                                .font(.system(size: 14, weight: .bold, design: .rounded))
                                .foregroundStyle(KidPalette.ink)
                                .lineLimit(1)
                            Text(photo.subtitle)
                                .font(.system(size: 12, weight: .medium, design: .rounded))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        .frame(width: cardSize, alignment: .leading)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.vertical, 4)
        }
    }
}
