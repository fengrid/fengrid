pragma Singleton
import QtQuick

// Lucide icons (ISC-licensed shapes, https://lucide.dev) on the 24px
// grid, rendered with a 1.25px hairline stroke — the subtle, technical
// weight used across Fengrid's own UI (no emoji anywhere; studio rule).
// Path data is vendored in from lucide@latest so the app needs no icon
// runtime or network access; names keep their Fengrid keys (a few were
// renamed upstream: grid->layout-grid, help->circle-question-mark,
// refresh->refresh-cw, unlock->lock-open, code->code-xml).
QtObject {
    readonly property var _paths: ({
        "check": "<path d='M20 6 9 17l-5-5' />",
        "chevron-down": "<path d='m6 9 6 6 6-6' />",
        "chevron-left": "<path d='m15 18-6-6 6-6' />",
        "chevron-right": "<path d='m9 18 6-6-6-6' />",
        "chevron-up": "<path d='m18 15-6-6-6 6' />",
        "code": "<path d='m18 16 4-4-4-4' /> <path d='m6 8-4 4 4 4' /> <path d='m14.5 4-5 16' />",
        "copy": "<rect width='14' height='14' x='8' y='8' rx='2' ry='2' /> <path d='M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2' />",
        "download": "<path d='M12 15V3' /> <path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4' /> <path d='m7 10 5 5 5-5' />",
        "droplet": "<path d='M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z' />",
        "external-link": "<path d='M15 3h6v6' /> <path d='M10 14 21 3' /> <path d='M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6' />",
        "file-text": "<path d='M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z' /> <path d='M14 2v5a1 1 0 0 0 1 1h5' /> <path d='M10 9H8' /> <path d='M16 13H8' /> <path d='M16 17H8' />",
        "folder-plus": "<path d='M12 10v6' /> <path d='M9 13h6' /> <path d='M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z' />",
        "git-branch": "<path d='M15 6a9 9 0 0 0-9 9V3' /> <circle cx='18' cy='6' r='3' /> <circle cx='6' cy='18' r='3' />",
        "grid": "<rect width='7' height='7' x='3' y='3' rx='1' /> <rect width='7' height='7' x='14' y='3' rx='1' /> <rect width='7' height='7' x='14' y='14' rx='1' /> <rect width='7' height='7' x='3' y='14' rx='1' />",
        "hard-drive": "<path d='M10 16h.01' /> <path d='M2.212 11.577a2 2 0 0 0-.212.896V18a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-5.527a2 2 0 0 0-.212-.896L18.55 5.11A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z' /> <path d='M21.946 12.013H2.054' /> <path d='M6 16h.01' />",
        "help": "<circle cx='12' cy='12' r='10' /> <path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3' /> <path d='M12 17h.01' />",
        "image": "<rect width='18' height='18' x='3' y='3' rx='2' ry='2' /> <circle cx='9' cy='9' r='2' /> <path d='m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21' />",
        "layers": "<path d='M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z' /> <path d='M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12' /> <path d='M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17' />",
        "lock": "<rect width='18' height='11' x='3' y='11' rx='2' ry='2' /> <path d='M7 11V7a5 5 0 0 1 10 0v4' />",
        "menu": "<path d='M4 5h16' /> <path d='M4 12h16' /> <path d='M4 19h16' />",
        "moon": "<path d='M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401' />",
        "package": "<path d='M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z' /> <path d='M12 22V12' /> <polyline points='3.29 7 12 12 20.71 7' /> <path d='m7.5 4.27 9 5.15' />",
        "play": "<path d='M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z' />",
        "plus": "<path d='M5 12h14' /> <path d='M12 5v14' />",
        "refresh": "<path d='M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8' /> <path d='M21 3v5h-5' /> <path d='M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16' /> <path d='M8 16H3v5' />",
        "search": "<path d='m21 21-4.34-4.34' /> <circle cx='11' cy='11' r='8' />",
        "star": "<path d='M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z' />",
        "sun": "<circle cx='12' cy='12' r='4' /> <path d='M12 2v2' /> <path d='M12 20v2' /> <path d='m4.93 4.93 1.41 1.41' /> <path d='m17.66 17.66 1.41 1.41' /> <path d='M2 12h2' /> <path d='M20 12h2' /> <path d='m6.34 17.66-1.41 1.41' /> <path d='m19.07 4.93-1.41 1.41' />",
        "tag": "<path d='M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z' /> <circle cx='7.5' cy='7.5' r='.5' fill='currentColor' />",
        "trash": "<path d='M10 11v6' /> <path d='M14 11v6' /> <path d='M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6' /> <path d='M3 6h18' /> <path d='M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2' />",
        "type": "<path d='M12 4v16' /> <path d='M4 7V5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v2' /> <path d='M9 20h6' />",
        "unlock": "<rect width='18' height='11' x='3' y='11' rx='2' ry='2' /> <path d='M7 11V7a5 5 0 0 1 9.9-1' />",
        "upload": "<path d='M12 3v12' /> <path d='m17 8-5-5-5 5' /> <path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4' />",
        "x": "<path d='M18 6 6 18' /> <path d='m6 6 12 12' />",
        "zap": "<path d='M15.914 4a1.5 1.5 0 00-2.474-1.561l-9 9A1.5 1.5 0 005.5 14h4.002a.5.5 0 01.471.666L8.086 20a1.5 1.5 0 002.475 1.56l9-9A1.5 1.5 0 0018.5 10h-3.997a.5.5 0 01-.472-.667z' />"
    })

    function url(name, color, fill, px) {
        var body = _paths[name] || "";
        // 1.25px hairline stroke on the 24px Lucide grid — the
        // technical, understated weight. The viewBox is padded to 28
        // (-2..26): Lucide glyphs ink ~83% of their box, so without
        // the inset a "14px" icon drew ~11.6px of ink next to 12px
        // text (cap-height ~8.7px) and read as oversized. With the
        // 28-box, ink = 0.71 x px — the optical size matches the text
        // beside it, Hermes-style.
        //
        // Stroke: 1.46 units in the 28-box keeps the approved
        // 1.25px/24-box ratio — but at small icon sizes that ratio
        // renders sub-pixel (0.54px at 12px), which rasterizes to gray
        // fuzz. So small glyphs get the stroke boosted to the smallest
        // value that still renders a full 1px: units = max(1.46, 28/px).
        // At 48px tiles the spec ratio wins (proportional, thin); at
        // 12-16px the floor guarantees a crisp single-pixel line.
        var units = Math.max(1.46, 28 / (px || 24));
        // half-pixel snap: for even px the glyph centers land on pixel
        // boundaries and a 1px stroke straddles two columns at ~50%
        // coverage each — the exact "fuzzy plus" fuzz. Shifting the
        // viewBox by 0.5px (in 28-box units) puts the hairlines on
        // pixel centers, measured 0.92-luminance single-pixel lines at
        // 12px and 16px. Odd px are already pixel-centered.
        var x0 = -2;
        if ((px || 24) % 2 === 0) x0 = -2 - 0.5 * (28 / (px || 24));
        var svg = "<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24'" +
                  " viewBox='" + x0 + " " + x0 + " 28 28' fill='" + (fill || "none") + "' stroke='" + color + "'" +
                  " stroke-width='" + units + "' stroke-linecap='round' stroke-linejoin='round'>" +
                  body + "</svg>";
        return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
    }

    function fileUrl(path) {
        // file URL that survives spaces and '#' in indexed paths — and
        // is well-formed on Windows: drive paths need the third slash
        // ("file:///D:/…"; "file://D:/…" would parse 'D:' as a host),
        // UNC paths keep both slashes ("file://host/share/…")
        var s = String(path).replace(/\\/g, "/");
        var enc = encodeURI(s).replace(/#/g, "%23");
        if (/^[A-Za-z]:($|[\/?#])/.test(s))
            return "file:///" + enc;
        if (s.indexOf("//") === 0)
            return "file:" + enc;
        return "file://" + enc;
    }

    function toLocalPath(u) {
        // file:///D:/Library/… → "D:/Library/…" (NOT "/D:/…" — Windows
        // isdir can never match that). POSIX URLs keep the leading
        // slash; file://host/share becomes a //host/share UNC path.
        // decodeURIComponent handles %20 spaces, %23 hashes, UTF-8.
        var s = u.toString();
        if (s.indexOf("file://") !== 0)
            return s;
        var rest = decodeURIComponent(s.substring(7));
        if (/^\/[A-Za-z]:($|[\/?#])/.test(rest))
            return rest.substring(1);           // Windows drive letter
        if (rest.charAt(0) === "/")
            return rest;                        // POSIX absolute
        return "//" + rest;                     // UNC: file://host/share
    }
}
