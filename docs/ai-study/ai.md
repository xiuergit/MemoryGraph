# ai 学习开发领域

Runtime 如何承载Agent的执行过程
LLM CALL 一次模型 调用 到 agent Task

Agent Task
执行时间长 
可能调用多个系统
由任务状态 
有动态执行路径
可能发生等待，
可能分多轮推进

Agent Loop
Ahent Loop 的真正价值（允许根据实际观察发生变化）
初始计划 观测结果 状态变化 计划调整

Planner：决定下一步“做什么” 

Executor: 把计划真正推进下去

Session 这是哪一次会话或运行 Context： 当前这一步需要看到什么 Memmory：哪些信息以后值得保留 State：当前Task已经执行到了哪一步

