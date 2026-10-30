#!/usr/bin/env bash
# Setup the Fengrid development environment using local Qt 6.12.0 at ~/Qt
# Source this: source scripts/setup-qt-env.sh

export QT_ROOT="/home/native/Qt/6.12.0/gcc_64"
export QT_VERSION="6.12.0"
export QT_QPA_PLATFORM="xcb"

# Qt binaries and libraries
export PATH="$QT_ROOT/bin:$PATH"
export LD_LIBRARY_PATH="$QT_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Qt plugins, QML imports
export QT_PLUGIN_PATH="$QT_ROOT/plugins${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
export QML_IMPORT_PATH="$QT_ROOT/qml${QML_IMPORT_PATH:+:$QML_IMPORT_PATH}"
export QML2_IMPORT_PATH="$QT_ROOT/qml${QML2_IMPORT_PATH:+:$QML2_IMPORT_PATH}"

# Point to the .venv for this project
export PYTHONPATH="/home/native/dev/projects/fengrid/qt/src:${PYTHONPATH}"

# Build environment for QtCreator profiles
export FENGRID_BUILD_PROFILE="Qt6-6.12.0-gcc_64"
export FENGRID_DEV_ENV="1"

echo "Qt 6.12.0 environment configured ($QT_ROOT)"
echo "Run: . qt/.venv/bin/activate && python -m fengrid"
