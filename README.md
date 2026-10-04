# 湖雷出发 · 六个人的周边小旅行

独立的中文家庭旅行网站。面向从永定湖雷镇出发的 **5 位大人 + 1 岁宝宝**，页面围绕短程动物观赏、乡村平地休闲、城市公园和夜市散步组织。

五个顶部选项：澜溪生态鹦鹉观光园、培斜村乡村休闲、龙岩东山湿地公园、石锣鼓公园 + M7 街区、凤城夜市 + 沿河路。每个都有车程粗估、具体看点、推车与宝宝照护提示、弹性行程、地图搜索和来源链接。

## 本地运行

需要 Node.js 24 LTS（无第三方运行依赖）。在本目录执行：

```powershell
npm start
```

打开 `http://localhost:3000`。投票数据库自动写到 `data/ballots.json`，重启后保留。服务器默认只监听 `127.0.0.1`。若要在同一局域网手机打开，在 PowerShell 设置实际来源地址后启动：

```powershell
$env:HOST = '0.0.0.0'
$env:PUBLIC_ORIGIN = 'http://你的电脑局域网IP:3000'
npm start
```

只有网页使用的地址与 `PUBLIC_ORIGIN` 一致时才允许浏览器提交投票。必要时在系统防火墙放行此局域网端口。不要把开发服务器直接作为公网服务。

## 现有代理上的 /test 部署

如果 VPS 已有站点占用 80/443，使用这一模式。把整个项目上传到 VPS，在项目目录运行：

```bash
sudo bash deploy.sh --mode path --base-path /test --port 3100 --origin https://travel.lovenom.eu.org
```

`--origin` 填现有 HTTPS 站点的域名来源，**不带 `/test`**；`--port` 选一个未占用的高位端口。也可复制 `.env.path.example` 为 `.env` 填好参数，再运行 `sudo bash deploy.sh`。此模式仅启动 `compose.path.yaml` 中的 app，通过 Docker 发布在 **`127.0.0.1:3100`**，不会启动本项目的 Caddy、申请新证书、占用 80/443、修改已有代理配置或停止其他服务。公网地址为 `https://travel.lovenom.eu.org/test/`。

HTTPS 和证书续期继续由现有 Nginx/Caddy 处理，浏览器对页面和投票接口仍使用 HTTPS。现有代理把 `/test` 和 `/test/` 请求发到本机 `http://127.0.0.1:3100`，**保留 `/test` 前缀**；主站其他路径继续使用原配置。应用会把 `/test` 重定向到 `/test/`，页面资源、模块导入、图片标志和投票 API 都跟随 `BASE_PATH`。

将 [proxy/nginx-test.conf](proxy/nginx-test.conf) 中的两个 `location` 放进现有 HTTPS `server {}` 内，或将 [proxy/caddy-test.caddy](proxy/caddy-test.caddy) 中的匹配块放进现有域名块。它们默认端口 3100、路径 `/test`，修改参数时同步改片段。Nginx 的 `proxy_pass` **不要添加末尾斜杠**；Caddy 用 `handle`，**不要改成会剥掉前缀的 `handle_path`**。

保存代理配置后，先使用对应代理自己的配置校验，再只 reload 该代理，例如 `nginx -t` 后 `systemctl reload nginx`，或 `caddy validate --config /etc/caddy/Caddyfile` 后 `systemctl reload caddy`。这些步骤由实际部署操作者执行，本次未运行。脚本仅确认本机 app 健康；加好代理并能公开访问之前，不会声称公网部署完成。

这两个片段适用于**与 Docker 在同一 VPS、直接运行于宿主机的现有代理**。如果现有代理也在容器里，其 `127.0.0.1` 指向代理容器自身，需要接入私有 Docker 网络并改用 app 服务地址；不要为此把 3100 开到公网，也不要把现有代理直接替换成本项目 Caddy。

更新此模式时继续用同一部署命令，查看日志/停止 app 必须选对 Compose 文件：

```bash
docker compose -f compose.path.yaml ps
docker compose -f compose.path.yaml logs --tail=80 app
```

两种模式使用同一个 `family-travel_votes` 投票卷，切换时保留旧票；保持单个 app 实例，不要同时运行两种模式的 app。脚本不会自动停止另一模式的服务，需要切换时由部署操作者安排。高位端口仅用于本机代理，不需要开放云安全组的 3100 入站。

## 独立域名 HTTPS 部署

支持 Debian/Ubuntu VPS，推荐至少 1 GB 内存。把**整个 travel 目录**传到 VPS，例如 `/opt/family-travel`。无需 API 密钥、数据库密码或支付账户。

1. 在 DNS 管理中创建 `travel.lovenom.eu.org` 的 A 记录指向 VPS 公网 IPv4，使用 DNS 直连模式。若保留 AAAA，其地址也必须指向该 VPS 的可用公网 IPv6。
2. 在云厂商安全组和系统防火墙开放入站 **TCP 80、TCP 443**；UDP 443 可用于 HTTP/3。开放出站 HTTPS 以安装依赖和申请证书。
3. VPS 的 80/443 端口须可用；脚本不会停掉已有站点。若已有反向代理，需把新域名整合进现有代理。
4. 在项目目录执行：

```bash
sudo bash deploy.sh --mode standalone --base-path /
```

脚本询问证书通知邮箱，也可先复制 `.env.example` 为 `.env` 并填好 `ACME_EMAIL`。脚本会安装基础工具与 Docker 官方仓库组件、核实公共 DNS A/AAAA、拒绝端口冲突、构建并启动 Compose、等待 Caddy 自动申请 HTTPS 证书，最后尝试访问公开健康接口。已有 Docker 引擎时只补安装 Compose，不替换引擎。DNS 未生效或防火墙不通时会说明原因并停止/报出未确认状态。

证书由 Caddy 自动续期，公开地址是 `https://travel.lovenom.eu.org`。应用端口 3000 仅在 Docker 内部网络可见，Caddy 独占公网入口，Docker 内使用 `HOST=0.0.0.0`。

更新上传后的源文件并再次运行同一命令即可。投票数据保存在 `family-travel_votes` 命名卷，证书保存在 `family-travel_caddy_data`；正常 rebuild、restart 和 `docker compose down` 保留它们。**不要使用 `docker compose down -v`，这会删除这些卷。**

查看运行情况与日志：

```bash
docker compose ps
docker compose logs --tail=80 caddy app
```

## 投票规则与数据

- 单选 1 个，或多选 1–3 个不同目的地。客户端提示，服务端重新验证。
- 昵称按 Unicode NFKC、移除空白、转小写归一化；2–16 个中文、字母、数字或 `_ . -`。例如全角与半角、大小写、空格差异不能重复投票。
- **同一归一化昵称只能提交一次，提交后不能修改。**重试或换设备使用同一昵称会返回 409，不会新增票。
- 服务端仅存昵称 SHA-256、目的地 IDs、模式和提交时间，不保存原昵称或 IP。昵称哈希属于去标识数据，熟悉昵称的人仍可能猜测，不作为身份认证。
- 公开结果仅含总人数、总选择数和各目的地票数，不显示昵称。多选百分比的分母是投票人数，总和可能超过 100%。
- 页面按 5 位成人参与解释结果；这是公开的家庭讨论票，没有登录或邀请口令，无法证明投票者身份，也不会硬性限制为 5 人。超过 5 人时页面显示说明。
- localStorage 仅记住该浏览器的表单昵称；共享票数始终来自服务端，不使用浏览器存储充当数据库。

`GET /api/results` 返回汇总；`POST /api/votes` 接收 JSON；`GET /api/health` 检查存储能否读取。子路径模式下分别是 `/test/api/results`、`/test/api/votes`、`/test/api/health`。请求体上限 2 KB，同 IP 每分钟最多 8 次提交和 90 次 API 读取；错误只返回安全提示，服务器不回传堆栈和文件路径。

持久化采用进程内写队列、文件系统目录锁、同目录临时文件 `fsync`、原子 rename；Linux 同步目录元数据。锁在中断后 30 秒恢复；读到损坏数据会报错并保留原文件，不覆盖重置。部署固定为**一个 app 实例**，适合这个小规模投票；多实例、共享网络磁盘或大流量场景应迁移到真正的数据库锁/事务。

备份可停止应用后复制数据卷，不要删除卷。下面以现有代理模式为例，独立模式去掉命令中的 `-f compose.path.yaml`：

```bash
docker compose -f compose.path.yaml stop app
docker run --rm -v family-travel_votes:/data:ro -v "$PWD":/backup alpine tar -czf /backup/votes-backup.tgz -C /data .
docker compose -f compose.path.yaml start app
```

## 文件与架构

```text
public/index.html        页面、五个导航标签、独立右上角投票弹层
public/styles.css       手机竖屏优先、平板和桌面排版
public/app.js           标签切换、行程渲染、投票与结果交互
public/destinations.js  五条路线内容、地图关键词与来源
server.mjs              静态文件、HTTP API、安全响应与限流
lib/ballots.mjs         昵称规则、目录锁、持久写入和汇总
Dockerfile              非 root Node 容器
compose.yaml            私有 app + 公网 Caddy + 持久卷
compose.path.yaml       现有代理模式，仅 loopback 高位端口 app
Caddyfile               自动 HTTPS、压缩与反向代理
proxy/nginx-test.conf   添加到现有 Nginx HTTPS 站点的 /test 片段
proxy/caddy-test.caddy  添加到现有 Caddy 域名块的 /test 片段
deploy.sh               DNS/端口前置检查和 VPS 一键部署
```

## 内容边界

车程是粗略规划范围，**未查询实时路线**；以实际日期、导航、停车、天气和宝宝作息为准。动物园、乡村经营点、M7 商家、夜市活动与公园设施都需出发前确认。培斜的动物/咖啡/牧场类经营点按当日营业选择，不保证所有项目同时存在或开放；园区只安排平地短线。

图片使用东南网、福建省文旅厅、龙岩城管和福建省政府对应资料的远程链接：鹦鹉园与培斜资料照片、东山草坪开放区域图、凤城夜市历史活动照片，均附准确说明与原文来源。石锣鼓/M7 使用明确标注的简绘路线示意，不按比例、非现场照片。远程站点可能改地址或限制外链，页面有加载失败提示；历史资料不代表当前现场。公开推广或商用时应先向权利人取得适用的图片授权，或替换为自有照片。

## 交付状态

本次子路径适配未运行测试、构建、浏览器验收、代理配置校验或实际 VPS 部署；尚未确认 `/test/` 公网访问。出发前请按页面提示核实当天开放、路线与设施。部署脚本中的健康确认只在实际执行脚本时运行。
