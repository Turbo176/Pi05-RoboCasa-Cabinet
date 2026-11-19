# 服务器首轮执行清单

2026-11-19：用户已反馈服务器数据校验通过，准备检查训练环境。本页是下一步操作和交付要求，不代表本机已经连接服务器或完成训练。

首轮保持 `drawer_sft_v1`：训练28条/10226帧，验证4条/1465帧，使用同一份冻结train统计量。新增16条本地数据已通过辅助审查，但本轮不合并、不重新划分。

## 先检查现有环境

由能连接服务器的那台电脑执行，或交给服务器端助手。先复用已有代码和环境，不改网络，不在本地GTX1650Ti上训练。

```bash
uname -a
nvidia-smi
df -h .
python3 --version
command -v conda
# 有conda时再执行：
conda env list
# 在实际项目目录执行：
git status --short
git rev-parse HEAD
```

检查训练环境中PyTorch、CUDA、LeRobot及π0.5依赖的实际版本，并记录锁文件。先报告GPU占用和调度允许使用的卡号；有8张卡不表示当前允许全部使用。原交接bundle的提交为`8036d64`，冻结清单应与传输包一致。保留服务器已有修改，不能为了对齐本地最新提交强制覆盖工作。

## GPU可用后的顺序

| 关卡 | 实际要做的事 | 通过依据 |
|---|---|---|
| 真实processor | 官方加载器取一个batch，按冻结契约经过π0.5 pre/postprocessor | 双RGB方向、9维state、7维动作、任务字符串、padding/mask和反归一化正确；两split都用train统计量 |
| 单batch训练 | 实际前向、loss、反向和optimizer更新 | loss及梯度有限，明确参数更新范围，记录每卡峰值显存 |
| 100–300步短训练 | 复用同一数据和配置，保存checkpoint，再从它恢复继续若干步 | model/processor/statistics和optimizer/scheduler/step/随机状态均可恢复；恢复后有实际更新 |
| 首轮SFT | 短训练通过后确定训练步数、batch和单卡/多卡方案 | 保存配置、revision、日志、验证结果和checkpoint选择依据 |
| 模型推理服务 | 实际加载checkpoint及匹配processor，复用现有HTTP协议 | 记录权重/统计量身份，收到真实观测后返回反归一化的`[50,7]`动作块 |
| 本地闭环 | 本地MuJoCo执行前5步，重新取观测，运行四条指令 | 每条保存报告、请求日志和MP4；失败保留，不以loss下降代替任务成功 |

不要先编造一个“一键训练命令”。当前仓库尚无在此服务器验证过的π0.5训练脚本及模型服务端，服务器助手需要根据实际锁定的官方版本实现并运行。不能把录制动作端点改个名字当作模型服务。

## 交给服务器助手的提示词

> 数据传输校验已通过，请继续Pi05-RoboCasa-Cabinet的服务器环境检查。先阅读仓库`docs/SERVER_AND_RL.md`、`docs/DATA_CONTRACT.md`和`docs/REMOTE_INFERENCE.md`，复用已有环境和代码，保留已有修改。首轮固定使用`configs/sft_release_v1.json`，训练28条/10226帧、验证4条/1465帧，均使用其中指定的train统计量。先报告可用GPU及调度权限、驱动、PyTorch/CUDA、Python/LeRobot环境和磁盘，不改网络。GPU未获准使用前不加载大模型或训练。GPU获准后锁定官方π0.5训练器、依赖和基础模型revision，先完成真实processor和单batch前向/反向，再做100–300步短训练，实际验证保存、加载、恢复训练和每卡峰值显存。补齐可运行训练脚本，不只给计划。首轮返回环境清单、processor报告、训练配置、短训练日志和恢复结果。通过后再推进正式SFT及真实PI05 HTTP服务；保持两路256RGB、9维state、7维OSC动作和`[50,7]`动作块，不引入把手/抽屉真值，不切换任务平台，不开展RL，不把录制回放标成模型推理。

## 首轮结果回传

把下面这些小文件或摘要带回本对话即可，暂时不用把整个模型下载到本地：

- 实际代码提交、GPU型号和获准卡号、依赖版本及环境锁文件。
- processor检查结果：输入输出布局、dtype、相机映射、状态/动作处理、train统计量hash。
- 短训练的启动命令、配置、loss日志、每卡峰值显存、保存路径、恢复后的step及更新结果。
- checkpoint及processor的目录结构和身份；HTTP服务就绪后，再给本机可达的现有转发地址与checkpoint ID，不发送密码或Token。

本地模型试跑入口见[四指令试跑](POLICY_SMOKE.md)。它复用原来的仿真客户端；服务器权重和processor加载证据仍由服务端提供。新增本地文档和入口不改变已上传的v1数据，服务器准备训练时可以继续用原包。
