# 问答错题本

> **入口在 Vue**：Inspector →「问答」Tab → **错题本**（不要靠改本 md 打勾）。

状态落盘：`data/ask_checklist.json`（gitignore；跨机可拷）。  
实现：`hub/shared/ask_checklist.py` · Desk `GET/PATCH/POST/DELETE /api/ask/checklist*` · `web/src/components/MemoryAsk.vue`。

用法：打开错题本 → 点问句提问 → 左侧答完后点「好了 / 没好」。可筛选未测/没好，可添加自家问句。
