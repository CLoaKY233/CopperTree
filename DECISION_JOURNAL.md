# CopperTree — Decision Journal

Append-only log of every learning-loop promote/reject decision.
Each entry records the statistical gate results, score deltas, and artifact file paths.

---

## 2026-04-16T07:47:45Z — assessment — assessment_v5 → assessment_v9

**Decision:** REJECTED  
**Reason:** Improvement not statistically significant by Wilcoxon test (p=0.688 >= alpha=0.05). Baseline mean=0.6998, candidate mean=0.6898, delta mean=-0.0100.

**Baseline (assessment_v5):** composite=0.6998 ± 0.0707, compliance_pass=100.0%, N=5, seed=42  
**Candidate (assessment_v9):** composite=0.6898 ± 0.1116, compliance_pass=100.0%  
**Delta:** -0.0100
**Statistical gate:**
- **Gate 1** (100% compliance required): PASS  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): PASS  (p=0.5000)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): FAIL  (p=0.6875)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_42_a12ef645.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_42_a18b4be7.jsonl`

---

## 2026-04-16T07:47:46Z — assessment — assessment_v5 → assessment_v8

**Decision:** REJECTED  
**Reason:** Compliance gate failed: 2/5 conversations had hard-gate violations (compliance_pass_rate=60.0%). All conversations must pass to be eligible for promotion.

**Baseline (assessment_v5):** composite=0.5678 ± 0.0000, compliance_pass=80.0%, N=5, seed=42  
**Candidate (assessment_v8):** composite=0.4792 ± 0.0000, compliance_pass=60.0%  
**Delta:** -0.0885
**Statistical gate:**
- **Gate 1** (100% compliance required): FAIL  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): —  (n/a)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): FAIL  (n/a)  
- **Gate 4** (bootstrap 95% CI lower > 0): FAIL  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_42_3e9204ca.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_42_4346e898.jsonl`

---

## 2026-04-16T11:30:08Z — assessment — assessment_v5 → assessment_v10

**Decision:** REJECTED  
**Reason:** Improvement not statistically significant by Wilcoxon test (p=0.219 >= alpha=0.05). Baseline mean=0.5608, candidate mean=0.7083, delta mean=+0.1475.

**Baseline (assessment_v5):** composite=0.5608 ± 0.2978, compliance_pass=80.0%, N=5, seed=42  
**Candidate (assessment_v10):** composite=0.7083 ± 0.1004, compliance_pass=100.0%  
**Delta:** +0.1475
**Statistical gate:**
- **Gate 1** (100% compliance required): PASS  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): PASS  (n/a)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): FAIL  (p=0.2188)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_42_3dbbec99.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_42_5d9090c6.jsonl`

---

## 2026-04-16T11:34:29Z — assessment — assessment_v5 → assessment_v11

**Decision:** REJECTED  
**Reason:** Compliance gate failed: 1/5 conversations had hard-gate violations (compliance_pass_rate=80.0%). All conversations must pass to be eligible for promotion.

**Baseline (assessment_v5):** composite=0.7223 ± 0.0882, compliance_pass=100.0%, N=5, seed=1042  
**Candidate (assessment_v11):** composite=0.5687 ± 0.3002, compliance_pass=80.0%  
**Delta:** -0.1537
**Statistical gate:**
- **Gate 1** (100% compliance required): FAIL  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): —  (n/a)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): —  (n/a)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_1042_e8768c11.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_1042_1fbbe716.jsonl`

---

## 2026-04-16T11:40:15Z — assessment — assessment_v5 → assessment_v12

**Decision:** REJECTED  
**Reason:** Compliance gate failed: 1/5 conversations had hard-gate violations (compliance_pass_rate=80.0%). All conversations must pass to be eligible for promotion.

**Baseline (assessment_v5):** composite=0.5512 ± 0.2890, compliance_pass=80.0%, N=5, seed=2042  
**Candidate (assessment_v12):** composite=0.5755 ± 0.2950, compliance_pass=80.0%  
**Delta:** +0.0242
**Statistical gate:**
- **Gate 1** (100% compliance required): FAIL  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): —  (n/a)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): —  (n/a)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_2042_56099a1c.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_2042_5cc12267.jsonl`

---

## 2026-04-16T11:45:25Z — assessment — assessment_v5 → assessment_v13

**Decision:** REJECTED  
**Reason:** Improvement not statistically significant by Wilcoxon test (p=0.688 >= alpha=0.05). Baseline mean=0.7347, candidate mean=0.7177, delta mean=-0.0170.

**Baseline (assessment_v5):** composite=0.7347 ± 0.0662, compliance_pass=100.0%, N=5, seed=3042  
**Candidate (assessment_v13):** composite=0.7177 ± 0.0770, compliance_pass=100.0%  
**Delta:** -0.0170
**Statistical gate:**
- **Gate 1** (100% compliance required): PASS  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): PASS  (p=0.2500)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): FAIL  (p=0.6875)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_3042_11edaa67.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_3042_2e3feebb.jsonl`

---

## 2026-04-16T11:49:48Z — assessment — assessment_v5 → assessment_v14

**Decision:** REJECTED  
**Reason:** Improvement not statistically significant by Wilcoxon test (p=0.500 >= alpha=0.05). Baseline mean=0.6902, candidate mean=0.7031, delta mean=+0.0129.

**Baseline (assessment_v5):** composite=0.6902 ± 0.0818, compliance_pass=100.0%, N=5, seed=4042  
**Candidate (assessment_v14):** composite=0.7031 ± 0.0658, compliance_pass=100.0%  
**Delta:** +0.0129
**Statistical gate:**
- **Gate 1** (100% compliance required): PASS  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): PASS  (p=1.0000)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): FAIL  (p=0.5000)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_4042_97af6f70.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_4042_618ab84d.jsonl`

---

## 2026-04-16T11:54:09Z — assessment — assessment_v5 → assessment_v15

**Decision:** REJECTED  
**Reason:** Improvement not statistically significant by Wilcoxon test (p=0.219 >= alpha=0.05). Baseline mean=0.7140, candidate mean=0.7303, delta mean=+0.0163.

**Baseline (assessment_v5):** composite=0.7140 ± 0.0669, compliance_pass=100.0%, N=5, seed=5042  
**Candidate (assessment_v15):** composite=0.7303 ± 0.0858, compliance_pass=100.0%  
**Delta:** +0.0163
**Statistical gate:**
- **Gate 1** (100% compliance required): PASS  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): PASS  (p=1.0000)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): FAIL  (p=0.2188)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_5042_062a7f50.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_5042_47b79e49.jsonl`

---

## 2026-04-16T11:58:34Z — assessment — assessment_v5 → assessment_v16

**Decision:** REJECTED  
**Reason:** Improvement not statistically significant by Wilcoxon test (p=0.406 >= alpha=0.05). Baseline mean=0.5725, candidate mean=0.7418, delta mean=+0.1693.

**Baseline (assessment_v5):** composite=0.5725 ± 0.3090, compliance_pass=80.0%, N=5, seed=6042  
**Candidate (assessment_v16):** composite=0.7418 ± 0.0434, compliance_pass=100.0%  
**Delta:** +0.1693
**Statistical gate:**
- **Gate 1** (100% compliance required): PASS  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): PASS  (n/a)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): FAIL  (p=0.4062)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_6042_b89d46aa.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_6042_c427e73a.jsonl`

---

## 2026-04-16T12:03:05Z — assessment — assessment_v5 → assessment_v17

**Decision:** REJECTED  
**Reason:** Compliance gate failed: 1/5 conversations had hard-gate violations (compliance_pass_rate=80.0%). All conversations must pass to be eligible for promotion.

**Baseline (assessment_v5):** composite=0.6731 ± 0.1231, compliance_pass=100.0%, N=5, seed=7042  
**Candidate (assessment_v17):** composite=0.5540 ± 0.2938, compliance_pass=80.0%  
**Delta:** -0.1191
**Statistical gate:**
- **Gate 1** (100% compliance required): FAIL  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): —  (n/a)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): —  (n/a)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_7042_e6286619.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_7042_4d0f1317.jsonl`

---

## 2026-04-16T12:07:17Z — assessment — assessment_v5 → assessment_v18

**Decision:** REJECTED  
**Reason:** Improvement not statistically significant by Wilcoxon test (p=0.406 >= alpha=0.05). Baseline mean=0.5740, candidate mean=0.7108, delta mean=+0.1368.

**Baseline (assessment_v5):** composite=0.5740 ± 0.2968, compliance_pass=80.0%, N=5, seed=8042  
**Candidate (assessment_v18):** composite=0.7108 ± 0.0939, compliance_pass=100.0%  
**Delta:** +0.1368
**Statistical gate:**
- **Gate 1** (100% compliance required): PASS  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): PASS  (n/a)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): FAIL  (p=0.4062)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_8042_60bb00ce.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_8042_43aecf75.jsonl`

---

## 2026-04-16T12:11:47Z — assessment — assessment_v5 → assessment_v19

**Decision:** REJECTED  
**Reason:** Improvement not statistically significant by Wilcoxon test (p=0.969 >= alpha=0.05). Baseline mean=0.7626, candidate mean=0.7397, delta mean=-0.0229.

**Baseline (assessment_v5):** composite=0.7626 ± 0.0399, compliance_pass=100.0%, N=5, seed=9042  
**Candidate (assessment_v19):** composite=0.7397 ± 0.0430, compliance_pass=100.0%  
**Delta:** -0.0229
**Statistical gate:**
- **Gate 1** (100% compliance required): PASS  
- **Gate 2** (compliance non-regression, Wilcoxon one-sided): PASS  (p=1.0000)  
- **Gate 3** (composite improvement, Wilcoxon one-sided): FAIL  (p=0.9688)  
- **Gate 4** (bootstrap 95% CI lower > 0): —  (n/a)

**Artifacts:**  
- Baseline: `data/eval_runs/eval_assessment_9042_68a6ad85.jsonl`  
- Candidate: `data/eval_runs/eval_assessment_9042_14eef425.jsonl`

---

