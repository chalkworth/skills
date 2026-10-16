---
name: remote-simulator
description: Fixture excerpt of an imported skill with version markers, used by the marker lint tests. Not a shipped skill.
---

# Remote Simulator (fixture excerpt)

Upstream: example/simulator tag v6.1.0. Each marker below was checked against that tag, and the text from the
upstream main branch that did not hold on v6.1.0 was replaced.

The simulator ships a `code_server` extension at version 1.4.0. <!-- VERIFIED(Simulator 6.1.0): code_server extension version is 1.4.0 => extension.toml has version = "1.4.0" -->

The server listens on `127.0.0.1:8226`. <!-- VERIFIED(Simulator 6.1.0): default bind is 127.0.0.1 port 8226 => the same extension.toml [settings]: host = "127.0.0.1", port = 8226 -->

Start it with `--enable code_server`; the `/enabled=true` setting does not work. <!-- VERIFIED(Simulator 6.1.0): the --enable flag is the supported route => the upstream pitfalls page says so and the extension id matches extension.toml; the failing setting was not run, it is upstream's claim -->

`Prim.set_local_poses` takes `translations=`, not `positions=`. <!-- VERIFIED(Simulator 6.1.0): set_local_poses keyword is translations => the signature in prim.py is (translations, orientations, indices); set_world_poses takes positions -->

The server has no authentication unless you ask for it: `require_auth` defaults to false. <!-- VERIFIED(Simulator 6.1.0): upstream's "no auth" is incomplete => extension.toml has require_auth = false and an optional auth_token; extension.py generates a token when require_auth is true -->

Without a configured asset root, call `get_assets_root_path()` instead of hard-coding a bucket path. <!-- SELECTED(Simulator 6.1.0): asset root .../Assets/6.2 (upstream main text) | get_assets_root_path() => get_assets_root_path(): the storage extension.toml sets the default asset root to .../Assets/6.1, so the 6.2 string is wrong on 6.1.0 -->
