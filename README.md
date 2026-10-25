# ImageC

基于 Python、Pillow 和 Tkinter 的 Windows 桌面图片压缩工具，支持批量处理 `jpg`、`png`、`webp` 和 `avif`。

## 功能

- 支持单文件或文件夹输入，文件夹扫描包含 AVIF。
- Pillow 负责图片读取、EXIF 方向校正和等比例 LANCZOS Resize。
- JPG 使用 Jpegli `cjpegli`，PNG 使用 `pngquant` + `oxipng`，WebP 使用 `cwebp`，AVIF 使用 `avifenc`。
- JPG、PNG、WebP、AVIF 均支持输入和输出；透明图片输出 JPG 时使用白色背景。
- “最大大小 (KB)” 是硬上限：通过编码器大小上限参数与 Resize 重试保证不生成超限文件。
- 默认不覆盖已存在的输出文件，冲突时自动追加 `-1`、`-2` 后缀；可在界面勾选“覆盖同名输出文件”改为复用原文件名。
- 当输出路径与源文件相同时始终拒绝写入，避免误删原图。
- 输出不保留原图元数据；任务支持批量并发（默认 4 线程，上限 16）和取消。

当前发布包只提供 Windows x64 编码器。Pillow 的 AVIF 读写在本项目中按 8-bit 图片处理，不用于 HDR/10-bit 保真传输。

## 运行

```bash
uv run main.py
```

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

默认生成 onedir 包（启动速度更快）；`--onefile` 生成单文件 EXE。两种模式都会内置编码器资源，打包前会校验资源清单，onedir 构建完成后还会再次校验输出目录。

Nuitka（输出到 `nuitka-dist/`）：

```bash
uv run build-N.py
uv run build-N.py --onefile
```

默认生成 `nuitka-dist/image_compressor.dist/`，`--onefile` 生成 `nuitka-dist/image_compressor.exe`，与 PyInstaller 的产物目录互不覆盖。Nuitka 首次构建会下载 MinGW 或 Dependency Walker 等依赖，需要联网和 MSVC Build Tools。

Nuitka 不设置 `sys.frozen`，程序通过 `__compiled__` 判断冻结环境；onefile 下配置与日志写入 exe 所在目录，而不是临时解包目录。

## 第三方许可

编码器来源、版本、许可证和 pngquant 的 GPL/商业授权要求见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。发布包含 pngquant 的版本前，需要完成相应授权合规确认。
