import json
from pathlib import Path
import random

POOL_FILE = Path("question_pool.json")


def load_pool():
    with open(POOL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_pool(pool):
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, indent=2)


def select_questions(
    num_technical=5,
    num_scenario=3,
    num_coding=2
):
    pool = load_pool()
    selected = []

    # Helper function to pick unused questions
    def pick(qtype, count):
        available = [
            q for q in pool["questions"][qtype]
            if not q["used"]
        ]

        chosen = random.sample(
            available,
            min(count, len(available))
        )

        for q in chosen:
            q["used"] = True

        return chosen

    selected.extend(pick("technical", num_technical))
    selected.extend(pick("scenario", num_scenario))
    selected.extend(pick("coding", num_coding))

    save_pool(pool)
    return selected
