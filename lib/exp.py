"""EXP scoring engine — pure functions, easy to reason about and test."""

BASE_PER_SET = 12
COMPOUND_MULTIPLIER = 1.5
OVERLOAD_BONUS = 25
MISS_PENALTY = -30


def calculate_exp(completed: bool, is_compound: bool, sets_done: int,
                  beat_previous_weight: bool, streak_days: int):
    """Return (delta, reasons[])."""
    if not completed:
        return MISS_PENALTY, ["Missed a scheduled workout"]

    reasons = []
    base = sets_done * BASE_PER_SET
    reasons.append(f"Completed {sets_done} sets")

    if is_compound:
        base *= COMPOUND_MULTIPLIER
        reasons.append("Compound exercise bonus (1.5x)")

    if beat_previous_weight:
        base += OVERLOAD_BONUS
        reasons.append("Progressive overload (beat last session)")

    streak_blocks = streak_days // 7
    streak_mult = min(1 + streak_blocks * 0.1, 2)
    if streak_mult > 1:
        base *= streak_mult
        reasons.append(f"{streak_days}-day streak ({streak_mult:.1f}x)")

    return round(base), reasons


def calc_bmi(weight_kg: float, height_cm: float) -> float:
    if not height_cm:
        return 0.0
    m = height_cm / 100
    return round(weight_kg / (m * m), 1)
