# W09 · Docker（MemoryGraph Desk）

**本周目标**：`memory_desk` + Vue 构建产物可 docker compose 启动；Ollama 仍宿主机。  
**预计**：6～8h

---

## Day 1 · Docker 基础（1h）

- [ ] Docker Desktop + `docker run hello-world`
- [ ] 理解 volume（挂载 `data/` 只读或整库）

---

## Day 2 · Dockerfile（2h）

- [ ] 仓库根或 `tools/memory_desk/Dockerfile`：
  - Python 依赖 `requirements.txt`
  - 复制 `hub/`、`tools/memory_desk/`、`schemas/`
  - **不**把 `data/photos/` 打进镜像；运行时 volume 挂载 `data/`
- [ ] `docker build` 成功

---

## Day 3 · compose（2h）

- [ ] `docker-compose.yml`：
  - service `desk`：uvicorn memory_desk
  - 环境变量：`OLLAMA_BASE_URL=http://host.docker.internal:11434`
  - volume：`./data:/app/data`
- [ ] 可选 service `web`：nginx 托管 `web/dist` 或 dev 仍本地

---

## Day 4 · 排错（1h）

- [ ] `docker compose logs` 查 Ollama 连不上
- [ ] 文档：`docs/ai-study/deploy-docker.md`（启动步骤、数据目录说明）

---

## Day 5 · 限制说明（1h）

- [ ] 笔记：InsightFace/torch 镜像体积大；家用可 **Desk 容器 + 本机 Ollama/photo2json**
- [ ] 面试句：「推理在宿主机，API 容器化，数据 volume 挂载」

---

## 本周完成 ✓

- [ ] compose up 后能 `/api/ask` 或 `/api/memory/list`
- [ ] deploy 文档可跟着做

**下一周** → [W10-作品集.md](./W10-作品集.md)
