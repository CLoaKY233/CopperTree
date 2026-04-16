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

