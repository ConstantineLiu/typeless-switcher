# typeless-switcher

**重置 macOS 上 Typeless 的设备 ID，把数据迁移到新账号，也可以一条命令把换号全流程自动跑完。**

[English](README.md) | 简体中文

> 设备重置、逆向出的 API 调用和导出/导入工具基于 **Kartone** 的 [estarpro1022/typeless-reset-device](https://github.com/estarpro1022/typeless-reset-device)（MIT 协议）。本项目在此基础上新增了一键迁移、首次登录、邮箱自动登录和 Gmail 验证码自动获取。详见[致谢](#致谢)。

> [!IMPORTANT]
> **支持的平台与邮箱**
> - **仅支持 macOS。** 脚本依赖 macOS 钥匙串、`osascript`、`open` 命令和 Typeless 在 macOS 上的文件布局。Windows / Linux 用户需要自行修改代码。
> - **仅支持 Gmail，通过 IMAP 读取。** 验证码自动获取靠应用专用密码经 Gmail 的 IMAP 服务读收件箱，其他邮箱不在支持范围内。如果用的是其他邮箱，请先自行确认它是否支持 IMAP 访问和应用专用密码，再修改 `gmail_code.py`。
> - 别名方案依赖 Gmail 会忽略地址里的点号（发往 `y.ou@gmail.com` 的邮件会进 `you@gmail.com`）。大多数其他邮箱没有这个特性。

## 免责声明

本工具是基于逆向分析的非官方工具，与 Typeless 官方没有任何关系，也未经其认可。它会修改本地应用数据，并调用 Typeless 的私有接口。Typeless 以后的更新可能让它失效，使用它也可能违反 Typeless 的服务条款。风险和责任由使用者自行承担，重要数据请先备份。

## 背景

> 测试环境：Typeless v2.0.0，macOS。

Typeless 每次请求都会带上一个 **Device ID**，服务端用它限制同一台电脑能登录的账号数量。超出限制后登录会报错：

```
The number of users logged into this device has exceeded the limit.
```

本仓库提供：

| 工具 | 作用 |
|------|------|
| `reset-device-macos.sh` | 清除 Device ID，让服务端把这台 Mac 当成新设备 |
| `export.py` / `import.py` | 把词典（云端）、历史记录和录音（本地）从一个账号搬到另一个账号 |
| `reset-and-migrate.sh` | 一条命令跑完「导出 → 重置 → 登录新账号 → 导入」 |
| `web_login.py` | 在干净的 Chrome 会话里用邮箱登录 Typeless，自动填验证码，再把登录态交回 app |
| `gmail_code.py` | 通过 IMAP 从 Gmail 读取 Typeless 验证码（也可以单独使用） |

## 环境要求

- macOS，Typeless 安装在 `/Applications/Typeless.app`
- [uv](https://docs.astral.sh/uv/)，Python 3.13+
- Google Chrome。`web_login.py` 通过 Playwright 驱动本机已安装的 Chrome，每次使用全新的临时配置，不会碰你平时用的配置，也不需要额外下载浏览器。
- Node.js（用来修改 `app-storage.json`）
- `trash` 命令。较新的 macOS 自带；旧系统可以 `brew install trash`。一键脚本删除文件时都是移到废纸篓，所有改动都能恢复。
- 自动登录需要：一个开启了两步验证的个人 Gmail 账号

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # 安装 uv
uv sync                                           # 安装 Python 依赖
```

## 快速开始

### 方式一：一键迁移（推荐）

**一次性配置：把 Gmail 应用专用密码存进钥匙串**

1. 为 Google 账号开启两步验证。
2. 在 <https://myaccount.google.com/apppasswords> 创建应用专用密码。
3. 存入 macOS 钥匙串。账号填 Gmail 的原始地址，**不带点号**：

   ```bash
   security add-generic-password -s "typeless-reset-gmail" -a "you@gmail.com" -w "<16 位应用专用密码>"
   ```

**第一次使用（Typeless 还没登录任何账号）**

这时没有账号可以导出，脚本会跳过导出和词典导入，直接登录你的第一个别名（`y.o.u.rname@gmail.com`）。它需要知道你的 Gmail 地址，有两种给法：

```bash
# 交互式：脚本会在终端里问你 Gmail 地址
bash reset-and-migrate.sh

# 非交互式，比如由其他脚本或 AI Agent 调用：把地址作为参数传入
bash reset-and-migrate.sh you@gmail.com
```

在非交互环境里既没传地址、也没法提问时，脚本会直接报错并给出用法，不会卡在那里等输入。

**每次换号时**，先确认 Typeless 登录着当前账号，然后运行：

```bash
bash reset-and-migrate.sh
```

执行过程：

| 步骤 | 内容 |
|------|------|
| 预检 | 确定 Gmail 收件箱，检查钥匙串配置。缺什么就在这里停下，此时还没有做任何改动 |
| 1 | 把词典、数据库、录音和设置导出到 `backup_<时间戳>/`（第一次使用时跳过） |
| 2 | 退出 Typeless |
| 3 | 重置 Device ID，清除本地登录态（移到废纸篓，可以恢复） |
| 4 | 选出下一个没用过的 Gmail 点号别名，在干净的 Chrome 会话里网页登录，从 Gmail 取验证码并填入，把 `typeless://` 回调交给 app |
| 5 | 把词典导入新账号（第一次使用时跳过），并把本地全部历史记录改归新账号 |
| 6 | 重启 Typeless |

Gmail 地址的取值顺序是：命令行参数 → `GMAIL_USER` 环境变量 → 当前登录的账号 → 在终端里提问。地址里的点号会自动去掉，所以 `y.ou@gmail.com` 和 `you@gmail.com` 会被当成同一个收件箱。

### 方式二：手动流程

```bash
uv run python3 export.py                       # 1. 登录着旧账号时导出
bash reset-device-macos.sh                     # 2. 重置 Device ID
                                               # 3. 在 Typeless 里登录新账号
uv run python3 import.py backup_<时间戳>/       # 4. 导入到新账号
```

只想解决设备数量限制的话，单独跑第 2 步就够了。

## 邮箱别名

Gmail 会忽略地址里的点号，所以 `you@gmail.com`、`y.ou@gmail.com`、`y.o.u@gmail.com` 都进同一个收件箱，但在 Typeless 看来是三个不同的账号。

`web_login.py` 把所有加点方式排成一个固定顺序，每次取下一个没用过的：

- 从 3 个点（`MIN_DOTS`）起步，第一个是把点加在最前面：`y.o.u.rname@gmail.com`
- 同样点数的方案按字典序排；用完了再用 4 个点、5 个点，依此类推，1 个点和 2 个点的方案排在最后
- 每个登录成功的别名都会记进 `used_aliases.txt`，这里面和 `backup_*/` 里出现过的别名都会跳过。所以新用户一定从 `y.o.u.rname` 开始；某个别名用过了，就自动往后挪一个。全部用完时脚本报错停下，不会重复使用

别名的数量取决于 Gmail 用户名（`@` 前面去掉点号的部分）的长度。*n* 个字符之间有 *n − 1* 个空位可以插点，一共有 2^(n−1) − 1 个别名。脚本会自动读取你的地址长度，不需要额外配置：

| 用户名长度 | 3 个点的别名 | 全部别名 |
|-----------|-------------|---------|
| 6（Gmail 下限） | 10 | 31 |
| 8 | 35 | 127 |
| 10 | 84 | 511 |
| 12 | 165 | 2,047 |
| 16 | 455 | 32,767 |

想换一个起步点数，修改 `web_login.py` 别名部分开头的 `MIN_DOTS` 即可。名字太短放不下这么多点时，脚本会自动用能放下的最多点数。

## 原理（逆向分析）

### Device ID

Device ID 来自 macOS 原生动态库 `libUtilHelper.dylib`，读取顺序是：

```
1. 钥匙串     → 找到就用
2. 本地缓存   → 找到就用，并同步回钥匙串
3. 都没有     → 生成新 UUID，同时写入两处
```

| 存储 | 位置 |
|------|------|
| 钥匙串 | service `now.typeless.desktop.deviceIdentifier`，account `now.typeless.desktop.security.auth_key` |
| 本地缓存 | `~/Library/Application Support/now.typeless.desktop/device.cache` |

把这两处清干净，Typeless 下次启动就会生成新的 Device ID。

### 词典 API

词典只存在 Typeless 服务端。`export.py` / `import.py` 直接调用接口：

1. 解密 `user-data.json`（electron-store 加密：两轮 PBKDF2 + AES-256-CBC）
2. 构造签名请求头（HMAC-SHA1 签名，加上 CryptoJS AES 加密的 `X-Authorization`）
3. 调用 `/user/dictionary/list`（导出）和 `/user/dictionary/add`（导入）

### 本地数据库

`typeless.db` 里 `history` 和 `history_v2` 表的每一行都有 `user_id` 字段。迁移时把它改成新账号的 id，录音文件（`.ogg`）不需要改。

### 邮箱登录

app 上的 "Sign in with email" 按钮会在浏览器里打开 `https://www.typeless.com/login/email?registration_origin=desktop_app`。验证通过后，网页跳转到 `typeless://auth/...`，macOS 把这个链接交给 app 完成登录。`web_login.py` 用 Chrome DevTools Protocol（`Page.frameRequestedNavigation`）截下这次跳转，自己用 `open` 打开，所以不用去点浏览器的「要打开 Typeless 吗」确认框。浏览器每次都用全新配置，不会被之前的网页登录状态干扰，也就不用先退出网页版。

### 加密细节

```
加密密钥 = PBKDF2-SHA256(SHA256("darwin-{arch}").hex() + "Typeless", "typeless-user-service", 10000, 32)
逐值密钥 = PBKDF2-SHA512(加密密钥, IV.toUtf8(), 10000, 32)
文件格式 = [16 字节 IV] + ':' + [AES-256-CBC 密文]
```

`arch` 为 `arm64`（Apple Silicon）或 `x64`（Intel），自动检测。

## 常见问题

- **卡在第 4 步**：`web_login.py` 会把出错那一刻的页面截图存到 `web_login_debug.png`，可能是 Typeless 改了登录页。
- **提示「Keychain 里没有 ... 的 Gmail 应用专用密码」**：钥匙串里没有对应条目，检查 `-a` 填的是不是不带点号的 Gmail 地址。
- **收不到验证码**：确认 Gmail 账号可以用 IMAP，应用专用密码没有失效。

## 文件结构

```
├── reset-and-migrate.sh    # 一键迁移
├── web_login.py            # 邮箱自动登录 + 别名选择
├── gmail_code.py           # Gmail IMAP 验证码读取
├── reset-device-macos.sh   # 重置 Device ID
├── export.py               # 导出词典、数据库、录音、设置
├── import.py               # 导入到新账号
├── crypto_utils.py         # 解密与 API 请求签名
└── pyproject.toml
```

## 致谢

- **Kartone** 的 [estarpro1022/typeless-reset-device](https://github.com/estarpro1022/typeless-reset-device)（MIT）：本 fork 的上游项目，设备重置、逆向出的 API 调用和导出/导入工具都来自这里。
- 上游项目致谢过、并借鉴了其实现的项目：
  - [mercy719/typeless-migrator](https://github.com/mercy719/typeless-migrator)
  - [schummiking/free-typeless](https://github.com/schummiking/free-typeless)

## 许可证

[MIT](LICENSE)。按 MIT 协议要求，保留了上游的版权声明。
