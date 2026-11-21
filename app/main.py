
import re
import shutil
import tempfile
import subprocess
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
        return (
            int(parts[0]) * 3600
            + int(parts[1]) * 60
            + int(parts[2])
        )

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
        raise HTTPException(
            status_code=400,
            detail="Informe um link HTTPS válido da Kick."
        )

    if bool(data.start) != bool(data.end):
        raise HTTPException(
            status_code=400,
            detail="Informe o início e o fim do trecho."
        )

    start = end = None

    if data.start and data.end:
        try:
            start = parse_time(data.start)
            end = parse_time(data.end)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc)
            )

        if start < 0 or end <= start or end - start > 3600:
            raise HTTPException(
                status_code=400,
                detail="O trecho deve ter até 60 minutos."
            )

    temp_dir = Path(tempfile.mkdtemp(prefix="kick-download-"))

    try:
        options = {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": str(temp_dir / "video.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
            "external_downloader": {
                "m3u8": "ffmpeg"
            },
        }

        if start is not None:
            options["download_ranges"] = (
                yt_dlp.utils.download_range_func(
                    None,
                    [(start, end)]
                )
            )
            options["force_keyframes_at_cuts"] = True

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        files = [
            f for f in temp_dir.glob("video.*")
            if f.is_file()
            and not f.name.endswith(".part")
            and f.suffix.lower() in (
                ".mp4", ".mkv", ".webm", ".mov"
            )
        ]

        if not files:
            raise RuntimeError(
                "Não foi possível localizar o vídeo."
            )

        source = max(files, key=lambda f: f.stat().st_size)
        output = temp_dir / "kick-video.mp4"

        if source.suffix.lower() == ".mp4":
            shutil.copy2(source, output)
        else:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i", str(source),
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-movflags", "+faststart",
                    str(output),
                ],
                check=True,
                capture_output=True,
            )

        return FileResponse(
            output,
            media_type="video/mp4",
            filename="kick-video.mp4",
            background=BackgroundTask(
                shutil.rmtree,
                temp_dir,
                ignore_errors=True
            ),
        )

    except HTTPException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    except Exception as exc:
        print(f"Erro ao baixar vídeo: {exc}")

        shutil.rmtree(temp_dir, ignore_errors=True)

        raise HTTPException(
            status_code=500,
            detail=(
                "Não foi possível processar o vídeo. "
                "Verifique o link e tente novamente."
            )
        )


@app.post("/api/live-capture")
def capture_live(data: DownloadRequest):
    raise HTTPException(
        status_code=501,
        detail=(
            "A captura ao vivo ainda depende de uma "
            "fonte de transmissão autorizada e acessível."
        ),
    )
