# Demonstration review

New local batches use [automatic checks plus agent spot review](../configs/data_review_v2.json).
The maintainer approved this workflow on November 19, 2026. It replaces the
requirement to watch and approve every new episode manually. Frozen releases
keep their original acceptance records.

| Review | Coverage | Record |
|---|---|---|
| Automatic checks | Every attempt; every selected export frame | Existing task, replay, LeRobot, chunk-boundary, split and hash reports |
| Agent keyframe inspection | Every episode, both cameras | First action, grasp completion, final action and findings |
| Complete trajectory spot checks | At least two episodes or 10%, rounded up; capped at batch size | Sample IDs chosen before inspection, reasons and every observation index |
| Exception inspection | Relevant failed or unusual checks | Original failure, source evidence, disposition and unresolved items |
| Maintainer input | Cases the agent cannot resolve | A specific clip, question and reason for escalation |

The complete-trajectory sample covers training and validation where available,
and includes opening and closing. Relevant anomalous cases are added when
needed. Inspection uses chronological dual-view filmstrips containing every
observation, with native-resolution images around contact or suspicious motion.
This is recorded as agent image inspection, separate from real-time video
playback or a human declaration of complete-video viewing.

Inspect target selection, handle approach and grasp, drawer motion, movement
of the other drawer, release, clearance, retreat, and camera visibility.
Automatic success cannot resolve a visual anomaly. Keep task failures and
their reasons; exclude rejected episodes from demonstrations used for SFT.
The existing numeric thresholds and exact raw-to-dataset pixel comparison
remain in force.

Use `accepted_under_assisted_review_v2` only after the automatic checks pass,
the required visual inspection is recorded, and no blocking anomaly remains.
Bind the result to the policy, selection, raw recordings, review media and
data reports using SHA256. Record the reviewer as an agent and specify the
actual frame coverage. Preserve earlier reports rather than rewriting their
historical `pending` fields. Human decisions remain optional and separate;
the [existing Chinese review page and checker](TRAINING_DATA_EXTENSION.md#full-human-review-used-by-v1)
can still record them.

Admission allows a later explicitly versioned trial or release. It does not
change the active server data, normalization statistics or split membership.
Validation episodes remain outside training. If data are merged later, freeze
the new membership and training statistics, and compare checkpoints on the
same validation version.

## Follow-up v5

The [assisted-review record](../results/assisted_review_followup_v5.json)
admits all 16 follow-up episodes: eight training / 2,937 frames and eight
validation / 2,893 frames. Keyframes cover all 16 episodes. The two complete
trajectory samples are:

- `train_008/open_top`: opening example and the condition with the known
  paired-reset RGB discrepancy; 326 observations, including the initial state.
- `validation_002/close_bottom`: closing example and the longest validation
  recording; 411 observations, including the initial state.

All 737 sampled observations were inspected in 16 filmstrips. Nine further
sheets show native-resolution observations around every sampled stage
boundary. No blocking visual anomaly was identified at this inspection
resolution. The known reset discrepancy remains documented: three frontal
pixels differ by one uint8 level, within the pre-existing `lsb_v1` profile;
the rendering cause remains unisolated. The strict failure is retained.

The local Chinese status page is
`outputs/data_review_followup_v5_assisted/index.html`. The original page and
16 pending human declarations remain unchanged; they are no longer a required
gate for this cohort. This review decision supersedes only the original
follow-up plan's full-human-review requirement. The plan, raw data, original
reports and the v1 transfer remain unchanged. The follow-up has not been
merged into a new release or uploaded to the server.

Review can miss subtle contact defects. It establishes data admission, not
π0.5 success, language grounding or generalization.
