# 人脸参考库

将每个家庭成员的参考照放入独立子目录，文件夹名即 `people.id`。

```
faces/
├── registry.json       # 可选：id → 中文名（可从 registry.example.json 复制）
├── index.json          # 自动生成，勿手改（python tools/face_enroll/main.py）
├── baby/               # 宝宝参考照 3～10 张
│   ├── ref_01.jpg
│   └── ref_02.heic
├── mom/
└── dad/
```

## 参考照要求

- 正脸、清晰、脸部占画面一定比例
- 尽量单人照；合照也可，会取最大的一张脸
- 支持 `.jpg` `.jpeg` `.png` `.heic` `.heif`

## registry.json 格式

```json
{
  "baby": {
    "name": "宝宝",
    "birth_date": "2020-09-04",
    "role": "child"
  },
  "mom": {
    "name": "妈妈",
    "birth_date": "1991-10-20",
    "role": "parent"
  }
}
```

`birth_date` 用于在 JSON 里自动计算 `people[].age_at_photo`（几岁几月几天、出生第几天）。

```bash
# 1. 复制并编辑显示名（可选）
cp registry.example.json registry.json

# 2. 把参考照放进 baby/ 等目录

# 3. 生成 index.json
python tools/face_enroll/main.py
```

## 识别

注册后，运行 `python tools/photo2json/main.py` 会自动比对 `data/photos/` 中的照片，
将识别结果写入 JSON 的 `people` 字段。

匹配阈值默认 `0.45`，可通过环境变量调整：

```bash
export FACE_MATCH_THRESHOLD=0.50
python tools/face_enroll/main.py
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
