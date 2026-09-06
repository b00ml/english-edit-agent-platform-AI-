# app/engine/agreement.py —— judge 与人工标注一致性评估（P0-4 / OPT-020）
# 口径（诚实边界）：二值判定级。judge 判定 = auto 总分 >= threshold；
# 人工真值 = manual_score > 0（0 为驳回）。人工记录仅总分二值，不做维度级加权 kappa；
# judge 与生成模型同族的自偏好偏差由独立 judge 模型治理（P1-2）。
from typing import Any, Dict, List, Sequence, Tuple


def cohen_kappa(y_true: Sequence, y_pred: Sequence) -> float:
    """Cohen's kappa = (po - pe) / (1 - pe)，完全一致为 1.0。

    pe 为两标注者随机一致的概率（按边缘分布）；pe >= 1（含分布完全退化）
    时约定返回 1.0。长度不一致或样本为空抛 ValueError。
    """
    if len(y_true) != len(y_pred):
        raise ValueError("y_true 与 y_pred 长度不一致")
    n = len(y_true)
    if n == 0:
        raise ValueError("样本为空，无法计算 kappa")

    po = sum(1 for t, p in zip(y_true, y_pred) if t == p) / n
    labels = set(y_true) | set(y_pred)
    pe = sum(
        (sum(1 for t in y_true if t == k) / n) * (sum(1 for p in y_pred if p == k) / n)
        for k in labels
    )
    if pe >= 1:
        return 1.0
    return round((po - pe) / (1 - pe), 4)


def judge_vs_manual(pairs: List[Tuple[float, float]], threshold: float) -> Dict[str, Any]:
    """judge（auto 总分）与人工（manual 分）的二值判定一致性（纯函数）。

    pairs 每项为 (auto_total, manual_score)：
      - judge 判定：auto_total >= threshold 视为通过（1），否则驳回（0）；
      - 人工真值：manual_score > 0 视为通过（1），manual_score == 0 为驳回（0）。

    返回混淆矩阵（tp/tn/fp/fn，fp 即"auto 高分但人工驳回"的假阳性）
    与 accuracy/precision/recall/f1/kappa；样本为空时指标为 None。
    """
    y_true = [1 if m > 0 else 0 for _, m in pairs]
    y_pred = [1 if a >= threshold else 0 for a, _ in pairs]

    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    n = len(pairs)

    accuracy = (tp + tn) / n if n else None
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall)
        else None
    )

    return {
        "n": n,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "kappa": cohen_kappa(y_true, y_pred) if n else None,
    }
