# 服务故障共现研判

时序共现关联的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 校时凭据与方案（可行区间、冲突链、发布/撤销）→ 参数化分析（异步 Python worker，区分确定/待定跟随）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery，以及 CalibrationScheme 校时方案、CalibrationCredential 校时凭据、CredentialRevocation 撤销登记。

### 校时与依赖失效
- 凭据语义：`source→target` 断言 `offset[target]-offset[source] ∈ [lower, upper]`（分钟），参考服务锚定 0；后端用差值约束闭包求各服务相对参考服务的可行修正区间，以及任意两服务的可行时差（包含间接组合）。
- 可行修正下时滞落在 `(0, window]` 的跟随才计为确定；只有部分修正下成立的列为待定。只有全部可行校时下都成立的跟随进入确定关联。
- 凭据矛盾时不发布、不分析，并列出冲突链（每条边对应的凭据编号与不等式）；数据集内服务与参考服务不连通时拒绝联合分析。
- 方案先登记草稿，发布后才能被试验选用；原事件保留，试验保存创建时的校时快照与修订号。
- 撤销凭据或方案会提升方案修订号，立即失效依赖试验（含已批准）与分发计划；已发归档保留但标注依据撤销。撤销后拒绝新的批准与分发，不恢复旧资格。
- 撤销与批准/分发/worker 写回通过方案行锁串行；撤销登记表对凭据唯一，重试不重复登记；worker 中断恢复时按最新方案状态处理失效试验。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18212；后端文档 http://localhost:19212/docs；数据库宿主端口 17712。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、流程发布与撤销、分发、暂停、读取与下载|
|analyst@demo.local|Demo123!|接入、登记校时方案草稿与凭据、执行、读取与下载；不能发布、撤销、批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载（含校时方案、可行区间与冲突链）|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；PostgreSQL 16；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed；CalibrationStatus：draft/published/revoked；CredentialStatus：active/revoked。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=incident-links；FRONTEND_PORT=18212；BACKEND_PORT=19212；DB_PORT=17712；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1013/，源码不含日志/截图/测试报告。
校时相关测试运行：`cd backend && python -m pytest ../test-artifacts/gb-1013/tests/test_business.py`。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
