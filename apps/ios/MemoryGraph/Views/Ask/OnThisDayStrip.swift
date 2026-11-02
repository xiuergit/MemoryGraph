import SwiftUI

/// 往年今天：按年一张回忆卡（一句主文 + 少量代表图）。
struct OnThisDayStrip: View {
    @EnvironmentObject private var api: DeskAPIClient

    let years: [OnThisDayYear]
    var cardSize: CGFloat = 128
    var onSelect: (PhotoItem) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            ForEach(years) { year in
                yearCard(year)
            }
        }
    }

    private func yearCard(_ year: OnThisDayYear) -> some View {
        let visible = year.photos.filter { !$0.sourcePath.isEmpty }
        return VStack(alignment: .leading, spacing: 8) {
            Text(year.titleLine)
                .font(.system(size: 18, weight: .bold, design: .rounded))
                .foregroundStyle(KidPalette.ink)
                .lineLimit(2)

            if !year.subline.isEmpty {
                Text(year.subline)
                    .font(.system(size: 13, weight: .medium, design: .rounded))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            if !year.note.isEmpty {
                Text(year.note)
                    .font(.system(size: 14, weight: .medium, design: .rounded))
                    .foregroundStyle(KidPalette.ink.opacity(0.75))
                    .lineLimit(2)
            }

            if !visible.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(visible) { photo in
                            Button {
                                onSelect(photo)
                            } label: {
                                RemoteImageView(url: api.previewURL(sourcePath: photo.sourcePath, size: 360))
                                    .frame(width: cardSize, height: cardSize)
                                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
