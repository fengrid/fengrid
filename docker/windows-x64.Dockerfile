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
# TODO(draft) before first use: verify the python.org 3.12.x installer URL
# and the servercore tag available at build time.
FROM mcr.microsoft.com/windows/servercore:ltsc2022 AS build
ARG VARIANT=prod
SHELL ["powershell", "-Command", "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue';"]

RUN [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; \
    Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile C:\python-installer.exe; \
    Start-Process -Wait -FilePath C:\python-installer.exe -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1'; \
    Remove-Item C:\python-installer.exe

ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 FENGRID_VARIANT=${VARIANT}

WORKDIR C:/work
COPY build/scripts/ C:/work/build/scripts/
COPY build/requirements-build.txt C:/work/build/requirements-build.txt
COPY build/requirements-dev.txt C:/work/build/requirements-dev.txt
COPY qt/ C:/work/qt/
COPY fonts/ C:/work/fonts/

RUN python -m venv C:\venv
RUN C:\venv\Scripts\python.exe -m pip install --upgrade pip wheel
RUN if ($env:FENGRID_VARIANT -eq 'dev') { \
      C:\venv\Scripts\python.exe -m pip install -r C:\work\build\requirements-dev.txt; \
    } else { \
      C:\venv\Scripts\python.exe -m pip install -r C:\work\build\requirements-build.txt; \
    }
RUN cd C:\work\qt; C:\venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --name fengrid --add-data 'qml;qml' --add-data '..\fonts;fonts' --paths src src\fengrid\__main__.py

FROM mcr.microsoft.com/windows/nanoserver:ltsc2022 AS artifact
COPY --from=build C:/work/qt/dist/fengrid C:/fengrid
