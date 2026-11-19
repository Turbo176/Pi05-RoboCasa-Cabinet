# 服务器SFT与后续RL边界

2026-11-18：8×RTX3090服务器GPU暂忙。当前未连接服务器、未下载π0.5权重、未启动SFT/RL，也没有模型成功率或模型视频。本地仿真和CPU数据工具分别独立运行。

## SFT接入关卡

采用LeRobot官方π0.5训练器。当前数据使用LeRobot0.4.4 Dataset v3.0 API验证；服务器训练器及processor要另锁定版本，与其实际依赖和checkpoint核对。CPU数据环境不包含π0.5可选依赖，不能直接用作训练环境。

服务器空闲后依次检查Linux、驱动/CUDA、每卡24GB显存、Conda、磁盘和网络；8卡显存不能简单视作一张192GB显卡。基于实测选训练策略与分片，先做一批前向/反向、保存、恢复，再扩大训练；不提前承诺全参数训练的batch size或显存占用。

训练数据只用经人工确认且按episode划分的示教。现有开发pilot和新初始化的小批成功候选仍不足以支持模型质量或泛化结论；划分、排除失败轨迹与数据读取检查见 [SFT数据准备](DATA_READINESS.md)。服务器应读取固定manifest与train统计量，不能混入开发集或validation统计量。先把9维state、7维action与两路RGB送入官方processor，检查图像归一化、state量化、action缩放和padding；预测后必须用同一postprocessor反归一化。

首版已验收数据见[冻结清单](../configs/sft_release_v1.json)及[验收结果](../results/human_acceptance_v4.json)：train 28条/10226帧，validation仍为原4条/1465帧。2026-11-19导出的32条人工结论全部通过，均声明完整观看，来源与视频hash校验通过。清单固定episode顺序、22个数据文件和train统计量hash；原始验收姓名和备注只留本地。

数据来自[保留v4验证集的训练追加批次](TRAINING_DATA_EXTENSION.md)。合并训练集逐帧重新转换核对，原验证集7个文件的字节哈希保持一致；两部分共11691帧官方重读和160个动作块边界检查通过。32条动作回放通过，每条训练指令有5个左侧及2个右侧出生例子；验证只有一个左侧初始化。此前v3候选及失败保留原记录，不合并到v4。新模型固定使用`cabinet_front`加腕部RGB，禁止把旧`robot_left`候选混入同一数据集。服务器按冻结清单读取`data/lerobot/sft_readiness_v4_extended/train`及原`data/lerobot/sft_readiness_v4/validation`，传输后先核对文件hash，两者均使用追加后train统计量。训练/推理保留数据manifest、相机与train统计量hash；只使用自动筛选及人工验收均通过的轨迹。这仍是小批脚本示教，不能据此宣称能训练出稳定策略。

当前上游PI05Config有chunk_size、n_action_steps、量化归一化及图像processor配置。拟先预测H=50、执行前k=5步后更新观测（20Hz），这些参数仍需模型接口与延迟实测。必须保留完整processor与dataset统计量，不能仅保存safetensors。

每个run保存代码/数据hash、配置、训练/验证划分、随机状态、optimizer/scheduler、step、完整模型/processor与归一化统计。断点恢复须经过短训练验证。服务器只在本地已验证的数据格式和动作契约上继续；不切换任务平台。

## 真实闭环评测

本地已实现[HTTP动作块接口](REMOTE_INFERENCE.md)：语言、双RGB与9维state请求，完整校验`[H,7]`动作后执行前k步。录制动作端点用v4首组训练条件完成四条指令、1447步/291请求；第二次请求注入过期episode或超时后，均停在前5步，等待时仿真时间不推进。这是`RECORDED_ACTION_CHUNKS`通信与执行回归，不是模型推理；未提供π0.5服务端，也未验证模型processor或checkpoint加载。40组预留测试未执行，v4冻结采集源码未修改。

本地发送语言、双RGB、9维本体感知；服务器返回 `[H,7]` 动作块；客户端执行前k步，再取新观测。接口必须记录请求/episode/step身份、schema和checkpoint版本，拒绝迟到或上个episode的响应。连接超时、无效值或维度不符时停止推进仿真，禁止复用旧动作块。

固定20Hz、600步预算；按任务分别评测20次ID与20次明确不重叠初始位置区域的OOD。记录最终成功、连续10步稳定成功、耗时、成功数/总数、Wilson95%区间、动作块参数与推理延迟。语言指定目标至少要两个可区分抽屉，同一初始状态交换prompt，并检查非目标抽屉未被误动。

## RLinf兼容性初查

只阅读官方源码/文档，未安装RLinf。检查时官方HEAD：`b665e1873b07501f779a5b11dc5bed5b6dcb2125`。

| 官方已有内容 | 对本项目的意义 / 尚待补齐 |
|---|---|
| RoboCasa CloseDrawer + PandaOmron + OpenPI π0 + PPO配方 | 任务平台和机器人存在直接上游先例，无需更换平台；配方是π0，不等于本项目LeRobot π0.5 checkpoint已兼容 |
| 旧RoboCasa配方使用双224RGB、25维state、12维动作 | 本项目为双256RGB、9维state、7维动作；需复用本项目契约/processor并显式适配，不能直接套默认配置 |
| RoboCasa365独立wrapper支持配置state布局、action切片与禁用base | 说明环境侧有可复用入口；Lite自定义任务注册、版本与reset向量化尚须接入验证 |
| 框架有π0.5在其他环境的PPO/GRPO示例 | 说明模型/算法组件存在；并不证明RoboCasa+当前LeRobot模型+GRPO组合开箱即用 |

后续主要成本是LeRobot/OpenPI模型实现及checkpoint/processor一致性、9/7维适配、vector env中Lite注册/资产路径、动作块的奖励与终止语义、策略log-prob/参考策略和值函数配置。不能只把SFT权重路径填入RLinf旧π0示例就声称已接通。

先复现自己的SFT闭环，再在同一Lite任务上做单环境reset/step适配与奖励一致性检查。PPO/GRPO使用任务奖励；GRPO组内从相同初始化条件独立rollout，不能靠把手真值作为policy输入。保留环境稀疏成功奖励和任务判据，避免为脚本容易成功而改目标。只有此关卡稳定后才考虑服务器后训练；当前不启动。

官方来源：

- [LeRobot v0.4.4 PI05Config](https://github.com/huggingface/lerobot/blob/v0.4.4/src/lerobot/policies/pi05/configuration_pi05.py)
- [RLinf RoboCasa配方](https://github.com/RLinf/RLinf/blob/b665e1873b07501f779a5b11dc5bed5b6dcb2125/docs/source-en/rst_source/examples/embodied/robocasa.rst)
- [RLinf RoboCasa365接口](https://github.com/RLinf/RLinf/blob/b665e1873b07501f779a5b11dc5bed5b6dcb2125/docs/source-en/rst_source/examples/embodied/robocasa365.rst)
