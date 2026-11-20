
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from starlette.background import BackgroundTask
import yt_dlp

app = FastAPI(title="Kick Downloader")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class DownloadRequest(BaseModel):
    url: HttpUrl
    start: str | None = None
    end: str | None = None


def parse_time(value):
    parts = value.split(":")
    if not all(re.fullmatch(r"\d+", p) for p in parts):
        raise ValueError("Tempo inválido")

    if len(parts) == 1:
        return int(parts[0])
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

    raise ValueError("Use HH:MM:SS, MM:SS ou segundos")


@app.get("/api/health")
def health():
    return {"status": "online"}


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/download")
def download_video(data: DownloadRequest):
    url = str(data.url)
    parsed = urlparse(url)

    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        host == "kick.com" or host.endswith(".kick.com")
    ):
        raise HTTPException(400, "Informe um link HTTPS válido da Kick.")

    if bool(data.start) != bool(data.end):
        raise HTTPException(400, "Informe o início e o fim do trecho.")

    start = end = None
    if data.start and data.end:
        try:
            start = parse_time(data.start)
            end = parse_time(data.end)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        if start < 0 or end <= start or end - start > 3600:
            raise HTTPException(400, "O trecho deve ter até 60 minutos.")

    temp_dir = Path(tempfile.mkdtemp(prefix="kick-download-"))

    try:
        options = {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": str(temp_dir / "video.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        files = [
            f for f in temp_dir.glob("video.*")
            if f.is_file() and not f.name.endswith(".part")
        ]

        if not files:
            raise RuntimeError("Não foi possível localizar o vídeo.")

        source = max(files, key=lambda f: f.stat().st_size)
        output = temp_dir / "kick-video.mp4"

        if start is not None:
            duration = end - start
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", str(source),
                    "-t", str(duration),
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    str(output),
                ],
                check=True,
                capture_output=True,
            )
        else:
            shutil.copy2(source, output)

        return FileResponse(
            output,
            media_type="video/mp4",
            filename="kick-video.mp4",
            background=BackgroundTask(
                shutil.rmtree, temp_dir, ignore_errors=True
            ),
        )

    except HTTPException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(
            500,
            "Não foi possível processar o vídeo. Verifique o link e tente novamente."
        )



def capture_live(data: DownloadRequest):
    raise HTTPException(
        501,
        "A captura ao vivo ainda não está disponível. "
        
@app.post("/api/live-capture")
def capture_live(data: DownloadRequest):
    raise HTTPException(
        status_code=501,
        detail=(
            "A captura de trechos de uma live ainda depende "
            "de uma fonte de transmissão autorizada e acessível."
        ),
    )

        "É necessário configurar uma fonte de transmissão autorizada."
    )
