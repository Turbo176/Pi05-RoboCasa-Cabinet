# 数据、动作与来源约定

版本：`pandaomron_arm_osc_v1`。原始记录为 `cabinet_raw_v1`；LeRobot 0.4.4 的 Dataset 格式为 v3.0。仿真环境和 CPU 数据工具环境独立；数据工具不导入 MuJoCo、RoboCasa 或 robosuite。

## 原始 episode

`episode.hdf5`、`report.json`、MP4、最后一帧在一个独立目录中。写入中保留 `episode.partial.hdf5`；完成长度/有限数/时间间隔/视频解码检查后才标为完成。F9 或中断保留 partial 和丢弃原因，不自动删除用户数据；转换器拒绝 partial。

| 字段 | 长度/内容 |
|---|---|
| `observations/*` | T+1；两路256×256 RGB、关节/EEF/夹爪/底座状态 |
| `actions` | T×12；每个动作作用于 `observations[t]` |
| `sim_qpos`, `sim_qvel` | T+1；全仿真关节状态，用于检查与回放诊断 |
| `sim_time`, `wall_time` | T+1；模拟时钟固定间隔0.05秒，墙钟可包含暂停 |
| `success`, `drawer_open_fraction`, `reward`, `done`, `stage` | T；执行动作后的评测状态 |
| `initial_sim_state`, `model_xml` | 初始time/qpos/qvel与场景XML，严格动作回放依赖相同资产和版本 |
| `metadata_json` | 语言、任务、seed、来源、相机、布局、控制与图像约定 |
| `evaluation/drawer_open_fractions` | 双抽屉轨迹可选；T+1×2，顺序为metadata的`drawer_names`（top、bottom） |
| `evaluation/non_target_max_drift` | 双抽屉轨迹可选；T，各控制步累计非目标抽屉最大开度偏移 |

原始相机是 OpenGL bottom-left RGB；转换时只翻转一次行方向。视频使用 top-left RGB。图像记录在动作之前，T+1 的最后观测保留在原始数据中；LeRobot监督样本只取前T帧与T个动作。

双抽屉metadata额外保存 `scene_parameters`（instruction、scene_offset、pair_layout、front_camera），回放用其重建原布局；旧版记录缺少pair_layout时默认为compact，缺少front_camera时默认为robot_left。`target_drawer`和抽屉评测真值只用于环境判据/脚本与审计，不作为state或RGB输入。LeRobot转换报告逐episode保留这些参数、相机映射和非目标偏移；图像上的演示HUD不写入策略相机。

## 策略输入输出

| LeRobot键 | 维度 | 语义 |
|---|---|---|
| `observation.images.front` | 256×256×3 | 新采集为`cabinet_front_image`；旧录制为`robot0_agentview_left_image`，top-left RGB |
| `observation.images.wrist` | 256×256×3 | `robot0_eye_in_hand_image`，top-left RGB |
| `observation.state` | 9 | Panda 7个关节位置(rad)与2个夹指位置(m) |
| `action` | 7 | OSC base坐标系归一化末端delta：XYZ、轴角XYZ、夹爪 |
| `task` | 语言字符串 | 官方加载器通过task_index还原对应指令 |

`action[:3]` 经控制器缩放到每步最大±0.05m；`action[3:6]` 最大±0.5rad；夹爪+1关闭、-1打开。机器人完整动作 `[0:6]` 为右臂、`[6]` 为夹爪、`[7:10]` 为底座、`[10]` 为躯干、`[11]` 为模式。适配器补底座/躯干为0，模式为-1；转换时逐帧检查这些维度，拒绝静默丢弃非零底座动作。

此版不是关节位置动作，也不是绝对EEF位姿。关节状态与OSC动作维度可以不同。抽屉状态、把手坐标、success不进入策略输入。π0.5 的图像预处理、状态/动作归一化和padding交给官方processor；不能仅取模型输出而跳过反归一化。

前视相机的版本由`scene_parameters.front_camera`明确记录。新CLI默认`cabinet_front`：固定世界坐标机位，能同时覆盖上下抽屉；腕部相机不变。相机不随语言目标或把手状态移动。`robot_left`保留历史相机和XML，可通过`--front-camera robot_left`显式选择。适配器拒绝同时存在两个前视来源的模糊输入；转换器拒绝在一个数据集中混用两种前视配置。训练与推理必须使用同一配置，不能把同名的`front`当作可任意替换的视角。详见[相机检查报告](../results/camera_framing_v3.json)。

最初两条脚本pilot采用lossless PNG嵌入Parquet，官方API计算统计量，重读全部830帧逐像素比较。它是合法LeRobot Image Dataset，没有假造video元数据；后续规模增大再决定是否转视频存储。

## 来源与划分

- `SCRIPTED_PRIVILEGED_STATE`：使用仿真把手真值的脚本基线；必须加 `--allow-scripted` 才能转换。
- `KEYBOARD_TELEOP`：用户键盘人工示教。P键可选固定夹持姿态辅助，仅依赖机器人本体感知；平移和夹爪由操作者决定。
- `AGENT_UI_CHECK` / `SYNTHETIC_KEY_CONTROL_CHECK`：开发检查；转换器拒绝加入训练数据。
- `PI05`：保留给未来真实模型闭环；当前没有这种轨迹。

成功与失败轨迹分别保留标签，不因按F8就标为成功。SFT先人工复查成功示教；失败数据留给故障分析与后续RL。训练/验证/测试按episode和初始化区域划分，不能随机拆帧。重复seed0的流水线检查不是新增独立评测。

固定划分及自动成功候选筛选见 [SFT数据准备](DATA_READINESS.md)。通用转换器继续支持完整失败轨迹做技术核验；SFT候选由单独manifest选择，要求末10步成功、非目标完整、同文件hash回放通过。训练和验证目录分开，未来两者processor均使用训练集统计量。预留的世界坐标平移压力测试不代表已经固定机器人相对位置OOD区域。

## 本机命令

```powershell
$data = 'D:\Robotics\envs\pi05-data-cpu\Scripts\python.exe'
& $data scripts\convert_lerobot.py outputs\open_shared_recorder_v1\episode.hdf5 outputs\close_seed0\episode.hdf5 --allow-scripted --output data\lerobot\NEW_PILOT
```

输出目录必须不存在。人工示教转换去掉 `--allow-scripted` 并传入实际完成的 `data/raw/teleop/.../episode.hdf5`，不传partial、UI检查或重复文件。转换脚本默认离线，不上传Hub，不下载数据或模型。
