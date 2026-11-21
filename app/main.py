
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
        raise ValueError("Tempo inválido.")

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

    raise ValueError("Use HH:MM:SS, MM:SS ou segundos.")


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
            raise HTTPException(status_code=400, detail=str(exc))

        if start < 0 or end <= start or end - start > 3600:
            raise HTTPException(
                status_code=400,
                detail="O trecho deve ter até 60 minutos."
            )

    temp_dir = Path(tempfile.mkdtemp(prefix="kick-download-"))
    output = temp_dir / "kick-video.mp4"

    try:
        ydl_options = {
            "format": "best[height<=720]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "retries": 2,
            "socket_timeout": 30,
        }

        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise RuntimeError("Não foi possível localizar a transmissão.")

        if start is not None:
            media_url = info.get("url")

            if not media_url and info.get("requested_formats"):
                formats = info["requested_formats"]
                media_url = next(
                    (f.get("url") for f in formats if f.get("url")),
                    None
                )

            if not media_url:
                raise RuntimeError("Fonte de vídeo não encontrada.")

            headers = info.get("http_headers") or {}
            header_text = "".join(
                f"{key}: {value}\r\n"
                for key, value in headers.items()
            )

            duration = end - start

            command = ["ffmpeg", "-y", "-ss", str(start)]

            if header_text:
                command += ["-headers", header_text]

            command += [
                "-i", media_url,
                "-t", str(duration),
                "-map", "0:v:0?",
                "-map", "0:a:0?",
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                str(output),
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode != 0:
                print("Erro FFmpeg:", result.stderr[-3000:])
                raise RuntimeError("Falha ao cortar a transmissão.")

        else:
            download_options = {
                "format": "best[height<=720]/best",
                "outtmpl": str(temp_dir / "video.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "retries": 2,
            }

            with yt_dlp.YoutubeDL(download_options) as ydl:
                ydl.download([url])

            files = [
                f for f in temp_dir.glob("video.*")
                if f.is_file() and f.suffix.lower() in (
                    ".mp4", ".mkv", ".webm", ".mov"
                )
            ]

            if not files:
                raise RuntimeError("Vídeo não encontrado.")

            source = max(files, key=lambda f: f.stat().st_size)

            if source.suffix.lower() == ".mp4":
                shutil.copy2(source, output)
            else:
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", str(source),
                        "-c:v", "libx264",
                        "-c:a", "aac",
                        "-movflags", "+faststart",
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=600,
                )

        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError("O arquivo de vídeo ficou vazio.")

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
        print(f"Erro ao processar vídeo: {exc}")
        shutil.rmtree(temp_dir, ignore_errors=True)

        raise HTTPException(
            status_code=500,
            detail=(
                "Não foi possível processar o vídeo. "
                "Verifique se a transmissão está disponível."
            )
        )


@app.post("/api/live-capture")
def capture_live(data: DownloadRequest):
    raise HTTPException(
        status_code=501,
        detail="A captura ao vivo ainda não está disponível."
    )
