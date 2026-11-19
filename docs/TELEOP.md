# 键盘示教与回放

双抽屉键盘窗口与自动采集命令见 [双抽屉任务](MULTI_DRAWER.md)。例如增加 `--task OpenDrawerPairLite --instruction 'Open the bottom drawer.' --pair-layout spaced`；窗口显示当前指令和非目标抽屉状态。自动脚本也可采集，无需反复人工刷同一场景。

先确认窗口内是自己要采集的任务。没有正式人工示教前，不扩大轨迹数量。Open和Close各先做1条，回放与数据核对通过后再采5–10条。

```powershell
Set-Location D:\Robotics\Pi05-RoboCasa-Cabinet
$sim = 'D:\Robotics\envs\pi05-sim-win\Scripts\python.exe'
& $sim scripts\teleop_record.py --task OpenDrawerLite
# 第二次运行时选CloseDrawerLite
```

这是Windows原生GLFW交互窗口。外部展示视角在左，两路策略相机在右。先点击窗口使其获得焦点，再按Enter开始。READY时不驱动机器人；失焦自动暂停仿真，不会在后台持续执行运动。

| 键 | 功能 |
|---|---|
| Enter | 开始一条新记录 |
| W / S | 世界坐标+Y / -Y，即朝柜体 / 远离柜体 |
| A / D | 世界坐标-X / +X |
| R / F | 上 / 下 |
| 左Shift | 加快平移；接触把手时建议松开 |
| J / L；I / K；U / O | 分别绕世界X、Y、Z轴正/负转动 |
| Tab | 开/闭夹爪；初始为打开 |
| P | 切换固定夹持姿态辅助，便于两指跨过横向把手；使用旋转键会关闭辅助 |
| Space | 暂停/继续；到步数上限后延长并继续，不重置当前轨迹 |
| F8 | 保存当前完整episode，包括失败轨迹，然后用下个seed复位 |
| F9 | 丢弃，保留partial和原因，然后复位 |
| Esc / 关闭窗口 | 退出；未保存的episode保留为partial |

建议先在高处调整姿态，再降至把手高度、缓慢接近。夹爪上下跨住横向把手后按Tab闭合，用S拉开、W推回。根据前视和腕部相机调整位置，避免仅看展示相机。成功判据显示在窗口中；开抽屉≥0.95、关抽屉≤0.05，建议稳定保持10步以上后保存。

P键只指定一个固定的末端姿态，不自动查找把手、不自动移动到把手、不自动完成任务。该辅助写入元数据；原始数据保存实际执行动作。

默认每1200个模拟控制步（60秒模拟时间）暂停提醒一次。到上限后，标题显示 `LIMIT - SPACE TO EXTEND`，按Space再增加1200步并从当前位置继续；F8仍可保存，F9仍可丢弃。标题会分别标明手动暂停、失焦、上限和录制状态。旧版到上限只能保存或丢弃，Space也无法继续，这个交互现已修复。保存前可多次延长，不会清空已采数据。

如果需要不受时长限制地练习和采集，用 `--max-steps 0`；长轨迹会持续占用磁盘，完成后及时F8保存。该参数只影响采集提醒，不改变后续模型评测的控制步预算。

```powershell
& $sim scripts\teleop_record.py --task OpenDrawerLite --max-steps 0
```

视频按20FPS记录模拟时间；失焦或手动暂停的墙钟间隙不增加视频帧。HUD、HDF5和JSON保留来源；开发时 `--operator agent_ui_check` 的记录不算人为示教，转换器会拒绝。

每次保存后，终端打印实际输出路径。先回放该文件：

```powershell
& $sim scripts\replay_episode.py data\raw\teleop\实际episode目录\episode.hdf5 --output outputs\NEW_TELEOP_REPLAY
```

回放只执行保存动作，不重新运行脚本策略。严格模式检查相同XML、seed和初始状态，逐步比较关节位置与抽屉开度。当前回放验证限同机同版本；跨机器需处理资产路径和版本差异后另验，不声称跨版本物理确定性。

已验证：三视角OpenGL窗口帧缓冲；Enter/F8保存与新seed复位；40步键盘UI检查的原始数据与动作回放（误差0）；synthetic held-key控制检查能移动EEF。人工完成整个开/关任务仍需操作者实际示教；开发检查不计入训练集。

2026-11-18修复后，用真实RoboCasa环境和录制器、进程内合成按键事件验证：上限暂停、Space延长同一条轨迹、失焦暂停、手动暂停/继续、F8保存复位、F9丢弃复位及不限时模式。此项检查验证采集主循环，不代表再次验证系统原生键盘事件投递；报告见 `results/teleop_time_limit_check.json`。

首条人工保存记录为 `OpenDrawerLite_s0_20261118_231404_647900`：1200动作/1201观测，归一化开度0.220491，任务未成功。动作回放最大关节误差8.07×10⁻⁹rad、开度误差7.98×10⁻¹⁰；转换为独立LeRobot核验集后，1200帧图像/状态/动作/语言/时间戳逐帧核对通过。它是完整、可回放的失败尝试，未归入成功SFT训练集；不需要重新采集来证明保存功能有效。
