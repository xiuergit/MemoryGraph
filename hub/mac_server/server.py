"""MemoryGraph Mac 本地服务：接收 iOS 上传、触发分析、落盘。"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.analyzer import analyze_image
from hub.shared.config import MEMORY_DIR, PHOTOS_DIR
from hub.shared.family import enrich_people_with_age
from hub.shared.schema import AnalysisResult, analysis_from_dict, build_photo_json
from hub.shared.utils import (
    build_source_info,
    enrich_analysis_location,
    extract_exif_timestamp,
    get_photo_id,
)

logger = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, File, Form, UploadFile
    from fastapi.responses import JSONResponse
except ImportError as exc:
    raise ImportError(
        "缺少 fastapi，请安装: pip install -r requirements.txt"
    ) from exc

app = FastAPI(title="MemoryGraph Mac Hub", version="0.1.0")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/import")
async def import_photo(
    file: UploadFile = File(...),
    json_payload: Optional[str] = Form(default=None),
    device_id: str = Form(default="iphone"),
) -> JSONResponse:
    """接收 iOS 上传的原图，可选附带 JSON 骨架；落盘后补全 AI 字段。

    - 原图写入 data/photos/{photo_id}{ext}
    - JSON 写入 data/memory/{photo_id}.json
    """
    if not file.filename:
        return JSONResponse({"error": "missing filename"}, status_code=400)

    photo_path = Path(file.filename)
    photo_id = get_photo_id(photo_path)

    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    dest_photo = PHOTOS_DIR / file.filename
    content = await file.read()
    dest_photo.write_bytes(content)

    incoming: dict | None = None
    if json_payload:
        try:
            incoming = json.loads(json_payload)
        except json.JSONDecodeError:
            return JSONResponse({"error": "invalid json_payload"}, status_code=400)
        timestamp = incoming.get("timestamp") or extract_exif_timestamp(dest_photo)
        device = incoming.get("device_id") or device_id
    else:
        timestamp = extract_exif_timestamp(dest_photo)
        device = device_id

    raw = analyze_image(
        str(dest_photo),
        timestamp=timestamp,
        photo_id=photo_id,
    )
    analysis, location_coords = enrich_analysis_location(analysis_from_dict(raw), dest_photo)
    analysis = AnalysisResult(
        people=enrich_people_with_age(analysis["people"], timestamp),
        scene=analysis["scene"],
        location=analysis["location"],
        objects=analysis["objects"],
        actions=analysis["actions"],
        emotion=analysis["emotion"],
        tags=analysis["tags"],
        quality=analysis["quality"],
    )

    source = build_source_info(dest_photo)
    photo_json = build_photo_json(
        photo_id=photo_id,
        timestamp=timestamp,
        source=source,
        analysis=analysis,
        device_id=device,
        location_coords=location_coords,
    )

    memory_path = MEMORY_DIR / f"{photo_id}.json"
    with memory_path.open("w", encoding="utf-8") as f:
        json.dump(dict(photo_json), f, ensure_ascii=False, indent=2)
        f.write("\n")

    logger.info("已导入: photo=%s, memory=%s", dest_photo.name, memory_path.name)
    return JSONResponse(dict(photo_json))


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    uvicorn.run(
        "hub.mac_server.server:app",
        host="0.0.0.0",
        port=8765,
        reload=False,
    )


if __name__ == "__main__":
    main()
