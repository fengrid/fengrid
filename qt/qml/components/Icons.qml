pragma Singleton
import QtQuick

// Hand-drawn 24px / 2px-stroke Feather-style icons (MIT-licensed shapes),
// tinted at use time — no emoji anywhere in the UI (studio rule).
QtObject {
    readonly property var _paths: ({
        "search": "<circle cx='11' cy='11' r='8'/><line x1='21' y1='21' x2='16.65' y2='16.65'/>",
        "x": "<line x1='18' y1='6' x2='6' y2='18'/><line x1='6' y1='6' x2='18' y2='18'/>",
        "sun": "<circle cx='12' cy='12' r='5'/><line x1='12' y1='1' x2='12' y2='3'/><line x1='12' y1='21' x2='12' y2='23'/><line x1='4.22' y1='4.22' x2='5.64' y2='5.64'/><line x1='18.36' y1='18.36' x2='19.78' y2='19.78'/><line x1='1' y1='12' x2='3' y2='12'/><line x1='21' y1='12' x2='23' y2='12'/><line x1='4.22' y1='19.78' x2='5.64' y2='18.36'/><line x1='18.36' y1='5.64' x2='19.78' y2='4.22'/>",
        "moon": "<path d='M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z'/>",
        "refresh": "<polyline points='23 4 23 10 17 10'/><path d='M20.49 15a9 9 0 1 1-2.12-9.36L23 10'/>",
        "copy": "<rect x='9' y='9' width='13' height='13' rx='2' ry='2'/><path d='M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'/>",
        "download": "<path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/><polyline points='7 10 12 15 17 10'/><line x1='12' y1='15' x2='12' y2='3'/>",
        "tag": "<path d='M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.83z'/><line x1='7' y1='7' x2='7.01' y2='7'/>",
        "check": "<polyline points='20 6 9 17 4 12'/>",
        "plus": "<line x1='12' y1='5' x2='12' y2='19'/><line x1='5' y1='12' x2='19' y2='12'/>",
        "grid": "<rect x='3' y='3' width='7' height='7'/><rect x='14' y='3' width='7' height='7'/><rect x='14' y='14' width='7' height='7'/><rect x='3' y='14' width='7' height='7'/>",
        "image": "<rect x='3' y='3' width='18' height='18' rx='2' ry='2'/><circle cx='8.5' cy='8.5' r='1.5'/><polyline points='21 15 16 10 5 21'/>",
        "folder-plus": "<path d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'/><line x1='12' y1='11' x2='12' y2='17'/><line x1='9' y1='14' x2='15' y2='14'/>",
        "layers": "<polygon points='12 2 2 7 12 12 22 7 12 2'/><polyline points='2 17 12 22 22 17'/><polyline points='2 12 12 17 22 12'/>",
        "file-text": "<path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/><polyline points='14 2 14 8 20 8'/><line x1='16' y1='13' x2='8' y2='13'/><line x1='16' y1='17' x2='8' y2='17'/>"
    })

    function url(name, color) {
        var body = _paths[name] || "";
        var svg = "<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24'" +
                  " viewBox='0 0 24 24' fill='none' stroke='" + color + "'" +
                  " stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>" +
                  body + "</svg>";
        return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
    }

    function fileUrl(path) {
        // file URL that survives spaces and '#' in indexed paths
        return "file://" + encodeURI(path).replace(/#/g, "%23");
    }

    function toLocalPath(u) {
        var s = u.toString();
        if (s.indexOf("file://") === 0)
            return decodeURIComponent(s.substring(7));
        return s;
    }
}
