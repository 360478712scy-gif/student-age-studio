# Third-party components and game resources

StudentAge Studio's original editor code is licensed under GPL-3.0-only.

- `standalone/search-pinyin.js` contains pronunciation data from pypinyin 0.55.0 under the MIT license. Its original license and copyright notice remain at the top of that file.
- `standalone/vendor-steamworks/SteamworksPy64.dll` is the upstream redistributable bridge from SteamworksPy 1.6.3 by GP Garcia, CoaguCo Industries, under the MIT license (see `standalone/vendor-steamworks/LICENSE.SteamworksPy`). Valve's `steam_api64.dll` is proprietary and is **not** shipped: at runtime the editor loads the copy from the user's own game installation or Steam client directory.
- Python packages installed through `requirements.txt` retain their own licenses. They are dependencies, not relicensed copies of this project's code.
- StudentAge game images, fonts, original tables, story data, extracted bundles and user Mods are **not included** in the public repository or code-update ZIP. Resource layout descriptions and extraction code are provided so users can work with their own local game installation.
- Optional Live2D Cubism Core binaries, proprietary SDK runtimes, native compiled helpers and bundled third-party JavaScript distributions are not included. Obtain optional SDKs from their respective vendors and follow their licenses. The editor's GPL does not grant rights to those components or to game assets.
- The name of the game identifies compatibility. This is an independent community editor.

- certifi 提供 Mozilla 根证书集合，按其 MPL-2.0 许可分发；客户端同时保留系统信任根并校验 HTTPS 证书与主机名。
