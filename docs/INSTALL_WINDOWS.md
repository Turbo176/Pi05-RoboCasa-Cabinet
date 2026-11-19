# Windows 原生安装与已知兼容问题

本机验证日期：2026-11-18。默认项目路径：`D:\Robotics\Pi05-RoboCasa-Cabinet`。

## 运行

在项目根目录打开 PowerShell。已有环境只做运行验证：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap_sim.ps1 -VerifyOnly
```

首次安装（需 Git、64 位 Python 3.11 和系统 MSVC 运行库）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap_sim.ps1 -BasePython D:\anconda\python.exe
```

`ExecutionPolicy Bypass` 仅作用于此启动的 PowerShell 进程。脚本不修改全局策略。不要在 base 或 yolov5 环境内直接安装依赖。

单独运行：

```powershell
$sim = 'D:\Robotics\envs\pi05-sim-win\Scripts\python.exe'
& $sim scripts\mujoco_smoke.py --viewer-seconds 6
& $sim scripts\scene_smoke.py --task OpenDrawerLite
& $sim scripts\scene_smoke.py --task CloseDrawerLite --output outputs\close_scene_smoke
```

输出为 `outputs/` 下的 MP4、PNG 和 JSON。第一条仅验证抽象滑块图形；后两条是零臂动作场景验证，不是成功控制或 π0.5 视频。完整重装脚本待其他机器验证；当前机器已验证依赖安装和对应运行命令。

## 实际遇到的问题

| 问题 | 证据与根因 | 当前处理 |
|---|---|---|
| MuJoCo `WinError 1114` | 首个 `plugin/actuator.dll` 初始化失败；Anaconda 2024 私带 MSVC 14.27，系统 14.42；进程预加载系统 `msvcp140.dll` 后正常 | `scripts/_windows_runtime.py`；不复制 DLL、不修改系统与上游 |
| PyPI robosuite 依赖不可解 | 1.5.2 wheel 强制 mink 0.0.5→NumPy<2；当前 RoboCasa 固定 NumPy2.2.5 | 固定官方源码 `5ce6643...`，其 mink 为可选项；本项目使用 OSC，不使用 mink IK |
| 标准 OpenDrawer 缺资产 | reset 找不到 `fixtures/sinks/Sink025/model.xml`；代码仓库不包含下载资产包 | 先以 Lite 自定义小布局验证任务，不把它报告为完整 benchmark；未下载厨房资产全集 |
| Windows 路径 `ValueError` | `Kitchen.edit_model_xml` 使用 `/robocasa/`、`/robosuite/` 字符串判断，生成的路径混有反斜杠 | Lite 的 `LocalAssetPaths` 保存已存在本地文件路径，调用上游处理相机后恢复规范路径 |
| 遥操作窗口创建但不显示 | MuJoCo离屏GLFW上下文把全局VISIBLE hint设为false，随后创建的窗口继承隐藏设置 | 自己的遥操作窗口先恢复默认hint并显式设VISIBLE；仍保留MuJoCo离屏相机 |
| pip check 报缺项 | RoboCasa setup 将训练/转换/硬件采集工具也列为强依赖 | 当前刻意只装可运行的仿真子集，未装 lerobot、tianshou、pygame、hidapi；`pip check` **不是通过状态**，这些工具入口暂不支持 |

当前复用了 robosuite 自动选择的 Windows WGL/GLFW 渲染，无 EGL 错误。可选机器人、MimicGen、mink 和 private macros 的警告保留，便于识别功能边界。原始日志在 gitignore 的 `work/`。

完整 RoboCasa 安装、LeRobot 转换和服务器训练应使用独立依赖配置。当前不通过 `pip install robocasa` 拉起整个训练依赖树，更不安装 GPU 版 PyTorch 到本地。WSL2 + WSLg 已检测到，但未宣称 RoboCasa 在 WSL 中完成安装/运行；其 `df` 的虚拟卷可用量不能视为物理磁盘余量。

## CPU数据工具环境（已获用户授权并安装）

`D:\Robotics\envs\pi05-data-cpu`，CPU torch2.7.1+cpu / torchvision0.22.1+cpu / LeRobot0.4.4。只用于官方Dataset API，不含模型权重与π0.5可选依赖。其 `pip check` 已通过；仿真子集的依赖边界仍见上表，不受此结果替代。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_data.ps1 -VerifyOnly
# 新机器安装（下载CPU依赖，不下载模型/示教）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_data.ps1 -BasePython D:\anconda\python.exe
```

安装脚本先从官方CPU wheel索引安装固定torch/torchvision，再安装锁定依赖；`requirements/data-cpu.lock.txt`是当前实测解析结果。从零重装尚待另一机器验证；本机安装过程及验证均已执行。采集、回放与转换详见 `TELEOP.md`、`DATA_CONTRACT.md`。
