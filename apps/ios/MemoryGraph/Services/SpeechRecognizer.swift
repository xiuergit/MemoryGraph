import AVFoundation
import Foundation
import Speech

/// 设备端中文语音识别（不上传第三方）。
@MainActor
final class SpeechRecognizer: ObservableObject {
    @Published private(set) var transcript: String = ""
    @Published private(set) var isRecording = false
    @Published private(set) var authStatus: AuthStatus = .unknown
    @Published var errorMessage: String?

    enum AuthStatus {
        case unknown
        case authorized
        case denied
        case unavailable
    }

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    var isUsable: Bool {
        authStatus == .authorized && (recognizer?.isAvailable ?? false)
    }

    func prepare() async {
        guard let recognizer, recognizer.isAvailable else {
            authStatus = .unavailable
            return
        }

        let speechOK = await requestSpeechAuth()
        let micOK = await requestMicAuth()
        if speechOK && micOK {
            authStatus = .authorized
        } else {
            authStatus = .denied
            errorMessage = "需要麦克风和语音识别权限，才能按住说话。"
        }
    }

    func start() {
        errorMessage = nil
        guard authStatus == .authorized || authStatus == .unknown else { return }

        Task {
            if authStatus != .authorized {
                await prepare()
                guard authStatus == .authorized else { return }
            }
            do {
                try beginRecording()
            } catch {
                errorMessage = error.localizedDescription
                isRecording = false
            }
        }
    }

    func stop() -> String {
        let text = KidSpeechVocabulary.correctHomophones(
            transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        tearDownEngine()
        isRecording = false
        return text
    }

    func cancel() {
        tearDownEngine()
        transcript = ""
        isRecording = false
    }

    // MARK: - Private

    private func requestSpeechAuth() async -> Bool {
        await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { status in
                cont.resume(returning: status == .authorized)
            }
        }
    }

    private func requestMicAuth() async -> Bool {
        await withCheckedContinuation { cont in
            AVAudioApplication.requestRecordPermission { ok in
                cont.resume(returning: ok)
            }
        }
    }

    private func beginRecording() throws {
        tearDownEngine()
        transcript = ""

        guard let recognizer, recognizer.isAvailable else {
            throw SpeechError.unavailable
        }

        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
        try session.setActive(true, options: .notifyOthersOnDeactivation)

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.taskHint = .search
        request.contextualStrings = KidSpeechVocabulary.contextualPhrases
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        self.request = request

        let input = audioEngine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            self?.request?.append(buffer)
        }

        audioEngine.prepare()
        try audioEngine.start()
        isRecording = true

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                guard let self else { return }
                if let result {
                    // 优先选含领域词的候选项，再做近音纠错（如 龙华→轮滑）
                    self.transcript = KidSpeechVocabulary.preferredTranscript(from: result)
                }
                if error != nil || (result?.isFinal ?? false) {
                    // 点第二次 stop() 会 tearDown；识别自然结束时只停引擎
                    if self.isRecording, result?.isFinal == true {
                        self.tearDownEngine()
                        self.isRecording = false
                    }
                }
            }
        }
    }

    private func tearDownEngine() {
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
    }
}

enum SpeechError: LocalizedError {
    case unavailable

    var errorDescription: String? {
        switch self {
        case .unavailable:
            return "这台设备暂时不能语音识别"
        }
    }
}
