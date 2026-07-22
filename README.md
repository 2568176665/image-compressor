# ImageC

基于 Python、Pillow 和 Tkinter 的桌面图片压缩工具，支持批量处理 `jpg`、`png`、`webp` 和 `avif`。

## 功能

- 支持单文件或文件夹输入，文件夹扫描包含 AVIF。
- Pillow 负责图片读取、EXIF 方向校正和等比例 LANCZOS Resize。
- JPG 使用 Jpegli `cjpegli`，PNG 使用 `pngquant` + `oxipng`，WebP 使用 `cwebp`，AVIF 使用 `avifenc`。
- JPG、PNG、WebP、AVIF 均支持输入和输出；透明图片输出 JPG 时使用白色背景。
- 通过编码器大小上限参数和 Resize 重试保证不生成超过最大大小的文件。
- “最大大小 (KB)” 是硬上限：先在原始尺寸下选择视觉质量合格的最小候选，只有无法同时满足质量和上限时才强制进一步压缩或缩放。
- 内置 SSIMULACRA2 感知评分，视觉质量可选关闭、高质量 (80)、优质 (85，默认) 和视觉无损 (90)；视觉优先模式会增加批量处理时间。
- 输出不保留原图元数据；任务支持批量并发（默认最大 4 线程）和取消。

当前发布包只提供 Windows x64 编码器。Pillow 的 AVIF 读写在本项目中按 8-bit 图片处理，不用于 HDR/10-bit 保真传输。

## 运行

```bash
uv run main.py
```

启动时会校验 `src/third_party/codecs/windows-x64/manifest.json` 及编码器、SSIMULACRA2 评分工具的 SHA-256，并检查编码器是否可以运行。旧版资源缺少评分工具时会安全回退到仅限制文件大小的模式；资源校验失败时，开始按钮会保持禁用。

## 测试

```bash
uv run pytest
```

## 打包

```bash
uv run build.py
uv run build.py --onefile
```

默认生成 onedir 包(启动速度更快)；`--onefile` 生成单文件 EXE。两种模式都会内置编码器资源。打包前会校验资源清单，onedir 构建完成后还会再次校验输出目录。

## 第三方许可

编码器来源、版本、许可证和 pngquant 的 GPL/商业授权要求见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。发布包含 pngquant 的版本前，需要完成相应授权合规确认。
