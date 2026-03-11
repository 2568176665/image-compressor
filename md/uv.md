| 命令        | 作用说明 |
|-------------|------------------------------------------------|
| `uv run`    | 运行 Python 脚本或命令，自动解决依赖 |
| `uv init`   | 初始化新项目，生成 `pyproject.toml` |
| `uv add`    | 添加依赖（类似 `pip install`，并更新锁文件） |
| `uv remove` | 移除依赖 |
| `uv sync`   | 根据锁文件同步环境（类似 `poetry install`） |
| `uv lock`   | 生成或更新锁文件 |
| `uv pip`    | 提供 pip 兼容接口，可直接用 pip 命令 |
| `uv python` | 管理 Python 版本（下载、切换） |
| `uv venv`   | 创建虚拟环境 |
| `uv build`  | 构建包（生成 wheel/sdist） |
| `uv publish`| 发布到 PyPI |
| `uv tool`   | 安装并运行 Python 工具（类似 `pipx`） |
