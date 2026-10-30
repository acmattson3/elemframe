"""ElemFrame: an offline digital photo frame. Serve only on localhost."""
from __future__ import annotations

import os
import json
import tempfile
from threading import Lock
import shutil
import stat
from typing import Literal
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from removable import locations
from media import EXTS, VIDEO_EXTS, display_name, playback_path, prepare_import, cached_copies, MediaError

ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("ELEMFRAME_DATA_DIR", str(ROOT))).expanduser().resolve()
LIBRARY = Path(os.environ.get("PICTURE_LIBRARY", str(DATA_ROOT / "library"))).expanduser().resolve()
# Optional comma-separated roots for removable media; defaults work on common Linux desktops.
MEDIA_ROOTS = [Path(p).expanduser().resolve() for p in os.environ.get("PICTURE_REMOVABLE_ROOTS", "/media,/run/media").split(",") if p]
LIBRARY.mkdir(parents=True, exist_ok=True)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


CONFIG = Path(os.environ.get("ELEMFRAME_CONFIG", str(DATA_ROOT / "config.json")))
CONFIG.parent.mkdir(parents=True, exist_ok=True)
config_lock = Lock()


class Settings(BaseModel):
    display_time: float = Field(default=7, ge=3, le=15, multiple_of=0.5)
    transition_time: float = Field(default=0, ge=0, le=5, multiple_of=0.5)
    shuffle: bool = False
    volume: float = Field(default=0, ge=0, le=1)


class SettingsUpdate(BaseModel):
    display_time: float | None = Field(default=None, ge=3, le=15, multiple_of=0.5)
    transition_time: float | None = Field(default=None, ge=0, le=5, multiple_of=0.5)
    shuffle: bool | None = None
    volume: float | None = Field(default=None, ge=0, le=1)


def write_config(settings: Settings):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=CONFIG.parent, prefix=".config-", delete=False) as output:
            temporary = Path(output.name)
            json.dump(settings.model_dump(), output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, CONFIG)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if not CONFIG.exists():
    write_config(Settings())


def read_config():
    try:
        return Settings.model_validate_json(CONFIG.read_text())
    except (OSError, ValueError) as error:
        raise HTTPException(500, "Cannot read config.json: " + str(error))


@app.get("/api/health")
def health():
    return {"app": "ElemFrame", "version": "0.1.0", "data_dir": str(DATA_ROOT)}


@app.post("/api/shutdown")
def shutdown(request: Request):
    import secrets
    token = getattr(app.state, "launcher_token", None)
    if not token or not secrets.compare_digest(request.headers.get("X-ElemFrame-Token", ""), token):
        raise HTTPException(403, "Not authorized")
    app.state.shutdown()
    return {"ok": True}


@app.get("/api/config")
def get_config():
    with config_lock:
        return read_config().model_dump()


@app.post("/api/config")
def update_config(update: SettingsUpdate):
    with config_lock:
        settings = Settings(**{**read_config().model_dump(), **update.model_dump(exclude_none=True)})
        try:
            write_config(settings)
        except OSError as error:
            raise HTTPException(500, "Cannot save config.json: " + str(error))
        return settings.model_dump()


def contained(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def removable_locations():
    return locations(MEDIA_ROOTS)


def resolve(side: str, relative: str, *, require_exists: bool = True) -> Path:
    if side not in ("local", "removable"):
        raise HTTPException(400, "Invalid side")
    if (not isinstance(relative, str) or relative.startswith("/") or "\\" in relative
            or "\0" in relative or ":" in relative):
        raise HTTPException(400, "Invalid path")
    if ".." in PurePosixPath(relative).parts:
        raise HTTPException(400, "Parent paths prohibited")
    if side == "local":
        base, suffix = LIBRARY, relative
    else:
        drive = next((d for d in removable_locations()
                      if relative == d["path"] or relative.startswith(d["path"] + "/")), None)
        if drive is None:
            raise HTTPException(403, "No accessible removable drive at this path")
        base = drive["root"]
        suffix = relative[len(drive["path"]):].lstrip("/")
    candidate = base.joinpath(*PurePosixPath(suffix).parts).resolve()
    if not contained(candidate, base):
        raise HTTPException(403, "Path outside accessible area")
    if require_exists and not candidate.exists():
        raise HTTPException(404, "File or folder missing")
    return candidate


def authorized_removable(relative: str) -> Path:
    return resolve("removable", relative)


def checked(side: str, path: str, exists=True) -> Path:
    if side == "removable":
        if not exists:
            # Existing parent must be on an authorized drive.
            authorized_removable(str(PurePosixPath(path).parent).replace("\\", "/"))
            return resolve(side, path, require_exists=False)
        return authorized_removable(path)
    return resolve(side, path, require_exists=exists)


def entry(p: Path, prefix: str):
    return {"name": p.name, "label": p.name if p.is_dir() else display_name(p), "video": p.suffix.lower() in VIDEO_EXTS, "path": f"{prefix}/{p.name}" if prefix else p.name,
            "directory": p.is_dir(), "media": p.suffix.lower() in EXTS and p.is_file()}


@app.get("/api/list")
def list_files(side: str, path: str = ""):
    if side == "removable" and not path:
        return {"path": "", "items": [{"name": d["name"], "path": d["path"], "directory": True, "media": False, "drive": True} for d in removable_locations()]}
    target = checked(side, path)
    if not target.is_dir():
        raise HTTPException(400, "Not a folder")
    try:
        items = [entry(p, path) for p in target.iterdir() if not p.is_symlink() and not p.name.startswith(".")]
        items.sort(key=lambda x: (not x["directory"], x["name"].lower()))
        return {"path": path, "items": items}
    except PermissionError:
        raise HTTPException(403, "Cannot read folder")


class PathRequest(BaseModel):
    side: str
    path: str


class RenameRequest(PathRequest):
    name: str
    stem_only: bool = False


class CopyRequest(BaseModel):
    source_side: str
    source_paths: list[str]
    target_side: str
    target_path: str
    conflict: Literal["error", "replace", "rename"] = "error"


def validate_name(name: str):
    if os.name == "nt":
        stem = name.split(".")[0].upper()
        if (any(c in name for c in '<>:"|?*') or name.endswith((".", " "))
                or stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}):
            raise HTTPException(400, "Invalid name")
    if any(ord(c) < 32 for c in name):
        raise HTTPException(400, "Invalid name")
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\0" in name or name.startswith("."):
        raise HTTPException(400, "Invalid name")


def protect_root(side: str, path: str):
    if not path or (side == "removable" and path in {d["path"] for d in removable_locations()}):
        raise HTTPException(403, "Cannot modify root folder")


@app.post("/api/mkdir")
def mkdir(req: RenameRequest):
    validate_name(req.name)
    folder = checked(req.side, req.path)
    if not folder.is_dir():
        raise HTTPException(400, "Not a folder")
    dest = checked(req.side, f"{req.path}/{req.name}".strip("/"), exists=False)
    try:
        dest.mkdir()
    except FileExistsError:
        raise HTTPException(409, "Name already exists")
    return {"ok": True}


@app.post("/api/rename")
def rename(req: RenameRequest):
    protect_root(req.side, req.path)
    validate_name(req.name)
    src = checked(req.side, req.path)
    parent = str(PurePosixPath(req.path).parent)
    if parent == ".": parent = ""
    name = req.name + src.suffix if req.stem_only and src.is_file() else req.name
    dst = checked(req.side, f"{parent}/{name}".strip("/"), exists=False)
    if dst == src:
        return {"ok": True}
    if dst.exists():
        raise HTTPException(409, "Name already exists")
    try:
        src.rename(dst)
    except OSError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/delete")
def delete(req: PathRequest):
    protect_root(req.side, req.path)
    p = checked(req.side, req.path)
    prepared_copies = cached_copies(p, LIBRARY) if req.side == "local" else []
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        for prepared in prepared_copies:
            prepared.unlink(missing_ok=True)
    except OSError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/copy")
def copy(req: CopyRequest):
    return transfer(req)


@app.post("/api/move")
def move(req: CopyRequest):
    return transfer(req, moving=True)


def transfer(req: CopyRequest, moving=False):
    if not req.source_paths or len(req.source_paths) > 1000:
        raise HTTPException(400, "Choose files to copy")
    dest_dir = checked(req.target_side, req.target_path)
    if not dest_dir.is_dir():
        raise HTTPException(400, "Target must be a folder")
    # Validate all inputs first to avoid partial copies on basic validation errors.
    operations = []
    for rel in req.source_paths:
        src = checked(req.source_side, rel)
        if moving:
            protect_root(req.source_side, rel)
        if req.source_side == "removable" and rel in {d["path"] for d in removable_locations()}:
            raise HTTPException(403, "Open drive and select files or folders")
        dst = checked(req.target_side, f"{req.target_path}/{src.name}".strip("/"), exists=False)
        if dst.exists():
            if req.conflict == "replace":
                pass
            elif req.conflict == "rename":
                stem, suffix = (src.name, "") if src.is_dir() else (src.stem, src.suffix)
                n = 1
                while dst.exists():
                    dst = checked(req.target_side, f"{req.target_path}/{stem} ({n}){suffix}".strip("/"), exists=False)
                    n += 1
            else:
                raise HTTPException(409, f"Already exists: {display_name(src)}")
        if src.is_dir() and (src == dest_dir or src in dest_dir.parents):
            raise HTTPException(400, "Cannot copy folder into itself")
        if dst == src or dst in src.parents:
            raise HTTPException(400, "Cannot replace a source file or its parent folder")
        operations.append((src, dst))
    try:
        for src, dst in operations:
            old_copies = cached_copies(dst, LIBRARY) if req.target_side == "local" and dst.exists() else []
            if moving and req.source_side == "local" and req.target_side != "local":
                old_copies.extend(cached_copies(src, LIBRARY))
            if dst.exists() and req.conflict == "replace":
                if dst.is_dir(): shutil.rmtree(dst)
                else: dst.unlink()
            if moving: shutil.move(str(src), str(dst))
            elif src.is_dir(): shutil.copytree(src, dst, symlinks=False)
            else: shutil.copy2(src, dst)
            for prepared in old_copies:
                prepared.unlink(missing_ok=True)
    except OSError as e:
        raise HTTPException(400, str(e))
    issues = []
    if req.target_side == "local":
        for _, destination in operations:
            issues.extend(prepare_import(destination, LIBRARY))
    return {"ok": True, "count": len(operations), "issues": issues}


@app.get("/api/slideshow")
def slideshow():
    files = []
    for directory, dirs, names in os.walk(LIBRARY, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink()]
        for name in names:
            p = Path(directory) / name
            if p.suffix.lower() in EXTS and not p.is_symlink():
                files.append({"path": p.relative_to(LIBRARY).as_posix(), "name": display_name(p),
                              "video": p.suffix.lower() in VIDEO_EXTS})
    return sorted(files, key=lambda f: f["path"].lower())


class PrepareRequest(BaseModel):
    path: str
    fallback: bool = False


@app.post("/api/prepare")
def prepare_media(req: PrepareRequest):
    source = checked("local", req.path)
    if not source.is_file() or source.suffix.lower() not in EXTS:
        raise HTTPException(404)
    try:
        playback_path(source, LIBRARY, force=req.fallback)
    except MediaError:
        raise HTTPException(415, "This item could not be displayed")
    return {"url": "/media/" + quote(req.path, safe="/") + ("?fallback=true" if req.fallback else "")}


@app.get("/media/{path:path}")
def serve_media(path: str, fallback: bool = False):
    p = checked("local", path)
    if not p.is_file() or p.suffix.lower() not in EXTS:
        raise HTTPException(404)
    try:
        prepared = playback_path(p, LIBRARY, force=fallback)
    except MediaError:
        raise HTTPException(415, "This item could not be displayed")
    # H.264 QuickTime/M4V can use the browser's MP4 decoder directly.
    mime = "video/mp4" if prepared.suffix.lower() in {".mp4", ".mov", ".m4v"} else None
    return FileResponse(prepared, media_type=mime)


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
