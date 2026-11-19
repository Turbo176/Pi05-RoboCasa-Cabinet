# 双抽屉任务与小样验证

2026-11-19：在已有Windows原生环境内加入两个RoboCasa官方Drawer fixture，机器人仍为PandaOmron；没有增加依赖、下载厨房资产或公开示教。该场景是本项目的Lite布局，不属于完整RoboCasa benchmark。

## 指令与场景

| 环境 | 可选指令 |
|---|---|
| `OpenDrawerPairLite` | `Open the top drawer.` / `Open the bottom drawer.` |
| `CloseDrawerPairLite` | `Close the top drawer.` / `Close the bottom drawer.` |

这是显式指令语法：环境校验并将目标绑定到fixture，脚本通过目标fixture真值控制机械臂。它用于准备多任务数据和评测环境；目前没有学习到语言理解或π0.5推理。未知指令或环境与动词不匹配时直接报错。

| `--pair-layout` | 上层/下层中心高度 | 当前用途 |
|---|---|---|
| `compact` | 0.85 / 0.60 m | 紧凑布局，保留诊断失败；兼容首批双抽屉记录 |
| `spaced` | 1.10 / 0.72 m | 间距更大的布局，已跑通四条指令，建议使用 |

相同环境、seed、布局和柜体平移下，上下目标共享同一个机器人出生参考；开任务初始化两个抽屉都关闭，关任务初始化两个都打开。没有把目标抽屉偷偷移到机器人附近，也没有通过“只有一个抽屉开着”泄露关任务目标。初始双RGB、time/qpos/qvel及XML逐项比较，必须完全一致；开任务与关任务之间不要求相同状态。

`--scene-offset DX DY` 将整个柜体平移，单位米，各轴限定±0.15m，参数随轨迹保存并用于回放。seed另外控制上游机器人位置扰动及开度随机化。单个新seed或单个平移点只能算开发小样，不是未见位置泛化评测；尚未建立训练/验证/测试的互不重叠位置区域。

## 成功与误操作

保留官方目标判据：开度≥0.95为开成功，≤0.05为关成功。归一化基准是抽屉深度×0.55。双抽屉额外要求：非目标抽屉相对reset后开度的**全轨迹最大偏移≤0.05**，约15mm，而不是仅看终点是否复位。每个20Hz控制步计算一次；即使目标已完成，另一抽屉曾超过容差，该轨迹也不能算成功。

同时报告最终成功、末10步稳定成功、双指把手接触步数、两个抽屉的开度及非目标最大偏移。脚本上层415步、下层545步，均在600步评测预算内。视频和数据始终标注 `SCRIPTED_PRIVILEGED_STATE`。

紧凑布局初测3/4成功。下层关闭时，接触诊断发现Panda第5/6连杆碰到上层抽屉面板，导致下层停在0.0664、上层最大偏移0.39285，正确判为失败。没有放宽成功门槛、冻结非目标关节或关闭碰撞。原记录保留；增大上下间距并在高于上层抽屉0.30m处接近，得到另一套可复现的宽间距布局。

宽间距seed0四条记录均成功，非目标最大偏移3.84×10⁻⁹；四条动作回放最大关节误差1.15×10⁻¹¹rad，最大双抽屉开度误差2.46×10⁻¹¹。官方LeRobot转换及加载检查通过，共1920帧、四条不同指令。这些条件参与过控制器开发，仅是开发pilot；不据此声称π0.5成功率或稳定泛化。

第二个条件（seed1、柜体平移+0.04/-0.03m）初测3/4成功：下层关闭在hold阶段已成功，但斜向上撤离时手指钩住把手，最终又拉开至0.4886。失败轨迹和转换标签均保留。将下层关闭的退出动作改为同高度水平后退后，原位置及平移位置复核均成功，平移位置最终开度0.0164146。修复后的两条件共8条、3840帧均最终/末10步成功，反目标评分0/8成功；8条回放与3840帧官方LeRobot逐帧加载核对通过。最大回放关节误差3.91×10⁻¹¹rad、双抽屉开度误差3.43×10⁻¹⁰；旧单抽屉轨迹回放也通过。依然是参与调试的开发样本，没有独立测试集。完整选择与哈希见 `results/pair_spaced_postfix_development_v1/report.json`，修复前结果见 `results/pair_spaced_shifted_seed1_before_withdraw_fix/`。

`evaluate_drawer_pair.py` 会独立从HDF5的两抽屉测量重算每步成功、累计误操作，再把同一条轨迹按相反目标重新评分；并检查上下目标的reset状态/双图/XML一致性。seed0宽间距记录在相反目标下均判失败。这是离线判据核验，没有调用语言模型；真实的prompt反事实测试需等π0.5闭环后实施。

## 运行与复现

```powershell
Set-Location D:\Robotics\Pi05-RoboCasa-Cabinet
$sim = 'D:\Robotics\envs\pi05-sim-win\Scripts\python.exe'

# 自动执行一条指令并录制；输出目录必须为新目录
& $sim scripts\scripted_rollout.py --task OpenDrawerPairLite --instruction 'Open the bottom drawer.' --pair-layout spaced --output outputs\NEW_PAIR_OPEN

# 同一场景也支持人工键盘采集，Space可延长，0取消限时
& $sim scripts\teleop_record.py --task CloseDrawerPairLite --instruction 'Close the bottom drawer.' --pair-layout spaced --max-steps 0

# 一键：四指令脚本录制→各自动作回放→原始判据审计→官方LeRobot转换/逐帧加载核对
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_pair_pilot.ps1 -OutputRoot outputs\NEW_PAIR_PILOT

# 新的开发初始条件：柜体平移(+4cm,-3cm)，seed1；不算正式OOD
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\run_pair_pilot.ps1 -OutputRoot outputs\NEW_SHIFTED_PILOT -Seed 1 -SceneOffset 0.04,-0.03"
```

脚本复用已有仿真/CPU数据环境；可用 `-SimPython` / `-DataPython` 指定其他已安装的解释器路径，不自动安装软件。每次四条轨迹约1920帧；失败轨迹也保留标签并可做技术核验，不能因一键脚本运行结束就视为成功SFT训练集。输出目录包括四个原始episode、四个 `replay_*`、`evaluation/report.json` / `episodes.csv` 和 `lerobot_pipeline_check/`。不上传GitHub或Hub。

## 数据与展示

双RGB、9维state和7维OSC action契约保持一致。附加评测数据位于 `evaluation/`，**不进入策略观测**。metadata保存指令、目标、布局、平移、两个抽屉的名称与初始开度；转换报告保留来源、成功标签和场景参数。旧单抽屉轨迹仍可按原场景回放。

README中的双抽屉MP4是四条独立脚本轨迹的同步拼图：上层开/关各20.75s，下层各27.25s；较短轨迹结束后保留末帧至27.25s，已在画面注明。轨迹运动部分为1倍模拟速度；它不是四阶段连续任务，也不是真正的π0.5自主执行。

接下来的验收是更多初始化条件的质量筛查、明确位置划分及成功数据选择，再接服务器SFT/动作块闭环；物品收纳和RL后训练尚未开始。每个开发条件仍只有每指令1条，不能将8/8写成有统计把握的通用成功率。
