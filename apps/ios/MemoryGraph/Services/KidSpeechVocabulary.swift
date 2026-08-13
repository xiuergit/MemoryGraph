import Foundation
import Speech

/// 小朋友语音提问用的领域词与近音纠错。
/// Apple 端侧识别常把「轮滑」听成「龙华」；用 contextualStrings 抬权重，再做轻量纠错。
enum KidSpeechVocabulary {
    /// 喂给 `SFSpeechAudioBufferRecognitionRequest.contextualStrings`（宜短、宜常用）。
    static let contextualPhrases: [String] = [
        // 人物
        "面面", "爸爸", "妈妈", "爷爷", "奶奶",
        // 活动 / 物体（近音易错）
        "轮滑", "滑轮", "旱冰", "自行车", "骑车", "滑板", "画画", "画作",
        "动物园", "游乐园", "游泳", "踢球", "积木", "乐高",
        // 常用问法
        "有没有轮滑", "轮滑的照片", "面面轮滑", "最近去哪了", "几岁了",
        "出去玩了哪些", "有没有笑", "骑车的照片",
    ]

    /// 已知近音误听 → 正确词。含地名后缀时不替换，避免真问「龙华」被改掉。
    private static let homophoneFixes: [(wrong: String, right: String)] = [
        ("龙华", "轮滑"),
        ("隆华", "轮滑"),
        ("聋话", "轮滑"),
        ("仑滑", "轮滑"),
        ("沦滑", "轮滑"),
    ]

    private static let placeKeepMarkers = ["区", "街道", "路", "镇", "县", "市", "地铁", "站"]

    static func preferredTranscript(from result: SFSpeechRecognitionResult) -> String {
        let candidates = result.transcriptions.map(\.formattedString)
        let bestRaw = pickBestCandidate(candidates)
        return correctHomophones(bestRaw)
    }

    static func correctHomophones(_ text: String) -> String {
        var out = text
        for pair in homophoneFixes {
            out = replaceHomophone(in: out, wrong: pair.wrong, right: pair.right)
        }
        return out
    }

    // MARK: - Private

    private static func pickBestCandidate(_ candidates: [String]) -> String {
        guard let first = candidates.first else { return "" }
        guard candidates.count > 1 else { return first }

        let scored = candidates.map { text -> (String, Int) in
            let score = contextualPhrases.reduce(0) { sum, phrase in
                sum + (text.contains(phrase) ? phrase.count : 0)
            }
            return (text, score)
        }
        let best = scored.max(by: { $0.1 < $1.1 })
        if let best, best.1 > 0 {
            return best.0
        }
        return first
    }

    private static func replaceHomophone(in text: String, wrong: String, right: String) -> String {
        guard text.contains(wrong) else { return text }

        var result = ""
        var rest = text[...]
        while let range = rest.range(of: wrong) {
            let after = rest[range.upperBound...]
            let keepAsPlace = placeKeepMarkers.contains { after.hasPrefix($0) }
            result += rest[..<range.lowerBound]
            result += keepAsPlace ? wrong : right
            rest = after
        }
        result += rest
        return result
    }
}
