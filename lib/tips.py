"""Static, pre-written form tips. Zero API cost — served straight from code."""

TIPS = {
    "Barbell Row": [
        "Lead with your elbows, not your hands — this targets the lats more effectively.",
        "Keep a flat back throughout; rounding under load risks your lower spine.",
        "Think about pulling the bar to your lower chest, pausing for a beat at the top.",
    ],
    "Pull-ups": [
        "Depress your shoulder blades before you bend your elbows.",
        "Slow negatives (a 3-second lower) build strength faster than rushed reps.",
        "If you can't hit the target reps, use a band — it's progress, not cheating.",
    ],
    "Bench Press": [
        "Keep your feet flat and drive your legs into the floor for a stable base.",
        "Lower the bar to your lower chest, not your neck.",
        "Keep your wrists stacked straight over your elbows.",
    ],
    "Barbell Squat": [
        "Brace your core hard before you descend — take a big breath and hold it.",
        "Drive through your whole foot: heel, big toe, little toe.",
        "Aim for hip crease below knee, but only as deep as your mobility allows.",
    ],
    "Romanian Deadlift": [
        "Push your hips back, don't squat down — feel the stretch in your hamstrings.",
        "Keep the bar close to your legs the whole way down.",
        "Never round your lower back; stop when your spine wants to curl.",
    ],
    "Lateral Raise": [
        "Lead with your elbows and imagine pouring water from two jugs.",
        "Keep it light — momentum here just trains your traps, not your delts.",
        "A slow 3-second lower is where the muscle is built.",
    ],
    "Dumbbell Curl": [
        "Pin your elbows to your sides; if they drift forward you're using your shoulders.",
        "Squeeze hard at the top for a full second.",
        "Lower slowly — don't just drop the weight.",
    ],
    "Push-ups": [
        "Keep your body in one straight line — squeeze your glutes and brace your core.",
        "Elbows at about 45 degrees from your torso, not flared out wide.",
        "Lower until your chest is just above the floor for full range.",
    ],
    "Plank": [
        "Tuck your pelvis slightly so your lower back doesn't sag.",
        "Squeeze everything: glutes, quads, core. A plank is full-body tension.",
        "Breathe steadily — don't hold your breath.",
    ],
    "Goblet Squat": [
        "Keep your chest tall and the dumbbell close to your body.",
        "Let your elbows track inside your knees at the bottom.",
        "Drive through your heels to stand.",
    ],
    "Overhead Press": [
        "Squeeze your glutes to stop your lower back from arching.",
        "Move your head slightly back to let the bar pass, then through at the top.",
        "Press in a straight vertical line, not forward.",
    ],
    "Walking Lunges": [
        "Keep your front knee tracking over your ankle, not past your toes.",
        "Push through your front heel to rise.",
        "Keep your torso upright the whole time.",
    ],
    "Seated Cable Row": [
        "Sit tall and avoid yanking with your lower back.",
        "Pull to your lower chest with elbows close to your sides.",
        "Pause with your shoulder blades fully squeezed together.",
    ],
    "Mountain Climbers": [
        "Keep your hips low and level — don't let them pike up.",
        "Drive your knees toward your chest in a steady rhythm.",
        "Keep your hands firmly under your shoulders.",
    ],
    "Jumping Jacks": [
        "Land softly on the balls of your feet to protect your knees.",
        "Keep a light, steady rhythm.",
        "Fully extend your arms overhead each rep.",
    ],
}

DEFAULT_TIPS = [
    "Control the lowering (eccentric) phase — that's where growth happens.",
    "Breathe out on the effort, in on the easier phase.",
    "If your form breaks down, lower the weight. Ego lifts cause injuries.",
]


def tips_for(name: str):
    return TIPS.get(name, DEFAULT_TIPS)
