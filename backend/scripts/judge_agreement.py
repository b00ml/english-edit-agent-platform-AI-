# scripts/judge_agreement.py —— J7 judge 与人工标注一致性评估（P0-4 / OPT-020）
# 从 DB 收集同 item 的 (auto 总分, manual 分) 标注对，计算 judge 二值判定与
# 人工通过/驳回的一致性：accuracy / precision / recall / f1 / Cohen's kappa。
# 只读分析，不写 DB。n < min_samples 时输出"样本不足"提示（仍打印原始数字）。
#
# 用法（backend 容器内，具备 DB 访问）：
#   python scripts/judge_agreement.py --template single_choice --threshold 70 --min-samples 30
#   python scripts/judge_agreement.py --output-file report.json
import argparse
import json
import sys
from types import SimpleNamespace

sys.path.insert(0, __file__.rsplit("/", 1)[0] + "/..")

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.engine.agreement import judge_vs_manual  # noqa: E402
from app.models import ContentItem, QualityRecord  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="judge 与人工标注一致性评估")
    p.add_argument("--template", default=None, help="题型模板 type_id（缺省=全部题型）")
    p.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="judge 通过阈值（缺省=全局 QUALITY_THRESHOLD）",
    )
    p.add_argument(
        "--min-samples",
        type=int,
        default=30,
        help="最少标注对数量，不足则在报告中提示样本不足（不影响计算）",
    )
    p.add_argument("--output-file", help="报告写入路径（JSON，可选）")
    return p.parse_args()


def collect_pairs(template_id=None):
    """收集同 item 的 (auto 总分, manual 分) 标注对（各取该 item 的第一条）。"""
    session = SessionLocal()
    try:
        q = session.query(ContentItem)
        if template_id:
            q = q.filter(ContentItem.template_id == template_id)
        pairs = []
        for item in q.all():
            records = (
                session.query(QualityRecord)
                .filter(QualityRecord.item_id == item.id)
                .order_by(QualityRecord.created_at)
                .all()
            )
            auto_rec = next((r for r in records if r.source == "auto"), None)
            manual_rec = next((r for r in records if r.source == "manual_review"), None)
            if auto_rec and manual_rec:
                pairs.append((float(auto_rec.score), float(manual_rec.score)))
        return pairs
    finally:
        session.close()


def main():
    args = parse_args()
    threshold = args.threshold if args.threshold is not None else settings.QUALITY_THRESHOLD
    pairs = collect_pairs(args.template)
    report = judge_vs_manual(pairs, threshold)
    report["threshold"] = threshold
    report["template"] = args.template or "(all)"
    report["min_samples"] = args.min_samples
    report["sufficient"] = report["n"] >= args.min_samples
    report["note"] = (
        "二值判定级口径：judge=auto>=threshold；真值=manual_score>0。"
        "人工记录仅总分二值，不做维度级加权 kappa；同族 judge 自偏好由独立 judge 模型治理。"
    )

    print("=" * 60)
    print(f"judge 与人工标注一致性评估  template={report['template']}")
    print(f"阈值={threshold}  标注对 n={report['n']}（最少要求 {args.min_samples}）")
    print(
        f"混淆矩阵: TP={report['tp']} TN={report['tn']} "
        f"FP(假阳性)={report['fp']} FN={report['fn']}"
    )
    print(
        f"accuracy={report['accuracy']}  precision={report['precision']}  "
        f"recall={report['recall']}  f1={report['f1']}"
    )
    print(f"Cohen's kappa={report['kappa']}")
    if not report["sufficient"]:
        print(
            f"[提示] 标注对不足（n={report['n']} < {args.min_samples}），"
            f"指标仅供观察，不建议作为简历/验收数字"
        )
    print("=" * 60)

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"报告已写入: {args.output_file}")


if __name__ == "__main__":
    main()
