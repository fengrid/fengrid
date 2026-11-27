# syntax=docker/dockerfile:1
#
# Fengrid Windows builder — windows-x64. DRAFT: UNVERIFIED.
#
# Windows base images only run on Windows hosts: the CI runner tagged
# (docker, windows-x64) must be a Windows machine with Windows containers
# enabled (process isolation). NOTE: the default CI path for this target is
# the native script (build/scripts/build-windows.ps1) which produces the
# same artifact — this Dockerfile is the containerized alternative and has
# not had its first real run yet.
#
# Package management is uv, matching every other pipeline: the astral
# installer drops uv into C:\uv (honoring $env:UV_INSTALL_DIR), and uv
# fetches its own CPython 3.12 (UV_PYTHON) — the python.org installer
# download is gone.
#
# TODO(draft) before first use: verify the astral installer URL is reachable
# from the runner and the servercore tag available at build time.
FROM mcr.microsoft.com/windows/servercore:ltsc2022 AS build
ARG VARIANT=prod
SHELL ["powershell", "-Command", "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue';"]

ENV UV_INSTALL_DIR=C:\uv UV_PYTHON=3.12 UV_NO_CACHE=1 FENGRID_VARIANT=${VARIANT}

# uv via the official installer (ExecutionPolicy Bypass — servercore's
# default RemoteSigned would block a downloaded .ps1)
RUN [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; \
    Invoke-WebRequest -Uri 'https://astral.sh/uv/install.ps1' -OutFile C:\uv-install.ps1; \
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\uv-install.ps1; \
    Remove-Item C:\uv-install.ps1
ENV PATH="C:\uv;%PATH%"

WORKDIR C:/work
COPY build/scripts/ C:/work/build/scripts/
# qt/ carries pyproject.toml + the committed uv.lock (the uv project root)
COPY qt/ C:/work/qt/
COPY fonts/ C:/work/fonts/

# frozen environment from the committed uv.lock — uv pulls CPython 3.12
# into its managed runtimes dir, which persists in this image layer
RUN cd C:\work\qt; if ($env:FENGRID_VARIANT -eq 'dev') { uv sync --frozen --group build } else { uv sync --frozen --no-dev --group build }
RUN cd C:\work\qt; C:\work\qt\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --name fengrid --add-data 'qml;qml' --add-data '..\fonts;fonts' --paths src src\fengrid\__main__.py

FROM mcr.microsoft.com/windows/nanoserver:ltsc2022 AS artifact
COPY --from=build C:/work/qt/dist/fengrid C:/fengrid
