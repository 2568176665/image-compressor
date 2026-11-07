# ImageC

基于 Python、Pillow 和 Tkinter 的 Windows 桌面图片压缩工具，支持批量处理 `jpg`、`png`、`webp` 和 `avif`。

## 功能

- 输入是一个图片路径列表：可以一次多选图片，也可以选择文件夹（会把目录内的图片全部加入列表），并支持把图片或文件夹直接拖进列表。
- 输出方式三档：`原图同目录`、`原图同目录\compressed`、`自定义目录…`；自动输出方式会给文件名追加 `_ic` 后缀，避免和原图重名。
- Pillow 负责图片读取、EXIF 方向校正和等比例 LANCZOS Resize。
- JPG 使用 Jpegli `cjpegli`，PNG 使用 `pngquant` + `oxipng`，WebP 使用 `cwebp`，AVIF 使用 `avifenc`。
- JPG、PNG、WebP、AVIF 均支持输入和输出；透明图片输出 JPG 时使用白色背景。
- “最大大小 (KB)” 是硬上限：通过编码器大小上限参数与 Resize 重试保证不生成超限文件。
- 默认不覆盖已存在的输出文件，冲突时自动追加 `-1`、`-2` 后缀；可在界面勾选“覆盖同名输出文件”改为复用原文件名。
- 当输出路径与源文件相同时始终拒绝写入；即使开启覆盖，也不会把输出写到本批次的任何一个输入文件上，避免误删原图。
- 输出不保留原图元数据；任务支持批量并发（默认 4 线程，上限 16）和取消。

当前发布包只提供 Windows x64 编码器。Pillow 的 AVIF 读写在本项目中按 8-bit 图片处理，不用于 HDR/10-bit 保真传输。

## 运行

```bash
uv run main.py
```

界面依赖 `tkinterdnd2` 提供拖拽；该包缺失时程序仍可启动，只是列表不再接受拖入文件。

启动时会校验 `src/third_party/codecs/windows-x64/manifest.json` 及全部编码器的 SHA-256，并检查编码器是否可以运行。资源校验失败时，开始按钮会保持禁用。

## 测试

```bash
uv run pytest
```

`tests/test_codec_smoke.py` 会调用内置编码器做真实编码，因此测试耗时依赖本机性能。

## 打包

PyInstaller（输出到 `dist/`）：

```bash
uv run build.py
uv run build.py --onefile
```

默认生成 onedir 包（启动最快）；`--onefile` 生成单文件 EXE。两种模式都会在打包前校验编码器资源清单，构建完成后再次校验产物：

- **onedir**：编码器内置在 `dist/image_compressor/_internal/codecs/windows-x64/`。
- **onefile**：编码器**不**打进 exe，而是复制到 `dist/codecs/windows-x64/`，必须与 `dist/image_compressor.exe` 一起分发。PyInstaller 的 onefile 每次启动都要把内置资源解压到临时目录，把约 20MB 编码器留在外面，等于每次冷启动少写 20MB、少扫几十个文件。运行时优先在 exe 同级目录找 `codecs/windows-x64/`，缺失会明确报错而不是静默降级。

构建会排除本程序用不到的模块（`ssl`、`urllib`、`email`、`xml`、`sqlite3`、`asyncio` 等），顺带丢掉随 Pillow 一起被收集的 OpenSSL 运行库（`libcrypto-3-x64.dll` 7.8MB + `libssl-3-x64.dll` 1.5MB）。`hashlib` 在缺少 `_hashlib` 时会回退到内建 `_sha256`，编码器清单的 SHA-256 校验不受影响。

## 第三方许可

编码器来源、版本、许可证和 pngquant 的 GPL/商业授权要求见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。发布包含 pngquant 的版本前，需要完成相应授权合规确认。
