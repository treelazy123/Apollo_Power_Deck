# Power Deck 上位机 GUI

适用于 Windows 的功耗、深度图监控和 WiFi 消息界面。需要 Python 3.10+ 和 [uv](https://docs.astral.sh/uv/)。运行时仅依赖 Python 标准库；图形界面使用 Tkinter。

## 从源码目录运行

在本目录中执行：

```powershell
uv run deck-gui
```

`deck-gui` 会打开监控界面，提供实时功耗曲线、深度预览和数据记录功能。 功耗卡片同时显示 ESP32-C6 读取的 WiFi RSSI（dBm）；记录时写入 `power.csv` 的 `rssi_dbm`、`rssi_valid` 列。旧固件未发送 RSSI 字段时显示 N/A。C6 IP 留空即可自动发现同一局域网中的 Power Deck；发现后界面会显示设备 IP。也可以手动填写 IP。GUI 监听 UDP 5005，并向 C6 UDP 5006 发送 `PDHELLO1` 发现报文。

## 安装和分发

在本目录中构建 wheel，然后将生成的文件复制到装有 Python 3.10+ 和 uv 的 Windows 电脑：

```powershell
uv build
uv tool install .\dist\power_deck_tools-0.1.0-py3-none-any.whl
deck-gui
```

也可以将源码目录复制到目标电脑，然后在该目录运行 `uv tool install .`。本项目没有第三方运行时依赖。使用 `deck-gui` 时，所用 Python 发行版必须包含 Tkinter。

Windows 防火墙需要允许本程序接收 UDP 5005 端口的数据。自动发现使用 UDP 广播，因此电脑和开发板需要位于支持广播互通的同一局域网；若网络禁用了广播，可在界面中手动填写 C6 IP。监控界面会在新的记录目录中保存 `power.csv`、`depth.csv` 和原始帧文件，不会覆盖已有目录。

## 命令选项

运行 `uv run deck-gui --help` 查看 GUI 的选项；使用 `uv run deck-gui --board 192.168.137.66` 可预填 C6 IP。


GUI 底部的“序号缺口 / 估算丢帧”按有效 DPT1 帧的 32 位序号计算：估算丢帧率 = 序号缺口 ÷（已收到帧数 + 序号缺口）。新设备或新 session 会重新开始统计；最近的乱序帧会在有限窗口内修正。此比例只覆盖本 session 中首个和最新有效帧之间的序号范围，不计开始前或结束后的未知帧，也不能区分 C6 主动丢帧和 WiFi/UDP 丢帧。

## 向 Power Deck 发送 WiFi 消息

1. 使用 ESP-IDF 重新构建并烧录本次 C6 固件。STM32 固件无需修改，旧的 `bench_artifacts` C6 镜像不具备消息接收功能。
2. 运行 `uv run deck-gui`，连接 C6。留空 IP 时，需等自动发现到设备；也可以手动指定 C6 IP。
3. 在“WiFi 消息”中输入任意文本，点击“发送消息”或按 Enter。单条上限为 512 个 UTF-8 字节，中文通常每字占 3 字节。暂不定义具体指令。
4. 串口监视器会出现 `net_rx: PC message id=... from=... bytes=... text=...`。上位机收到板端确认后显示“板端已接收”。

“已发送”只表示电脑发出了 UDP 数据报；“板端已接收”表示 C6 已处理并确认这条消息。2 秒未收到确认时提示超时，不自动重发；确认包本身丢失时，板端仍可能已经收到，可看串口核对。发送不阻塞 GUI，也可在功耗与深度图接收期间使用。断开连接时禁用发送。

消息复用现有发现端口：电脑从接收 socket 向 C6 UDP 5006 单播发送 `PDMSG1`（6 字节）+ 消息 ID（4 字节小端）+ UTF-8 文本。C6 只处理当前发现租约对应的电脑 IP/端口发来的消息，返回 `PDACK1` + 相同消息 ID（共 10 字节）。消息不改变流目的地址或设备配置。“帧类型/重新烧录”仍为前端预留。

板端接收入口位于 `main/Src/net_rx.c` 的 `net_rx_task()`；`receive_pc_message()` 负责消息校验、打印和确认。接收任务与发送任务独立，发送任务通过 `net_rx_get_status()` 获取目的地址快照。

## GUI 文件

- `src/deck_gui.py`：窗口、功耗曲线、深度预览和操作按钮。
- `src/deck_gui_backend.py`：UDP 收发、消息确认、记录写盘和接收统计。
- `src/depth_protocol.py`：GUI 使用的分片重组、深度帧解析和 CRC 校验。
- `src/__init__.py`：Python 包入口，配合 `pyproject.toml` 提供 `deck-gui` 命令。

源码包使用当前的 `src/` 目录。也可在 `tool/` 目录执行 `python -m src.deck_gui` 启动。
