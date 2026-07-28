# 人脸参考库

将每个家庭成员的参考照放入独立子目录，文件夹名即 `people.id`。

```
faces/
├── registry.json       # 可选：id → 中文名（可从 registry.example.json 复制）
├── index.json          # 自动生成，勿手改（python tools/face_enroll/main.py）
├── baby/               # 宝宝参考照 10～20 张，直接放此目录
│   ├── ref_01.jpg
│   └── ref_02.heic
├── mom/
└── dad/
```

每人一个文件夹即可。宝宝长得快，**关键是参考照要覆盖不同年龄段**（婴儿、1～2 岁、近照各几张），不是文件夹要分多细。

## 参考照要求

- 正脸、清晰、脸部占画面一定比例
- 尽量单人照；合照也可，会取最大的一张脸
- 支持 `.jpg` `.jpeg` `.png` `.heic` `.heif`
- 每人 10～20 张够用，不必把相册全塞进来

## registry.json 格式

```json
{
  "baby": {
    "name": "宝宝",
    "birth_date": "2020-09-04",
    "role": "child",
    "match_threshold": 0.55
  },
  "mom": {
    "name": "妈妈",
    "birth_date": "1991-10-20",
    "role": "parent",
    "match_threshold": 0.7
  }
}
```

可选字段 `match_threshold`：该成员的识别阈值（0～1）。未设置时使用 `.env` 里的 `FACE_MATCH_THRESHOLD`。宝宝等变化大的人可设低一些（如 0.55），成人可设高一些（如 0.70）减少误认。

`birth_date` 用于在 JSON 里自动计算 `people[].age_at_photo`（几岁几月几天、出生第几天）。

**常用 `role`：** `child` 孩子 · `parent` 家长 · `relative` 亲戚长辈 · `sibling` 兄弟姐妹 · `friend` 朋友 · `other` 其他

```bash
# 1. 复制并编辑显示名（可选）
cp registry.example.json registry.json

# 2. 把参考照放进 baby/ 等目录

# 3. 生成 index.json
python tools/face_enroll/main.py build

# 或 build 前自动补 registry 占位
python tools/face_enroll/main.py build --sync-registry
```

## 维护工具（推荐）

有参考照目录但忘了写 registry 时：

```bash
python tools/face_enroll/main.py sync-registry
# 编辑 registry.json 补充 name / role / birth_date
python tools/face_enroll/main.py build
```

从相册某张照片直接裁剪人脸入库（不必手动找文件）：

```bash
python tools/face_enroll/main.py from-photo \
  2021_2021年10月_IMG_4816 chuchu --name 初初 --role friend
```

**Vue Inspector（推荐）**：

- **人脸库 Tab**：编辑成员属性、按人设置识别阈值、删除参考照
- **详情页**：检测人脸 → 点击人脸框 →「加入人脸库」

需先启动 `python tools/memory_desk/main.py` 与 `cd web && npm run dev`。

发现相册里反复出现但未识别的人脸：

```bash
# 只扫「有脸但 people 为空」的照片（库中还没有的人，约 4000+ 张）
python tools/face_enroll/main.py cluster --needs-faces --limit 0 --auto

# 编辑 data/faces/registry.json：unk_001 → 中文名、role（可合并到已有 id）
python tools/face_enroll/main.py build
python tools/photo2json/main.py --backfill faces --needs-faces
python tools/memory_index/main.py sync

# 以后少量新人：交互式确认
python tools/face_enroll/main.py cluster --apply --limit 500
```

入库后重新识别照片：

```bash
python tools/photo2json/main.py --backfill faces
```

## 识别

注册后，运行 `python tools/photo2json/main.py` 会自动比对 `data/photos/` 中的照片，
将识别结果写入 JSON 的 `people` 字段。

全局默认阈值由 `.env` 的 `FACE_MATCH_THRESHOLD` 控制（当前常见为 `0.55`）。每人可在 `registry.json` 单独设置 `match_threshold` 覆盖全局值：

```bash
# .env
FACE_MATCH_THRESHOLD=0.55

# 改完 registry 或参考照后
python tools/face_enroll/main.py build
python tools/photo2json/main.py --backfill faces --refill --year 2026
```

## InsightFace 下载慢？

慢的一般不是 pip，而是**第一次运行时下载模型包**（从 GitHub 拉 zip）。

| 模型 | 大小（约） | 说明 |
|------|-----------|------|
| `buffalo_s` | ~160MB | 默认，家庭场景够用，下载快 |
| `buffalo_l` | ~330MB | 更准，更慢 |

在 `.env` 里配置：

```bash
INSIGHTFACE_MODEL=buffalo_s    # 或 buffalo_l
```

### 手动下载（推荐网络不好时用）

```bash
mkdir -p ~/.insightface/models
cd ~/.insightface/models

# 选一个（s 小，l 大）
curl -L -o buffalo_s.zip \
  https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip
unzip -o buffalo_s.zip && rm buffalo_s.zip
```

下完后直接跑 `python tools/face_enroll/main.py`，**不会重复下载**。

若 GitHub 很慢，可用手机热点、代理，或浏览器下载 zip 后放进 `~/.insightface/models/` 再解压。

### 临时跳过人脸识别

不装 insightface 也能跑 `photo2json`，只是 `people` 为空；场景分析仍走 Ollama。
