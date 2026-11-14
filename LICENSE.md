# MIT License

Copyright Native IT © 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## Third-party components

### server/vendor/qrcode.min.js

The QR code generator used by the LAN webshare (QR connect page and the
in-app QR dialog) is [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator)
v1.4.4 by Kazuhiko Arase, vendored from npm and minified by jsDelivr. It is
distributed under the MIT license:

> Copyright (c) 2009 Kazuhiko Arase
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

### Python standard library

Fengrid's REST API (`api/v1/`) uses only the Python standard library
(http.server, argparse, …) under the
[PSF License](https://docs.python.org/3/license.html) — nothing is
bundled or distributed from it.

### Optional external tools (not bundled, no distribution required)

The installers may *invoke* these tools at runtime when present, but never
bundle or distribute them: `sips` (macOS built-in, used to convert `.icns`
icons) and ImageMagick (`magick`/`convert`, used to convert `.xpm` icons).
No license obligations arise from invoking them.

---

## Bundled font licenses

The fonts in `fonts/` are subset for use by this project and distributed under
their own licenses, which are included alongside each font:

| Font | License | File |
|------|---------|------|
| Inter | SIL Open Font License 1.1 | [fonts/INTER-LICENSE.txt](fonts/INTER-LICENSE.txt) |
| Iosevka | MIT (Iosevka license) | [fonts/IOSEVKA-LICENSE.md](fonts/IOSEVKA-LICENSE.md) |

Inter is released under the SIL Open Font License 1.1; the bundled
`fonts/INTER-LICENSE.txt` contains the OFL 1.1 text.
