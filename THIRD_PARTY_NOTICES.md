# 第三方编码器声明

Windows x64 发布包内置以下命令行编码器。许可证文件和运行时 DLL 位于 `src/third_party/codecs/windows-x64/`，构建时会一并复制到发布包。

| 组件 | 固定版本 | 用途 | 来源与许可证 |
| --- | --- | --- | --- |
| Jpegli `cjpegli` | libjxl v0.11.2 | JPEG 编码 | [libjxl](https://github.com/libjxl/libjxl)，BSD-3-Clause；静态包依赖的许可证也随包保留 |
| pngquant | 3.0.3 | PNG 有损调色板量化 | [pngquant](https://pngquant.org/)，GPL-3.0-or-later 或商业授权；发布前必须满足对应授权 |
| `liblcms2-2.dll` | Little CMS 2.19.1 | pngquant 运行时依赖 | [Little CMS](https://github.com/mm2/Little-CMS)，MIT |
| `libpng16-16.dll` / `zlib1.dll` | libpng 1.6.58 / zlib 1.3.2 | pngquant 运行时依赖 | libpng 自定义许可 / zlib 许可 |
| oxipng | v10.2.1 | PNG 无损优化 | [oxipng](https://github.com/oxipng/oxipng)，MIT |
| libwebp `cwebp` | v1.6.0 | WebP | [libwebp](https://chromium.googlesource.com/webm/libwebp/)，BSD-3-Clause，并适用 WebM 专利条款 |
| libavif `avifenc` | v1.4.2 | AVIF | [libavif](https://github.com/AOMediaCodec/libavif)，BSD-2-Clause；AOM/dav1d 等编码依赖的许可要求也随包保留 |

`cjpegli` 保持在 libjxl v0.11.2：libjxl v0.12.0 已将 jpegli 代码移出并交由 [google/jpegli](https://github.com/google/jpegli) 维护，而该仓库目前未发布 Windows 二进制。待其提供构建产物后再随包升级。

`manifest.json` 记录最终随包文件的 SHA-256。`build.py` 和程序启动检查都会验证清单；文件缺失、被替换或版本资源损坏时不会继续构建/压缩。

归档来源及下载校验值：

- libjxl v0.11.2 `jxl-x64-windows-static.zip`：SHA-256 `97dc815bdd99ba243d8502050357342cf649251a5df069f8c3daee6828cbe0ce`
- libavif v1.4.2 `windows-artifacts.zip`：SHA-256 `cb2d9fea43dcbab1d0707e3b37eb7b08070ad2fb60a2c188c39ec12382c0484a`
- libwebp v1.6.0 `libwebp-1.6.0-windows-x64.zip`：最终可执行文件以 `manifest.json` 为准
- oxipng v10.2.1 `oxipng-10.2.1-x86_64-pc-windows-msvc.zip`：SHA-256 `7e940f83ee46874b73f53031f96a15834cb70b220af27391fb06fe7b4dd798e1`
- pngquant 3.0.3：MSYS2 UCRT64 包 [`mingw-w64-ucrt-x86_64-pngquant-3.0.3-1`](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-pngquant)，归档 SHA-256 `084352e218625fbc46c3bc7bd4a0e0dfb266ad305fbce86ddc46e15a735ebaf0`

pngquant 的 GPL/商业授权是发布前的硬性合规项。如果项目无法接受 GPL，应替换为单独取得商业许可的 pngquant 构建，并同步更新 manifest、本声明以及对应许可证文件。
