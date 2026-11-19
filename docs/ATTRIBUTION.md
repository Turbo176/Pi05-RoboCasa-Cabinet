# 上游引用与本人实现范围

| 上游 | 使用方式 / 锁定版本 | 归属边界 |
|---|---|---|
| [MuJoCo](https://github.com/google-deepmind/mujoco) | `mujoco==3.3.1`，物理与渲染 | 引擎由上游提供；本项目不复制其源码/二进制到仓库 |
| [RoboCasa](https://github.com/robocasa/robocasa) | 1.0.1，commit `425684d332f135f5b30a40b321f52d15a0fe9250` | OpenDrawer/CloseDrawer、Drawer fixture及原始目标判据沿用上游；单抽屉语言沿用上游，双抽屉目标指令与额外误操作判据由本项目实现；Lite不是官方完整benchmark |
| [robosuite](https://github.com/ARISE-Initiative/robosuite) | 1.5.2，commit `5ce6643f3092639d08f7b0f90ed1c6a84f50552c` | PandaOmron、OSC控制器、相机/状态与原始纹理来自上游 |
| [LeRobot](https://github.com/huggingface/lerobot) | 数据API0.4.4 / Dataset v3.0 | 本项目调用官方API生成与读取数据；不把手工JSON包装成已通过官方验证 |
| [π0.5 / Physical Intelligence](https://www.physicalintelligence.company/blog/pi05) | 后续模型与算法；尚未下载/训练 | 不声称原创基础模型或已取得模型性能 |
| [Pi05-Mujoco](https://github.com/metro8116/Pi05-Mujoco) | 参考工程、数据转换、checkpoint与视频展示组织 | 只参考README和工程思路；未复制FR3抓取入篮代码或数据 |
| [Pi05-FR3-Gello](https://github.com/metro8116/Pi05-FR3-Gello) | 参考采集、LeRobot、训练与部署管理思路 | 未复制其项目/数据/机器人资产 |
| [RLinf](https://github.com/RLinf/RLinf) | 仅官方文档兼容性调查 | 尚未安装、接入或启动后训练 |

本项目新增实现：

- 用官方Drawer fixture组成资产轻量的Lite布局，保留官方任务初始化和成功判据。
- 双抽屉紧凑/宽间距布局、上下目标指令、目标无关的相同物理reset、柜体平移参数与全轨迹非目标误操作判据。
- 在项目内实现Windows MSVC预加载和路径适配；不修改上游已跟踪文件。
- PandaOmron通过真实接触拉/推把手的脚本基线；用特权状态，视频明确标注。
- 键盘交互、固定姿态辅助、暂停/保存/丢弃、来源隔离。
- 共用流式HDF5+MP4录制、T/T+1对齐、时间戳、动作回放误差报告。
- 9维state/7维OSC契约，官方LeRobot转换与全部帧的像素/状态/动作/语言核对。
- 文档、可复现配置、小结果、演示及分阶段验收设计。
- 四指令一键pilot、原始开度独立重算、离线错误目标评分及相同初始双RGB/XML/状态审计；不冒称模型语言推理。
- 采集前冻结的训练/验证/预留测试清单、基于成功与同文件hash回放的候选筛选、动作块边界及CPU batch读取检查。

项目仓库不打包上游源码、完整厨房资产、公开示教或模型权重。上游分别保留原版权与LICENSE/NOTICE；RoboCasa/robosuite的本地源码LICENSE保存在各自上游checkout。参考工程许可不能仅凭README或根LICENSE链接缺失推断；未取得明确许可前不复制其代码或数据。后续引入模型或新增第三方资产时，需核对对应条款及再分发许可；生成的仿真视频保留引擎/机器人/资产来源说明。

本人实现采用仓库根目录的 [MIT许可证](../LICENSE)，已由仓库所有者确认。该许可证不重新许可上游引擎、机器人/fixture/纹理、模型权重或第三方代码；演示画面使用上述上游资产渲染，保留本文件的来源说明。
