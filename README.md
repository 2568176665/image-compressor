# ImageC

一个基于 Python + Tkinter 的图片压缩工具，使用 ImageMagick 执行实际压缩，可批量处理 `jpg`、`png`、`webp` 图片。

## 功能

- 支持单文件或文件夹输入
- 支持自动推导输出目录，默认输出到输入目录下的 `output`
- 支持按目标大小（KB）压缩
- 支持输出为 `jpg`、`png`、`webp`
- 支持使用预设或自定义宽高进行缩放
- 支持多线程批量处理
- 启动时自动检查并准备 ImageMagick 运行环境

## 界面说明

- 顶部区域用于选择输入路径、输出路径、目标大小、输出格式和缩放参数
- 中间显示整体进度条
- 底部日志区会显示 ImageMagick 检查过程、压缩进度和完成信息

当前版本已移除单独的运行时状态文本和状态栏文本，相关提示统一写入日志区。

## 使用方式

1. 运行 `image_compressor.py`，等待程序完成 ImageMagick 检查
2. 选择单张图片或图片文件夹
3. 设置输出目录、目标大小、输出格式和缩放参数
4. 点击“开始压缩”
5. 在日志区查看处理进度和结果

## 文件

- [image_compressor.py](/d:/Code/ImageC/image_compressor.py)：主界面与压缩流程
- [imagemagick_manager.py](/d:/Code/ImageC/imagemagick_manager.py)：ImageMagick 检查、下载与更新逻辑

## 说明

- 可执行文件可通过 UPX 进一步压缩体积
