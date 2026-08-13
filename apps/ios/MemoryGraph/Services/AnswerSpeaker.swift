import AVFoundation
import Foundation

/// 系统中文朗读答案。
@MainActor
final class AnswerSpeaker: NSObject, ObservableObject {
    @Published private(set) var isSpeaking = false

    private let synthesizer = AVSpeechSynthesizer()
    private let delegateBox = SynthesizerDelegate()

    override init() {
        super.init()
        synthesizer.delegate = delegateBox
        delegateBox.onSpeakingChange = { [weak self] speaking in
            Task { @MainActor in
                self?.isSpeaking = speaking
            }
        }
    }

    func speak(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        stop()

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
            try session.setActive(true)
        } catch {
            // 朗读失败不阻断问答
        }

        let utterance = AVSpeechUtterance(string: Self.prepareForSpeech(trimmed))
        utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
            ?? AVSpeechSynthesisVoice(language: "zh-Hans")
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.92
        utterance.pitchMultiplier = 1.05
        synthesizer.speak(utterance)
        isSpeaking = true
    }

    func stop() {
        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }
        isSpeaking = false
    }

    func toggle(_ text: String) {
        if isSpeaking {
            stop()
        } else {
            speak(text)
        }
    }

    /// 朗读专用：年份逐位读（2026 → 二零二六），避免「两千零二十六」。
    static func prepareForSpeech(_ text: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: #"(?:19|20)\d{2}"#) else {
            return text
        }
        let ns = text as NSString
        let matches = regex.matches(in: text, range: NSRange(location: 0, length: ns.length))
        var result = text
        for match in matches.reversed() {
            guard let range = Range(match.range, in: result) else { continue }
            let year = String(result[range])
            result.replaceSubrange(range, with: spellYearDigits(year))
        }
        return result
    }

    private static let digitSpeech: [Character: String] = [
        "0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
        "5": "五", "6": "六", "7": "七", "8": "八", "9": "九",
    ]

    private static func spellYearDigits(_ year: String) -> String {
        String(year.compactMap { digitSpeech[$0] }.joined())
    }
}

private final class SynthesizerDelegate: NSObject, AVSpeechSynthesizerDelegate {
    var onSpeakingChange: ((Bool) -> Void)?

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) {
        onSpeakingChange?(true)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        onSpeakingChange?(false)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        onSpeakingChange?(false)
    }
}
