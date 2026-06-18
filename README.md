# ImageC

基于 Python + Tkinter 的桌面图片压缩工具，使用 ImageMagick 执行实际压缩，支持批量处理 `jpg`、`png`、`webp`。

## 功能

- 支持单文件或文件夹输入。
- 支持自动推导输出目录，默认输出到输入目录下的 `output`。
- 支持按目标大小（KB）压缩。
- 支持输出为 `jpg`、`png`、`webp`。
- 支持预设或自定义宽高缩放。
- 支持多线程批量处理，并带有可取消的压缩流程。
- 启动时自动检查并准备 ImageMagick 运行时。

## 项目结构

- `src/imagec/main.py`：应用入口。
- `src/imagec/ui.py`：Tkinter 界面与交互。
- `src/imagec/config.py`：配置、日志和用户目录路径策略。
- `src/imagec/compression.py`：压缩调度、策略和取消逻辑。
- `src/imagec/subprocess_utils.py`：统一子进程执行与终止。
- `src/imagec/runtime.py`：ImageMagick 检查、下载和运行时状态封装。
- `main.py`：根目录启动入口薄包装。

## 运行

```bash
uv run python main.py
```

配置和日志默认优先尝试写入程序目录；如果目录不可写，会自动回退到用户可写目录。

## 测试

```bash
uv run pytest
```

## 打包

```bash
uv run python build.py
```

可选参数：

- `--clean-only`：只清理构建产物。
- `--skip-clean`：跳过构建前清理。
- `--onefile`：输出单文件 EXE。
