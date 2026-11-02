# Runtime branding resources

`fengrid-mark.svg` is the application/window icon bundled by
`build/scripts/build-linux.sh` (`--add-data "$QT_DIR/resources" resources`)
and resolved by `fengrid.__main__._asset_dir("resources", "branding")`.

Provenance: copied from `branding/assets/fengrid-mark.svg`
(md5 `015c2673193af5426d66aad4e03dc9a8`). `branding/assets` remains the
design source of truth but is deliberately gitignored (internal candidate
branding docs — see the root `.gitignore`), so the runtime copy lives here,
tracked, so CI checkouts always have it. If the mark changes upstream,
re-copy it here and update this note.
