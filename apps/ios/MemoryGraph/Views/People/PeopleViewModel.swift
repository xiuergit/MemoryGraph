import Foundation

@MainActor
final class PeopleViewModel: ObservableObject {
    @Published var people: [PersonInfo] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    func load(using api: DeskAPIClient) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            people = try await api.fetchRegistry()
        } catch {
            people = []
            errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}

@MainActor
final class PersonPhotosViewModel: ObservableObject {
    @Published var photos: [PhotoItem] = []
    @Published var total = 0
    @Published var isLoading = false
    @Published var isLoadingMore = false
    @Published var errorMessage: String?

    private var page = 1
    private let pageSize = 40
    private(set) var personName: String = ""

    var canLoadMore: Bool {
        photos.count < total
    }

    func load(person: PersonInfo, api: DeskAPIClient) async {
        personName = person.displayName
        page = 1
        photos = []
        total = 0
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let response = try await api.fetchPhotos(
                person: person.displayName,
                page: 1,
                pageSize: pageSize
            )
            photos = response.items
            total = response.total
            page = 1
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    func loadMore(api: DeskAPIClient) async {
        guard canLoadMore, !isLoadingMore, !isLoading else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        let next = page + 1
        do {
            let response = try await api.fetchPhotos(
                person: personName,
                page: next,
                pageSize: pageSize
            )
            photos.append(contentsOf: response.items)
            total = response.total
            page = next
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}
