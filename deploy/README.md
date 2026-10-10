# 问砺 · 深度研究智能体：运行与部署

应用由静态网页、FastAPI 和独立 Worker 管理进程组成。浏览器只访问一个域名，`/api/v1` 由 Nginx 转发；API 与数据库不开放公网端口。管理进程按 FIFO 同时执行最多 5 项研究，另有 10 项等待名额，一项研究从占槽开始最多运行 60 分钟。

现有 Notebook 入口继续可用。网页只复用 `deep_research` 原图并增加观测，不复制研究算法。生产默认调用真实 Agent；测试 runner 只能由测试显式注入。

## 1. 配置研究引擎

将仓库的 `comfig.yml.example` 复制为 `deploy/secrets/config.yml`，填写模型与搜索服务密钥，保持原有角色与配置结构。示例文件名的 `comfig` 是仓库原名。配置模板里的模型名也应根据自己的服务商可用模型确认，不能假定账号已有调用额度。

研究配置目录只有 Worker 容器可读，API 和前端不挂载。不要将密钥放到 `VITE_*` 环境变量中，也不要提交 `config.yml`、`.env`、数据库或证书私钥。用户界面仅接收公开研究事件；LangSmith 追踪遵循用户的环境配置，不由网页适配强制关闭。

如需 LangSmith，把已配置好的项目 `.env` 放在 `deploy/secrets/.env`（可以从根目录的 `env.example` 复制后填写）。Worker 的每项研究在导入模型图前加载 `.env`：优先 `WENLI_AGENT_ENV_FILE` 指定文件，否则查 `CONFIG_PATH` 同目录的 `.env`，再查仓库根 `.env`。显式进程环境变量优先，不被文件覆盖；因此既有启动脚本若设置过 `LANGSMITH_TRACING=false` 或 `LANGCHAIN_TRACING_V2=false`，应移除或按需要改为 true。API 不加载这些追踪密钥。LangSmith 会接收其配置启用的研究调用数据，与浏览器公开事件白名单是两条独立通道。

不配置 `.env` 时仍可运行研究；显式指定 `WENLI_AGENT_ENV_FILE` 却不存在时会报配置错误。修改追踪设置对之后启动的研究子进程生效，不能补录已经执行且未开启追踪的调用。

每项研究退出前主动等待最多 5 秒提交追踪尾部事件；默认 `LANGSMITH_USE_DAEMON=true`，用户显式环境或 `.env` 设置优先。管理进程收到研究结果后再给进程最多 5 秒退出宽限，后台线程持续阻塞时清理进程树并保留结果，释放执行槽。强制取消、故障或追踪网络持续不可用时，尾部追踪可能不完整，已持久化的网页成果仍保留。容器以 UID/GID 10001 运行，需确保该身份可读取挂载的配置与 `.env`，不要使用全员可写权限。

## 2. 在装有 Docker 的机器上试运行

以下命令在仓库根目录执行，适用于服务器 Bash。需要 Docker Engine、Compose 插件，以及访问包源、官方镜像源、模型和搜索服务的网络。

```bash
mkdir -p deploy/secrets deploy/tls
cp comfig.yml.example deploy/secrets/config.yml
cp deploy/.env.example deploy/.env
# 编辑 deploy/secrets/config.yml 后再启动。
docker compose --env-file deploy/.env -f deploy/compose.yaml build
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python -m server.admin_cli create admin --role admin
```

账号命令会隐藏输入密码，首次网页登录必须改密。访问 `http://localhost:8080`。基础配置只绑定宿主机回环地址，适合本机测试或 SSH 隧道，不作为公网明文登录配置。如果采用隧道访问，浏览器地址必须与 `WENLI_ALLOWED_ORIGINS` 一致。

Python 运行依赖在 `requirements.lock` 中带哈希固定，前端由 `package-lock.json` 固定；基础镜像按版本和 digest 固定。后端镜像编译带 WAL 修复的 SQLite 3.51.3 并校验 SHA-256、实际运行库版本。构建失败时不要关闭生产版本检查，先核查构建日志与运行库加载路径。

## 3. 阿里云中国内地服务器上线

已确认个人备案；具体地域、实例规格、域名与备份保留期在部署准备时确定。按阿里云当时的要求完成域名实名、备案与 DNS 解析，再启用公开服务。浏览器加载字体及脚本不依赖外部 CDN。

1. 配置 `deploy/.env`：`WENLI_ALLOWED_ORIGINS=https://你的域名`、`WENLI_SECURE_COOKIES=true`，`WENLI_VERSION` 使用本次发布标识。
2. 将对应域名的证书完整链与私钥分别放在 `deploy/tls/fullchain.pem`、`deploy/tls/privkey.pem`，配置宿主机最小读取权限，并安排证书续期。
3. 安全组仅开放业务所需的 80/443，以及受限来源的运维 SSH 端口。不开放 8000、SQLite 或 Docker socket。
4. 使用生产覆盖文件启动：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.production.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.production.yaml exec api python -m server.admin_cli create admin --role admin
curl -f https://你的域名/api/v1/health/ready
```

生产覆盖配置提供 HTTP → HTTPS 跳转及 Secure Cookie。`WENLI_ALLOWED_ORIGINS` 必须是完整的 `https://域名`，不带路径；多个合法入口用逗号分隔，不支持 `*`。

API 只处于 Compose 内网，Uvicorn 信任前置代理；Nginx **覆盖** `X-Forwarded-For` 为直接客户端地址，防止客户端伪造登录限流的 IP。若后续开放 API 公网端口或接入其他代理，必须同步收紧可信代理范围。不要为 Worker 管理服务设置多个副本；五个执行槽由其内部管理。

## 4. 服务器命令管理账号

在以上 `docker compose ... exec api` 后运行相应命令：

```bash
python -m server.admin_cli create alice
python -m server.admin_cli list
python -m server.admin_cli disable alice
python -m server.admin_cli enable alice
python -m server.admin_cli reset alice
```

创建和重置均交互输入密码，不接收明文密码参数。禁用或重置会撤销已有会话；重置后重新要求首次改密。用户日常改密在网页账户菜单完成。网页管理员可以查看全部研究，但不能凭此权限终止或删除其他账号的任务。

## 5. 本地开发（Windows PowerShell）

使用 Python 3.14 与 Node.js 24。部署锁文件用于固定依赖，原 `requirements.txt` 仍服务于 Notebook。可按自己的 Python 环境习惯安装；本次开发使用工作树 `.runtime/python`，未修改全局 Python。

```powershell
python -m pip install --target .runtime/python --require-hashes -r deploy/requirements.lock
$env:PYTHONPATH = '.runtime/python;.'
$env:WENLI_DATA_DIR = 'data'
$env:WENLI_SECURE_COOKIES = 'false'
$env:WENLI_ALLOWED_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173'
$env:CONFIG_PATH = (Resolve-Path config.yml).Path
$env:STAGE = 'prod'
# 如 .env 不在 config.yml 同目录，可显式设置 WENLI_AGENT_ENV_FILE。
# 仅旧 SQLite 本地测试时使用；生产必须保留 true。
$env:WENLI_REQUIRE_SAFE_SQLITE = 'false'
python -m server.admin_cli create admin --role admin
python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

先从模板准备根目录 `config.yml`。再开两个终端，设置相同的 `PYTHONPATH`、配置和 `WENLI_*` 环境变量，分别执行：

```powershell
python -m server.worker
```

```powershell
cd web
npm ci
npm run dev
```

Vite 把 `/api` 代理到 `127.0.0.1:8000`，无需跨域 CORS。网页刷新和关闭不会取消任务。测试配置缺少有效模型密钥时，欢迎页、账号、队列功能仍可测试，但研究将明确失败，不会自动切到假报告。

```powershell
# 仓库根目录
$env:PYTHONPATH = '.runtime/python;.'
python -m unittest discover -s tests -v
# web 目录
npm test
npm run build
```

测试使用临时数据库及显式模型/研究替身，不产生真实 API 费用。部分正文能否观测取决于现有模型是否提供内容 token 回调；已完整生成的阶段成果会即时保存，页面不会展示伪造进度。

## 6. 健康检查、数据保留与故障

- `/api/v1/health/live`：API 进程存活；`/api/v1/health/ready`：数据库、迁移版本和 Worker 心跳。五个槽均忙不属于故障。
- `docker compose ... logs --tail 100 api worker web` 检查内部日志；不要公开日志，因为原引擎日志可能包含研究主题与阶段信息。
- 所有运行数据保存在名为 `wenli-data` 的持久卷中。不要用 `docker compose down -v` 清理生产服务。
- 详细事件从完成、取消、失败或中断起保留 30 天。Worker 定期清理；报告、阶段成果、资料来源与最终协作图保留到用户主动删除。
- 管理进程异常退出后，旧执行进程被清理，未结束任务标为中断，排队任务继续等待。重新生成从头开始，不复用旧图状态。
- API 或数据库故障时不能宣称新成果已保存；页面断线会重连或轮询并显示连接状态。

## 7. 备份、恢复与发布回滚

使用 SQLite backup API，不直接复制一个正在写入的 `.sqlite3` 文件：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python deploy/backup.py /data/backups/wenli-before-release.sqlite3
docker compose --env-file deploy/.env -f deploy/compose.yaml cp api:/data/backups/wenli-before-release.sqlite3 ./wenli-before-release.sqlite3
```

目标文件必须不存在，脚本拒绝覆盖已有备份；新备份通过 `integrity_check` 后才报告成功。备份包含私有报告和账号哈希，应加密存放到独立位置并限制访问；具体轮换周期留到部署时确定。

恢复前停止 API 与 Worker，保留当前数据库以及 WAL/SHM 的完整副本；在**停止状态**将已验证的备份恢复为卷中的 `/data/wenli.sqlite3`，清理旧数据库对应的 WAL/SHM，并维持 UID/GID 10001 的读写权限。重新启动 Worker，让其应用恢复与事件保留规则，再启动 API/Web 对外服务。恢复会回到备份时刻，备份后的研究不会凭空恢复。不要让新旧管理服务同时访问恢复卷。

发布前备份，保留上一版本的 `wenli-backend:<版本>` 和 `wenli-web:<版本>`。先在测试环境验收，再在维护窗口停止领取新研究、等待或明确中断正在执行的任务，更新镜像版本后启动。回滚时将 `WENLI_VERSION` 恢复旧值并以 `up -d --no-build` 启动；若数据库 schema 不向后兼容，先停止服务并恢复对应备份。当前 schema 为 v2，提供 v1 → v2 的事务迁移及数据保留测试；后续迁移必须版本化，不能把手动改表当作发布流程。

上线验收必须在目标服务器执行：首次改密、同用户及跨用户并发、排队满、单项取消、SSE 重连、报告下载、异常退出恢复、备份恢复，以及真实模型和搜索网络。仓库内的自动化测试不等同于这项验收。
