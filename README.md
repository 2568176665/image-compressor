# ImageC

基于 Python、Pillow 和 Tkinter 的桌面图片压缩工具，支持批量处理 `jpg`、`png`、`webp` 和 `avif`。

## 功能

- 支持单文件或文件夹输入，文件夹扫描包含 AVIF。
- Pillow 负责图片读取、EXIF 方向校正和等比例 LANCZOS Resize。
- JPG 使用 Jpegli `cjpegli`，PNG 使用 `pngquant` + `oxipng`，WebP 使用 `cwebp`，AVIF 使用 `avifenc`。
- JPG、PNG、WebP、AVIF 均支持输入和输出；透明图片输出 JPG 时使用白色背景。
- 通过编码器目标大小参数和 Resize 重试保证不生成超过目标大小的文件。
- 输出不保留原图元数据；任务支持批量并发和取消。

当前发布包只提供 Windows x64 编码器。Pillow 的 AVIF 读写在本项目中按 8-bit 图片处理，不用于 HDR/10-bit 保真传输。

## 运行

```bash
uv run python main.py
```

启动时会校验 `src/third_party/codecs/windows-x64/manifest.json` 及所有编码器的 SHA-256，并检查编码器是否可以运行。资源缺失或校验失败时，开始按钮会保持禁用。

## 测试

```bash
uv run pytest
```

## 打包

```bash
uv run python build.py
uv run python build.py --onefile
```

默认生成 onedir 包；`--onefile` 生成单文件 EXE。两种模式都会内置编码器资源。打包前会校验资源清单，onedir 构建完成后还会再次校验输出目录。

## 第三方许可

编码器来源、版本、许可证和 pngquant 的 GPL/商业授权要求见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。发布包含 pngquant 的版本前，需要完成相应授权合规确认。
