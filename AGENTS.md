# AGENTS.md

## 项目定位

ImageC 是一个仅面向 **Windows x64** 的 Tkinter 桌面图片压缩工具。Python 负责读取、方向校正与缩放，实际编码全部委托给 `src/third_party/codecs/windows-x64/` 下的命令行编码器。

## 目录职责

| 路径 | 职责 |
| --- | --- |
| `main.py` | 入口脚本，注入 `src` 到 `sys.path` 后调用 `imagec.main.main` |
| `src/imagec/main.py` | 进程级初始化（DPI 感知、日志、配置路径） |
| `src/imagec/ui.py` | Tkinter 界面与线程调度，不包含编码逻辑 |
| `src/imagec/compression.py` | 编码策略、Resize 重试链、输出命名、并发批处理 |
| `src/imagec/runtime.py` | 编码器清单校验、版本探测、就绪状态 |
| `src/imagec/config.py` | 配置与日志路径解析、持久化 |
| `src/imagec/subprocess_utils.py` | 子进程执行、取消、超时、输出收集 |
| `src/third_party/codecs/windows-x64/` | 内置编码器、许可证与 `manifest.json` |
| `build.py` | PyInstaller 打包与产物校验 |

## 编码链路约定

- 所有输入先经 Pillow 转为临时 PNG（`_save_transform`），再交给外部编码器。
- 目标大小是硬上限，由编码器参数与 Resize 重试链共同保证；任何输出超过上限都视为失败。
- 输出命名规则：默认**从不覆盖**已存在的文件，冲突时追加 `-1`、`-2`；只有用户显式开启 `overwrite` 才复用原文件名。
- 当输出路径与源文件相同时，即使开启 `overwrite` 也必须拒绝，避免破坏原图。
- 临时目录使用系统临时目录，不得放在输出目录内。

## 第三方资源

- 新增或升级编码器后必须重新生成 `manifest.json` 的 `files` 与 `versions`，并同步 `THIRD_PARTY_NOTICES.md`。
- 许可证文本的哈希按 LF 归一化计算，以兼容 Git 的 autocrlf。
- `pngquant` 是 GPL-3.0-or-later 或商业授权，属于发布前的硬性合规项。
- `cjpegli` 停留在 libjxl 0.11.2：0.12.0 已移除 jpegli 代码，而 `google/jpegli` 尚无二进制发布。

## 开发命令

```bash
uv sync                 # 安装依赖
uv run pytest           # 运行测试（含编码器冒烟测试）
uv run main.py          # 启动界面
uv run build.py         # onedir 打包
uv run build.py --onefile
```

## 修改约束

- 不要绕过 `CompressionService` 直接在 UI 层调用编码器。
- 后台线程不得直接操作 Tk 控件，必须通过 `root.after` 回到主线程。
- 新增配置项时，需同时更新 `DEFAULT_CONFIG`、`load_config`、`save_config` 与配置往返测试。
- 涉及数据安全的逻辑（覆盖、命名、临时文件清理）必须有对应回归测试。
