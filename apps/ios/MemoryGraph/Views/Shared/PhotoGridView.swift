import SwiftUI

struct PhotoGridView: View {
    let photos: [PhotoItem]
    var onSelect: (PhotoItem) -> Void

    private let columns = [
        GridItem(.adaptive(minimum: 110, maximum: 200), spacing: 10),
    ]

    var body: some View {
        LazyVGrid(columns: columns, spacing: 10) {
            ForEach(photos) { photo in
                Button {
                    onSelect(photo)
                } label: {
                    PhotoCell(photo: photo)
                }
                .buttonStyle(.plain)
            }
        }
    }
}

private struct PhotoCell: View {
    @EnvironmentObject private var api: DeskAPIClient
    let photo: PhotoItem

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            RemoteImageView(url: api.previewURL(sourcePath: photo.sourcePath, size: 280))
                .frame(minHeight: 110)
                .frame(maxWidth: .infinity)
                .clipped()
                .aspectRatio(1, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

            Text(photo.shortTime.isEmpty ? "—" : photo.shortTime)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.primary)
                .lineLimit(1)

            Text(photo.subtitle)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(photo.shortTime)，\(photo.subtitle)")
    }
}
