import SwiftUI
import UIKit

struct PhotoDetailView: View {
    @EnvironmentObject private var api: DeskAPIClient
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.dismiss) private var dismiss

    let photos: [PhotoItem]
    @State private var selection: PhotoItem.ID

    init(photos: [PhotoItem], initial: PhotoItem) {
        self.photos = photos
        _selection = State(initialValue: initial.id)
    }

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.black.opacity(0.92)
                .ignoresSafeArea()

            TabView(selection: $selection) {
                ForEach(photos) { photo in
                    detailPage(photo)
                        .tag(photo.id)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: photos.count > 1 ? .automatic : .never))

            VStack(alignment: .leading, spacing: 10) {
                Button {
                    dismiss()
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "chevron.backward")
                            .font(.system(size: 17, weight: .bold))
                        Text("返回")
                            .font(settings.childFriendly
                                  ? .system(size: 18, weight: .bold, design: .rounded)
                                  : .body.weight(.semibold))
                    }
                    .foregroundStyle(KidPalette.ink)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(
                        Capsule(style: .continuous)
                            .fill(Color.white.opacity(0.95))
                            .shadow(color: .black.opacity(0.25), radius: 8, y: 2)
                    )
                }
                .buttonStyle(.plain)
                .accessibilityLabel("返回")

                if let photo = current {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(photo.shortTime.isEmpty ? photo.photoId : photo.shortTime)
                            .font(settings.childFriendly ? .headline.weight(.bold) : .subheadline.weight(.semibold))
                        if !photo.location.isEmpty {
                            Text(photo.location)
                                .font(.caption)
                                .foregroundStyle(.white.opacity(0.75))
                        }
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 4)
                }
            }
            .padding(.leading, 16)
            .padding(.top, 12)
        }
        .toolbar(.hidden, for: .navigationBar)
    }

    private var current: PhotoItem? {
        photos.first { $0.id == selection }
    }

    private func detailPage(_ photo: PhotoItem) -> some View {
        VStack(spacing: 12) {
            Spacer(minLength: 56)
            ZoomableRemoteImage(url: api.previewURL(sourcePath: photo.sourcePath, size: 1024))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(.horizontal, 8)

            VStack(spacing: 4) {
                if !photo.scene.isEmpty {
                    Text(photo.scene)
                        .font(settings.childFriendly ? .title3 : .body)
                        .foregroundStyle(.white)
                        .multilineTextAlignment(.center)
                }
                if !photo.people.isEmpty {
                    Text(photo.people)
                        .font(.subheadline)
                        .foregroundStyle(.white.opacity(0.8))
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 24)
        }
    }
}

/// UIScrollView 捏合缩放：双指放大缩小，双击 1x↔2.5x。
private struct ZoomableRemoteImage: UIViewRepresentable {
    let url: URL?

    func makeUIView(context: Context) -> ZoomScrollView {
        let scroll = ZoomScrollView()
        scroll.load(url: url)
        return scroll
    }

    func updateUIView(_ uiView: ZoomScrollView, context: Context) {
        uiView.load(url: url)
    }
}

private final class ZoomScrollView: UIScrollView, UIScrollViewDelegate {
    private let imageView = UIImageView()
    private var loadedURL: URL?
    private var imageSize: CGSize = .zero
    private var fittedBounds: CGSize = .zero
    private var dataTask: URLSessionDataTask?

    override init(frame: CGRect) {
        super.init(frame: frame)
        delegate = self
        minimumZoomScale = 1
        maximumZoomScale = 5
        bouncesZoom = true
        showsHorizontalScrollIndicator = false
        showsVerticalScrollIndicator = false
        backgroundColor = .clear
        contentInsetAdjustmentBehavior = .never
        imageView.contentMode = .scaleAspectFit
        imageView.isUserInteractionEnabled = true
        addSubview(imageView)

        let doubleTap = UITapGestureRecognizer(target: self, action: #selector(handleDoubleTap(_:)))
        doubleTap.numberOfTapsRequired = 2
        addGestureRecognizer(doubleTap)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func load(url: URL?) {
        guard url != loadedURL else { return }
        dataTask?.cancel()
        loadedURL = url
        imageView.image = nil
        imageSize = .zero
        fittedBounds = .zero
        zoomScale = 1
        contentSize = .zero

        guard let url else { return }
        dataTask = URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let self, let data, let image = UIImage(data: data) else { return }
            DispatchQueue.main.async {
                guard self.loadedURL == url else { return }
                self.imageView.image = image
                self.imageSize = image.size
                self.fittedBounds = .zero
                self.relayoutImageIfNeeded(force: true)
            }
        }
        dataTask?.resume()
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        relayoutImageIfNeeded(force: false)
    }

    private func relayoutImageIfNeeded(force: Bool) {
        guard imageSize.width > 0, imageSize.height > 0, bounds.width > 0, bounds.height > 0 else { return }
        if !force, fittedBounds == bounds.size {
            centerImage()
            return
        }

        fittedBounds = bounds.size
        let fit = min(bounds.width / imageSize.width, bounds.height / imageSize.height)
        let width = imageSize.width * fit
        let height = imageSize.height * fit
        zoomScale = 1
        imageView.frame = CGRect(x: 0, y: 0, width: width, height: height)
        contentSize = CGSize(width: width, height: height)
        centerImage()
    }

    private func centerImage() {
        let offsetX = max((bounds.width - contentSize.width) * 0.5, 0)
        let offsetY = max((bounds.height - contentSize.height) * 0.5, 0)
        contentInset = UIEdgeInsets(top: offsetY, left: offsetX, bottom: offsetY, right: offsetX)
    }

    func viewForZooming(in scrollView: UIScrollView) -> UIView? {
        imageView
    }

    func scrollViewDidZoom(_ scrollView: UIScrollView) {
        centerImage()
    }

    @objc private func handleDoubleTap(_ gesture: UITapGestureRecognizer) {
        if zoomScale > 1.1 {
            setZoomScale(1, animated: true)
        } else {
            let point = gesture.location(in: imageView)
            let target: CGFloat = 2.5
            let size = CGSize(
                width: bounds.width / target,
                height: bounds.height / target
            )
            let origin = CGPoint(
                x: point.x - size.width / 2,
                y: point.y - size.height / 2
            )
            zoom(to: CGRect(origin: origin, size: size), animated: true)
        }
    }
}
