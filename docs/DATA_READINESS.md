# SFT数据准备与固定划分

本页保存v1批次的原始结果；最新候选与复现命令见[反馈采集v4](DATA_READINESS_V4.md)。v1采集代码快照可从提交`3ab7a7d`恢复。撤离接触问题的后续修复及相机筛查见[接触控制记录](CONTACT_CONTROL.md)。旧清单和原始轨迹保留，不用当前代码覆盖重跑旧批次。

2026-11-19：这一步检查成功示教筛选、数据隔离、官方加载器和动作块读取。只采集三组新初始化，每组四条指令；尚未进行模型训练，不能据此评价π0.5。

## 先划分，再采集

固定清单为 [configs/data_splits_v1.json](../configs/data_splits_v1.json)。它在这批仿真运行之前生成，保存采样器、每个seed/平移值、收集代码与依赖锁文件的SHA256。所有既有轨迹，包括参与调试的seed0和seed1，以及人工失败尝试，继续作为development，均不进入这一批train/validation。

Git通过`.gitattributes`将文本checkout固定为LF，避免Windows的自动换行转换改变已冻结采集代码的字节hash。代码快照核对使用文件原始字节，原始录制和旧清单不重写。

| split | 初始条件 | 四条指令 | 用途 |
|---|---|---|---|
| train | seed101、102 | 每组上下抽屉开/关各一次 | 小样本训练数据候选 |
| validation | seed201 | 同上 | 数据读取和质量检查；未用于调整控制器 |
| test_id | seed1001–1020，共20组 | 预留四指令 | 当前不执行、不转为SFT数据 |
| test_translation | seed2001–2020，共20组 | 预留四指令 | 当前不执行的柜体世界坐标平移压力测试 |

train/validation/test_id从同一平移区域采样：dx、dy均在[-0.04,0.04]米；不同split的seed和具体平移点互不相同。test_translation的|dx|在[0.08,0.12]米，dy仍在[-0.04,0.04]米，与前述dx区域有间隔。同一seed、平移和布局的四条命令始终属于同一split，不能随机拆帧或把同一初始状态的top/bottom轨迹拆到两边。

**平移压力测试不等于机械臂相对位置OOD。** RoboCasa会随柜体重新安置机器人；整体平移可主要改变固定世界视角，而策略前视相机装在机器人上。本轮保留机器人实际spawn及“柜体中心减spawn”的世界坐标XY差，用于判断相对几何是否变化；尚未实施互不重叠的机器人相对位置测试区域。正式相对位置泛化需另行固定reset参数和协议，不能将这里预留的平移结果冒称为该成绩。

validation用于数据质量检查是有意的；若后续根据它调整脚本或场景，该版本需标为development，并重新分配验证条件。禁止检查预留测试后反复调参还保留原测试名称。

## 采集和筛选

复用原有`run_pair_pilot.ps1`，每个条件依次运行四条脚本物理轨迹、四次相同动作回放和独立抽屉判据审计。`-SkipConversion`避免为每个条件生成一个重复的数据转换副本。每次回放报告包含原始HDF5的SHA256；收集请求保存固定清单的SHA256。

原有通用`evaluation/report.json`保留保守的`development_pilot`标签，用于物理/数据检查；本批的train/validation归属以采集前固定清单、`collection_request.json`及成功筛选manifest为准，均不当作模型benchmark。

`prepare_sft_data.py build`逐条检查：

- 完整HDF5、统一20Hz、T动作/T+1观测、多视角RGB和9维state/7维动作契约；600步内完成。
- 从原始两抽屉测量独立重算判据；最终和末10步均成功，累计非目标开度偏移不超过0.05。
- 四条命令与清单一致、top/bottom初始状态和双RGB相同，审计与回放均绑定同一文件hash。
- 回放初始状态一致，最大关节误差和两抽屉开度误差均在原有0.01容差内；报告同时保留实际误差。
- 原始文件不能重复，train/validation不能出现相同初始状态或相同双RGB。失败轨迹保留原目录与拒选原因，分母始终包含全部12次尝试。

筛选结果保存为`selection_manifest.json`。通过自动检查仅表示**成功示教候选**，还需人工观看动作是否平稳、接触是否合理，以及图像是否清晰。数据来源保持`SCRIPTED_PRIVILEGED_STATE`，不能写成人工示教或模型推理。

## 本轮采集结果

冻结控制器运行三组共12次尝试：train_001为4/4，train_002为3/4，validation_001为4/4，合计11/12最终及末10步稳定成功。12条录制均通过动作回放。成功筛选保留train的7条、3295帧，以及validation的4条、1920帧；全部原始尝试共5760个动作，545帧失败轨迹完整保留并排除。

seed102的下层关闭在push末开度0.04111、hold末0.03979、release末0.03121，随后retreat末升到0.08134，超过0.05阈值；非目标抽屉未移动。测量确定了失败发生在撤离阶段，尚未重新仿真定位具体手指接触机理。原始动作回放同样失败，因此并非保存或转换把成功标签弄错。详见 [失败阶段报告](../results/data_readiness_failure_train002_close_bottom.json)。没有放宽阈值、截取中途成功前缀或为本批修改控制器。

seed101的机器人在柜体世界坐标X右侧，seed102在左侧，seed201在右侧。筛选报告保留每指令/出生侧计数；当前训练候选缺少“机器人从左侧出生时成功关闭下层抽屉”的样本，不能只凭四条指令均出现就宣称覆盖完整。后续应在训练条件上定位并修复撤离动作，再用新版本计划收集；这批失败继续留存。

## 官方LeRobot与动作块

成功候选分别转换为`train/`与`validation/`两个官方LeRobot v3.0目录；不将其合并再随机拆分。原有转换器继续允许带来源和失败标签的完整轨迹做技术核验，其默认行为不因SFT筛选而更改。

本机实测目录为`data/lerobot/sft_readiness_v1/`：train共3295帧、validation共1920帧；全5215帧官方重读核对通过。55个动作块边界样本通过，两个split均读取了CPU batch，action为[4,50,7]、state为[4,9]、每路RGB为[4,3,256,256]。12条动作回放最大关节误差0.00048175rad、双抽屉开度误差0.0000518344，均在既有0.01容差内；原始报告保留实际值，不宣称完全无数值漂移。详见 [完整数据准备报告](../results/sft_data_readiness_v1.json)。

转换后逐帧比对双RGB像素、state、action、语言和timestamp。另用官方加载器的`delta_timestamps={"action": [i/20 for i in range(50)]}`检查每条episode的起点、中部、最后完整动作块、第一次末尾padding和最后一帧：动作形状为[50,7]，padding重复本条episode的末动作，`action_is_pad`正确，不能跨到下一条指令。用CPU DataLoader把不同指令轨迹的起点组成batch，再检查双RGB、state、action、padding及语言维度；没有模型参与。

50步取自已安装LeRobot0.4.4的[官方PI05Config](https://github.com/huggingface/lerobot/blob/v0.4.4/src/lerobot/policies/pi05/configuration_pi05.py)。这里没有加载π0.5权重、tokenizer或processor，不代表完成模型前向、反向、loss masking或闭环动作块执行验证。

官方API各自生成统计量，并检查state/action的min/max/mean/std/q01/q99维度和有限性。**未来训练及验证的processor均使用train/meta/stats.json**；validation目录的统计量仅供诊断，不得混入训练归一化。固定报告保存train统计文件hash。

## 复现命令

从项目根目录运行，复用已安装的两个环境。清单和输出都必须是新文件/目录；已有结果无需重复采集。冻结清单后修改采集代码会被runner拒绝，应显式生成新版本清单，不能把新代码结果写进旧批次。

```powershell
Set-Location D:\Robotics\Pi05-RoboCasa-Cabinet
$data = 'D:\Robotics\envs\pi05-data-cpu\Scripts\python.exe'

# 仅首次冻结；当前configs/data_splits_v1.json已经存在，勿覆盖
# & $data scripts\prepare_sft_data.py plan --output configs\data_splits_NEW.json

foreach ($id in @('train_001', 'train_002', 'validation_001')) {
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_pair_pilot.ps1 `
        -SplitPlan configs\data_splits_v1.json -ConditionId $id `
        -OutputRoot "outputs\NEW_DATA_BATCH\$id" -SkipConversion
    if ($LASTEXITCODE -ne 0) { throw "Collection failed: $id" }
}

# 原始轨迹已存在时，可直接从这一步构建新的成功候选数据目录
& $data scripts\prepare_sft_data.py build --plan configs\data_splits_v1.json `
    --raw-root outputs\NEW_DATA_BATCH --output data\lerobot\NEW_SFT_PILOT `
    --report results\NEW_SFT_READINESS.json
```

所有命令不下载公开数据或模型，不上传Hub；大数据、视频与本机环境继续由gitignore排除。完整SFT还需要更多成功初始化、人工质量复查，以及服务器上的官方processor与短训练验证。
