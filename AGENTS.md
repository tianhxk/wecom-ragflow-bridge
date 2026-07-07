# Repository Guidelines

## Project Structure & Module Organization

本仓库是企业微信、微信客服、WorkBot 与 RAGFlow/Dify 的 Python 桥接服务。核心代码位于 `src/`：`main.py` 负责启动与编排，`config.py` 读取环境变量，`chat_client.py` 统一聊天后端，`ragflow_client.py`、`dify_client.py`、`wecom_api.py`、`wechat_kf.py`、`workbot.py` 分别处理外部通道。`media/` 存放本地媒体样例或运行产物。根目录包含 `Dockerfile`、`docker-compose.yml`、`docker-compose.example.yml` 和 `requirements.txt`。

## Build, Test, and Development Commands

- `python -m venv .venv`：创建本地虚拟环境。
- `pip install -r requirements.txt`：安装运行依赖。
- `python -u src/main.py`：从本机启动服务，默认读取 `config/.env`。
- `docker compose up -d --build`：构建并后台运行容器。
- `docker compose logs -f`：跟踪服务日志。
- `python -m py_compile src/*.py`：快速检查 Python 语法错误。

## Coding Style & Naming Conventions

使用 Python 3.12，保持 4 空格缩进。模块、函数、变量使用 `snake_case`，类使用 `PascalCase`，常量和环境变量使用 `UPPER_SNAKE_CASE`。异步 I/O 代码优先沿用 `asyncio`、`aiohttp`、`websockets` 的现有模式。日志使用模块级 `logger`，避免在日志中输出完整密钥、Token 或用户敏感内容。

## Testing Guidelines

当前仓库未包含正式测试目录。新增逻辑时优先补充 `tests/` 下的 `pytest` 用例，测试文件命名为 `test_*.py`。对外部服务调用应使用 mock 或 fake client，避免依赖真实企业微信、RAGFlow、Dify、MinerU 或 MySQL。提交前至少运行 `python -m py_compile src/*.py`，有测试时运行 `pytest`。

## Commit & Pull Request Guidelines

现有提交历史以中文说明为主，常见格式是简短动词短语或编号说明，例如“删除无关文件”“修订readme，更新了环境变量说明”。提交信息应说明用户可见变化和影响范围。PR 应包含变更摘要、配置项变化、验证命令结果；涉及 webhook、Docker 端口或环境变量时，注明迁移步骤。不要提交 `.env`、真实密钥、Token、数据库密码或生产媒体文件。

## Security & Configuration Tips

本项目依赖 `config/.env` 和容器挂载的 `./.config:/opt/app/config`。新增配置时同步更新示例文件和 README。默认端口、webhook path、外部 Docker 网络名称变更都可能影响部署，请在 PR 中显式标注。
