"""Asset-kind registry — file extensions → tracked asset kinds.

Beyond the original icon/font pair, Fengrid tracks general digital
assets: images, video, audio, documents, structured data, spatial
(GIS/GPS/GNSS), timeseries, and markdown. Every tracked row gets a
generated GUID at first ingest; slugs stay empty until the user sets
one. Extension precedence matters where sets overlap: icon formats stay
icons (the grid previews them), and csv/tsv land in `data` while
dedicated timeseries extensions get their own kind.
"""

from __future__ import annotations

ICON_EXTS = {"png", "svg", "ico", "jpg", "jpeg", "gif", "webp", "bmp",
             "xpm", "icns"}
FONT_EXTS = {"ttf", "otf", "ttc", "otc", "pfb", "woff", "woff2"}

# media + data kinds — every ext here is also discovered by folder scans
IMAGE_EXTS = {"tif", "tiff", "heic", "heif", "psd", "ai", "raw", "cr2",
              "nef", "orf", "raf", "dng", "avif", "jxl"}
VIDEO_EXTS = {"mp4", "mkv", "webm", "mov", "avi", "m4v", "mpg", "mpeg",
              "wmv", "flv"}
AUDIO_EXTS = {"mp3", "flac", "wav", "ogg", "oga", "m4a", "aiff", "aif",
              "opus", "wma", "mid", "midi"}
DOC_EXTS = {"pdf", "doc", "docx", "rtf", "odt", "ods", "odp", "xls",
            "xlsx", "ppt", "pptx", "pages", "epub", "tex", "txt"}
DATA_EXTS = {"json", "xml", "yml", "yaml", "csv", "tsv", "sql", "ndjson",
             "jsonl", "toml", "ini", "cfg", "conf", "parquet", "pq",
             "protobuf", "pb", "plist", "graphml", "dot"}
SPATIAL_EXTS = {"geojson", "kml", "kmz", "gpx", "shp", "shx", "dbf",
                "prj", "cpg", "geotiff", "gpkg", "las", "gml", "wkt"}
TIMESERIES_EXTS = {"h5", "hdf5", "arrow", "feather", "dta", "sav",
                   "rdata", "rds", "dat", "tsq", "mcap"}
MARKDOWN_EXTS = {"md", "markdown", "mdown", "mkd", "mdx"}

# display order used by inventory / rail counts
MEDIA_KINDS = ("image", "video", "audio", "doc", "data", "spatial",
               "timeseries", "markdown")

KIND_EXTS: dict[str, set[str]] = {
    "icon": ICON_EXTS,
    "font": FONT_EXTS,
    "image": IMAGE_EXTS,
    "video": VIDEO_EXTS,
    "audio": AUDIO_EXTS,
    "doc": DOC_EXTS,
    "data": DATA_EXTS,
    "spatial": SPATIAL_EXTS,
    "timeseries": TIMESERIES_EXTS,
    "markdown": MARKDOWN_EXTS,
}

ALL_KINDS = ("icon", "font", *MEDIA_KINDS)

_EXT_KIND: dict[str, str] = {}
for _k, _exts in KIND_EXTS.items():
    for _e in _exts:
        _EXT_KIND.setdefault(_e, _k)   # first kind wins (icon > image, …)


def kind_for_ext(ext: str) -> str | None:
    """Map a file extension (with or without dot) to its asset kind."""
    return _EXT_KIND.get((ext or "").lstrip(".").lower())


def kind_for_file(name: str) -> str | None:
    dot = name.rfind(".")
    return kind_for_ext(name[dot + 1:] if dot >= 0 else "")


# extensions Pillow can open (identify() extracts pixel metadata)
RASTER_EXTS = ICON_EXTS | IMAGE_EXTS


def is_raster(ext: str) -> bool:
    return (ext or "").lstrip(".").lower() in RASTER_EXTS
