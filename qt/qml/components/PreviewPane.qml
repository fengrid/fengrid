import QtWebEngine
import QtQuick

// PreviewPane — the hardened embedded-Chromium surface (ADR-0001 §8/§9).
//
// Serves indexed assets through fengrid-asset:// (path allowlist enforced in
// Python by AssetSchemeHandler); every other request is blocked by the
// profile's interceptor. Off-the-record profile — no storage, no cache.
//
// Startup contract: the scheme must be registered before QGuiApplication
// (done unconditionally in __main__ via web.register_asset_scheme). When the
// FIRST PreviewPane instance is ever shown, call QtWebEngineQuick.initialize()
// in Python before the app object — the default shell does not instantiate
// this component, so it stays out of the QA render path.
WebEngineView {
    id: pane

    property string assetPath: ""
    onAssetPathChanged: {
        if (assetPath !== "")
            pane.url = "fengrid-asset://" + assetPath
    }

    settings.showScrollBars: false
    settings.webGLEnabled: false
    settings.pluginsEnabled: false
    settings.javascriptCanAccessClipboard: false
    settings.localContentCanAccessRemoteUrls: false
    settings.localContentCanAccessFileUrls: false

    // previewed components are untrusted content: no context-menu powers,
    // no downloads, no window.open
    onContextMenuRequested: function(request) {
        request.accepted = true
    }
    onRenderProcessTerminated: function(status, code) {
        console.warn("preview renderer terminated:", status, code)
    }
}
