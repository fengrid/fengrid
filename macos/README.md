# macOS builds (native runner)

macOS apps **cannot** be built inside Docker (Apple EULA; no macOS base
images). The CI workflow runs `build/scripts/build-macos.sh` natively on the
`macos-x64` / `macos-arm64` runners; `docker/macos-*.Dockerfile` are
fail-fast stubs that exist only to keep the pipeline list complete.

## One-time runner setup

```sh
bash macos/setup-macos.sh
```

## Code signing & notarization (optional; unsigned builds work for local testing)

`build-macos.sh` signs the bundle when `MAC_CODESIGN_ID` is set. For
distribution, add notarization once Apple credentials are available:

| Variable | Purpose |
|---|---|
| `MAC_CODESIGN_ID` | Developer ID Application identity (codesign) |
| `APPLE_ID` | Apple ID for notarytool |
| `APPLE_TEAM_ID` | App Store Connect team id |
| `APPLE_PASSWORD` | App-specific password (or use `APPLE_API_KEY*` key files) |

Sketch (to wire into `build-macos.sh` once credentials exist):

```sh
xcrun notarytool submit fengrid-prod-macos-arm64.zip \
    --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_PASSWORD" --wait
xcrun stapler staple fengrid.app
```

Unsigned builds trigger Gatekeeper warnings ("unidentified developer") —
acceptable for internal testing, not for public distribution.
