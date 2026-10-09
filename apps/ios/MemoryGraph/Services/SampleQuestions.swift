import Foundation

struct SampleQuestion: Identifiable, Hashable {
    /// 小朋友看到的短标题
    let title: String
    /// 真正发给 Desk 的问句（对齐 agent 已支持意图）
    let question: String
    /// SF Symbol
    let symbol: String

    var id: String { question }
}

enum SampleQuestions {
    /// 小朋友爱问的：去哪玩、骑车、动物园、画画、笑、几岁、出门
    static let all: [SampleQuestion] = [
        SampleQuestion(title: "我几岁啦", question: "面面几岁了", symbol: "gift.fill"),
        SampleQuestion(title: "最近去哪玩", question: "面面最近去哪了", symbol: "figure.walk"),
        SampleQuestion(title: "出去玩过啥", question: "最近出去玩了哪些", symbol: "sun.max.fill"),
        SampleQuestion(title: "国庆去哪玩", question: "去年国庆去哪里玩了？开心吗？见了哪些人？", symbol: "flag.fill"),
        SampleQuestion(title: "骑车照片", question: "面面骑车的照片", symbol: "figure.outdoor.cycle"),
        SampleQuestion(title: "轮滑照片", question: "有没有轮滑", symbol: "figure.skating"),
        SampleQuestion(title: "看我的画", question: "面面的画作", symbol: "paintpalette.fill"),
        SampleQuestion(title: "动物园", question: "面面去动物园是什么时候", symbol: "pawprint.fill"),
        SampleQuestion(title: "我笑的样子", question: "有没有笑", symbol: "face.smiling"),
        SampleQuestion(title: "住过哪些地方", question: "面面住过哪些地方", symbol: "house.fill"),
    ]
}
