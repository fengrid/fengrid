import QtWebEngine
import QtQuick

// PreviewPane — the hardened embedded-Chromium surface (ADR-0001 §8/§9).
//
// Two content modes:
// - `assetPath`: serves an indexed file through fengrid-asset:// (path
//   allowlist enforced in Python by AssetSchemeHandler).
// - `document`: renders in-memory HTML (code playground / composer) via
//   loadHtml with an fengrid-asset:// base URL, so relative references
//   stay inside the sandboxed scheme.
//
// Every other request is blocked by the profile's interceptor. The profile
// MUST be the hardened off-the-record one (`previewProfile` context
// property, built by web.make_preview_profile) — the default profile has
// no interceptor, so instantiating this component without one is a bug.
//
// Startup contract: the scheme is registered and QtWebEngineQuick.initialize()
// runs before QGuiApplication (both in __main__); the component is only ever
// instantiated inside a Loader that the shell activates on demand, so the
// QA offscreen renders never pay the Chromium startup cost.
WebEngineView {
    id: pane

    property string assetPath: ""
    onAssetPathChanged: {
        if (assetPath !== "")
            pane.url = "fengrid-asset://" + assetPath
    }

    property string document: ""
    onDocumentChanged: {
        if (document !== "")
            // baseUrl keeps relative resolution inside the sandboxed scheme;
            // the interceptor still blocks everything unlisted
            pane.loadHtml(pane.document, "fengrid-asset://playground/")
    }

    settings.showScrollBars: true
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
